import json
import logging
import random
import sqlite3
import time
import uuid
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import (
    Protocol,
    runtime_checkable,
    List,
    Iterator,
    TypedDict,
    Literal,
    cast,
    Union,
)

from openai import OpenAI, BadRequestError
from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MODE = Literal["dev", "prod"]
DEFAULT_MODE: MODE = "prod"
mode: MODE = DEFAULT_MODE

NONE_CONTENT_FLAG = "CONTENT_WAS_NONE"


@runtime_checkable
class Closeable(Protocol):
    def close(self) -> None: ...


class EmailObject(TypedDict):
    message_id: str
    subject: str
    body: str
    sender: str


class ClassifiedEmail(TypedDict):
    message_id: str
    subject: str
    body: str
    sender: str
    classification: str


class ExceptionEmails(TypedDict):
    message_id: str
    exception: str
    message: str
    body: object


CLOSEABLE: List[Closeable] = []


def load_config(config_path="config.ini") -> ConfigParser:
    logger.debug("Loading configuration from '%s'", config_path)
    config = ConfigParser()
    files_read = config.read(config_path)
    if not files_read:
        logger.warning(
            "Config file '%s' not found or empty; using defaults", config_path
        )
    else:
        logger.info("Configuration loaded from: %s", files_read)
        logger.debug(
            "Config sections found: %s",
            config.sections(),
        )
    return config


def set_mode(config: ConfigParser) -> MODE:
    global mode
    logger.debug("Reading 'mode' from config [default] section")
    _mode = config["default"].get("mode", mode)
    mode = cast(MODE, _mode)
    if not _mode:
        logger.warning(
            "No 'mode' key found in config; falling back to DEFAULT_MODE='%s'",
            DEFAULT_MODE,
        )
        return DEFAULT_MODE
    logger.info("Application mode set to '%s'", mode)
    return mode


def run_on_mode(mode_required):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_mode = globals().get("mode")
            if current_mode != mode_required:
                logger.debug(
                    "Skipping '%s': requires mode='%s', current mode='%s'",
                    func.__name__,
                    mode_required,
                    current_mode,
                )
                return None
            logger.debug(
                "Running '%s' (mode='%s' matches requirement)",
                func.__name__,
                mode_required,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def system_prompt() -> str:
    return """
You are an email classification system.

Classify the given email into exactly one of the following categories:

* `Job Application`
* `Job Rejection`
* `Job Interview`
* `Job Advertisement`
* `None`

Definitions:

* Job Application: Confirmation or submission of an application.
* Job Rejection: Explicit decline or unsuccessful outcome.
* Job Interview: Invitation, scheduling, or discussion of an interview.
* Job Advertisement: Job offers, recruiting emails, or open positions.
* None: Not related to jobs.

Rules:

* Output only the category name.
* Do not explain your answer.
* If uncertain, choose the closest match.
    """.strip("\n")


def user_prompt(email: EmailObject) -> str:
    return f"""
From: {email['sender']}
Subject: {email['subject']}

{email['body']}
"""


def create_connection(config: ConfigParser) -> sqlite3.Connection:
    global CLOSEABLE
    db_path = config["default"]["db_path"]
    logger.info("Connecting to SQLite database at '%s'", db_path)
    try:
        con = sqlite3.connect(db_path)
        CLOSEABLE.append(con)
        logger.debug("Database connection established and registered for cleanup")
    except sqlite3.Error as e:
        logger.exception("Failed to connect to database at '%s': %s", db_path, e)
        raise
    return con


def get_override_safe_path(
    path: Union[Path, str], max_iter=100, uuid_on_max_iter=True
) -> Path:
    path = Path(path)
    logger.debug("Resolving collision-safe path for '%s'", path)
    suffix_count = 0

    original_stem = path.stem
    original_suffix = path.suffix
    parent = path.parent

    while path.exists():
        suffix_count += 1
        path = parent / f"{original_stem}_{suffix_count}{original_suffix}"
        logger.debug("Path already exists; trying '%s'", path)

        if suffix_count >= max_iter:
            break

    if path.exists():
        if uuid_on_max_iter:
            new_path = parent / f"{original_stem}_{uuid.uuid4()}{original_suffix}"
            logger.warning(
                "Reached max_iter=%d collision attempts for '%s'; "
                "falling back to UUID path '%s'",
                max_iter,
                original_stem,
                new_path,
            )
            path = new_path
        else:
            logger.error(
                "Could not find a free path after %d attempts for '%s'",
                max_iter,
                original_stem,
            )
            raise FileExistsError(
                f"Could not find free path after {max_iter} attempts: {path}"
            )

    logger.debug("Resolved safe output path: '%s'", path)
    return path


def get_row_count(config: ConfigParser, cur: sqlite3.Cursor) -> int:
    logger.debug("Querying total email row count")
    skip_classified = config["default"]["skip_classified"].lower() in [
        "true",
        "on",
        "1",
    ]
    logger.info(f"Querying total email row count (skip_classified = {skip_classified})")
    query = "SELECT count(*) FROM emails"
    if skip_classified:
        query = "SELECT count(*) FROM emails WHERE category is NULL"
    try:
        res = cur.execute(query)
        count = res.fetchone()
        total = count[0]
        logger.info("Total emails in database: %d", total)
        return total
    except sqlite3.Error as e:
        logger.exception("Failed to query row count: %s", e)
        raise


def generate_dataset(
    config: ConfigParser, cur: sqlite3.Cursor, chunk_size=64
) -> Iterator[EmailObject]:
    skip_classified = config["default"]["skip_classified"].lower() in [
        "true",
        "on",
        "1",
    ]
    logger.info(
        "Generating dataset (skip_classified=%s, chunk_size=%d)",
        skip_classified,
        chunk_size,
    )

    query = "SELECT message_id,subject,body,sender FROM emails"
    if skip_classified:
        query = (
            "SELECT message_id,subject,body,sender FROM emails WHERE category is NULL"
        )
    logger.debug("Dataset query: %s", query)

    try:
        res = cur.execute(query)
    except sqlite3.Error as e:
        logger.exception("Failed to execute dataset query: %s", e)
        raise

    chunk_index = 0
    yielded_total = 0
    while True:
        rows = res.fetchmany(chunk_size)
        if not rows:
            logger.debug(
                "No more rows to fetch after %d chunks (%d emails yielded total)",
                chunk_index,
                yielded_total,
            )
            break

        logger.debug(
            "Fetched chunk #%d with %d rows (cumulative: %d)",
            chunk_index,
            len(rows),
            yielded_total + len(rows),
        )
        chunk_index += 1

        for message_id, subject, body, sender in rows:
            email_obj = EmailObject(
                message_id=message_id,
                subject=subject,
                body=body,
                sender=sender,
            )
            logger.debug(
                "Yielding email message_id='%s' subject='%s' sender='%s'",
                message_id,
                subject,
                sender,
            )
            yielded_total += 1
            yield email_obj

    logger.info("Dataset generation complete. Total emails yielded: %d", yielded_total)


def update_classification(cur: sqlite3.Cursor, message_id: str, classification: str):
    logger.debug(
        "Updating classification for message_id='%s' to '%s'",
        message_id,
        classification,
    )
    try:
        cur.execute(
            "UPDATE emails SET category = ? WHERE message_id = ?",
            (classification, message_id),
        )
        cur.connection.commit()
        logger.debug("Classification committed for message_id='%s'", message_id)
    except sqlite3.Error as e:
        logger.exception(
            "Failed to update classification for message_id='%s': %s", message_id, e
        )
        raise


def classify_email(config: ConfigParser, client: OpenAI, email: EmailObject) -> str:
    model = config["llm"]["model"]
    logger.debug(
        "Classifying email message_id='%s' using model='%s'",
        email["message_id"],
        model,
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                ChatCompletionSystemMessageParam(
                    role="system", content=system_prompt()
                ),
                ChatCompletionUserMessageParam(role="user", content=user_prompt(email)),
            ],
        )
    except Exception as e:
        logger.exception(
            "LLM API call failed for message_id='%s': %s", email["message_id"], e
        )
        raise

    response_content = completion.choices[0].message.content

    if response_content is None:
        logger.warning(
            "LLM returned None content for message_id='%s'; flagging as '%s'",
            email["message_id"],
            NONE_CONTENT_FLAG,
        )
        return NONE_CONTENT_FLAG

    classification = response_content.strip()
    logger.debug(
        "Classified message_id='%s' as '%s'",
        email["message_id"],
        classification,
    )
    return classification


def save_to_json(config: ConfigParser, temp_data: List[ClassifiedEmail]):
    parent_path = Path(config["dev"]["output_path"])
    logger.info(
        "Saving %d classified emails to JSON under '%s'", len(temp_data), parent_path
    )

    parent_path.mkdir(parents=True, exist_ok=True)
    logger.debug("Output directory ensured: '%s'", parent_path)

    output_path = get_override_safe_path(parent_path / "sample.json")
    logger.info("Writing JSON output to '%s'", output_path)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(temp_data, f, indent=4, ensure_ascii=False)
        logger.info("JSON file written successfully: '%s'", output_path)
    except OSError as e:
        logger.exception("Failed to write JSON output to '%s': %s", output_path, e)
        raise


def sleep_stochastically(min_s: float = 0.25, max_s: float = 3.0):
    duration = random.uniform(min_s, max_s)
    logger.info(f"Sleeping for {duration:.2f} seconds")
    time.sleep(duration)


def main():
    logger.info("=== Email Classifier Starting ===")

    config = load_config()
    set_mode(config)

    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = Path(config["default"].get("logs_path", "logs")) / run_id
    log_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Current run logs can be found at: {log_path}")

    con = create_connection(config)
    cur = con.cursor()
    logger.debug("Database cursor created")

    logger.info(
        "Initialising OpenAI client (base_url='%s', model='%s')",
        config["llm"].get("base_url", "<default>"),
        config["llm"].get("model", "<unknown>"),
    )
    client = OpenAI(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
    )
    logger.debug("OpenAI client initialised")

    total_number_of_emails = get_row_count(config, cur)
    logger.info(f"Total Number of Emails: {total_number_of_emails}")

    if total_number_of_emails == 0:
        logger.warning("No emails found to classify; exiting early")
        return

    temp_data: List[ClassifiedEmail] = []
    error_items: List[ExceptionEmails] = []
    classification_counts: dict[str, int] = {}
    none_content_count = 0

    logger.info("Starting classification loop for %d emails", total_number_of_emails)
    for i, email in enumerate(generate_dataset(config, cur)):
        human_index = i + 1
        logger.debug(
            "Processing email %d/%d (message_id='%s')",
            human_index,
            total_number_of_emails,
            email["message_id"],
        )

        try:
            classification = classify_email(config, client, email)
        except BadRequestError as err:
            logger.error(
                f"Could not classify message. Skipping. Error Message: {err.message}"
            )
            error_items.append(
                ExceptionEmails(
                    message_id=email["message_id"],
                    exception="BadRequestError",
                    message=err.message,
                    body=err.body,
                )
            )
            break

        if classification == NONE_CONTENT_FLAG:
            none_content_count += 1
            logger.warning(
                "Email %d/%d (message_id='%s') received a None classification from LLM",
                human_index,
                total_number_of_emails,
                email["message_id"],
            )

        classification_counts[classification] = (
            classification_counts.get(classification, 0) + 1
        )

        update_classification(
            cur,
            message_id=email["message_id"],
            classification=classification,
        )
        temp_data.append(ClassifiedEmail(classification=classification, **email))

        if human_index % 100 == 0 or human_index == total_number_of_emails:
            logger.info(
                "Progress: %d/%d emails classified",
                human_index,
                total_number_of_emails,
            )
        sleep_stochastically()

    logger.info("Classification complete. Summary:")
    for label, count in sorted(classification_counts.items()):
        logger.info("  %-25s %d", label, count)
    if none_content_count:
        logger.warning("  Emails with None LLM response: %d", none_content_count)

    logger.info(
        f"Saving error classification details to {log_path/'error_classifications.json'}"
    )
    with open(log_path / "error_classifications.json", "w", encoding="utf-8") as f:
        json.dump(error_items, f, indent=4, ensure_ascii=False)

    current_mode = globals().get("mode", "prod")
    logger.debug("Post-classification mode check: mode='%s'", current_mode)
    if current_mode == "dev":
        logger.info("Dev mode active — saving results to JSON")
        save_to_json(config, temp_data)
    else:
        logger.info("Prod mode active — skipping JSON export")

    logger.info("=== Email Classifier Finished ===")


if __name__ == "__main__":
    try:
        logger.debug("Entry point reached")
        main()
    except KeyboardInterrupt:
        logger.fatal("User interrupted; aborting.")
    except Exception:
        logger.exception("Unhandled exception in main(); aborting")
        raise
    finally:
        logger.debug("Running cleanup for %d closeable resource(s)", len(CLOSEABLE))
        for item in CLOSEABLE:
            try:
                item.close()
                logger.debug("Closed resource: %s", item)
            except Exception as e:
                logger.warning("Failed to close resource %s: %s", item, e)
        logger.info("Cleanup complete")
