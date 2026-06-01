import json
import logging
import sqlite3
import uuid
from configparser import ConfigParser
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

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)

MODE = Literal["dev", "prod"]
DEFAULT_MODE: MODE = "prod"
mode: MODE = DEFAULT_MODE


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


CLOSEABLE: List[Closeable] = []


def load_config(config_path="config.ini") -> ConfigParser:
    config = ConfigParser()
    config.read(config_path)
    return config


def set_mode(config: ConfigParser) -> MODE:
    global mode
    _mode = config["default"].get("mode", mode)
    mode = cast(MODE, _mode)
    if not _mode:
        return DEFAULT_MODE
    return mode


def run_on_mode(mode_required):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if globals().get("mode") != mode_required:
                logging.info(f"Skipping {func.__name__} (requires {mode_required})")
                return None
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
    con = sqlite3.connect(config["default"]["db_path"])
    CLOSEABLE.append(con)
    return con


def get_override_safe_path(
    path: Union[Path, str], max_iter=100, uuid_on_max_iter=True
) -> Path:
    path = Path(path)
    suffix_count = 0

    original_stem = path.stem
    original_suffix = path.suffix
    parent = path.parent

    while path.exists():
        suffix_count += 1
        path = parent / f"{original_stem}_{suffix_count}{original_suffix}"

        if suffix_count >= max_iter:
            break

    if path.exists():
        if uuid_on_max_iter:
            path = parent / f"{original_stem}_{uuid.uuid4()}{original_suffix}"
        else:
            raise FileExistsError(
                f"Could not find free path after {max_iter} attempts: {path}"
            )

    return path


def get_row_count(cur: sqlite3.Cursor) -> int:
    res = cur.execute("SELECT count(*) from emails")
    count = res.fetchone()
    return count[0]


def generate_dataset(
    config: ConfigParser, cur: sqlite3.Cursor, chunk_size=64
) -> Iterator[EmailObject]:
    skip_classified = config["default"]["skip_classified"] == "True"
    query = "SELECT message_id,subject,body,sender FROM emails"
    if skip_classified:
        query = (
            "SELECT message_id,subject,body,sender FROM emails WHERE category is NULL"
        )
    res = cur.execute(query)
    while True:
        rows = res.fetchmany(chunk_size)
        if not rows:
            break
        for message_id, subject, body, sender in rows:
            email_obj = EmailObject(
                message_id=message_id,
                subject=subject,
                body=body,
                sender=sender,
            )
            yield email_obj


def update_classification(cur: sqlite3.Cursor, message_id: str, classification: str):
    cur.execute(
        "UPDATE emails SET category = ? WHERE message_id = ?",
        (classification, message_id),
    )
    cur.connection.commit()


def classify_email(config: ConfigParser, client: OpenAI, email: EmailObject) -> str:
    NONE_CONTENT_FLAG = "CONTENT_WAS_NONE"
    completion = client.chat.completions.create(
        model=config["llm"]["model"],
        messages=[
            ChatCompletionSystemMessageParam(role="system", content=system_prompt()),
            ChatCompletionUserMessageParam(role="user", content=user_prompt(email)),
        ],
    )
    response_content = completion.choices[0].message.content
    if response_content is None:
        return NONE_CONTENT_FLAG
    return response_content


def save_to_json(config: ConfigParser, temp_data: List[ClassifiedEmail]):
    parent_path = Path(config["dev"]["output_path"])
    parent_path.mkdir(parents=True, exist_ok=True)
    output_path = get_override_safe_path(parent_path / "sample.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(temp_data, f, indent=4, ensure_ascii=False)


def main():
    config = load_config()
    set_mode(config)
    con = create_connection(config)
    cur = con.cursor()
    client = OpenAI(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
    )
    total_number_of_emails = get_row_count(cur)
    print(f"Total Number of Emails: {total_number_of_emails}")

    temp_data: List[ClassifiedEmail] = []
    for i, email in enumerate(generate_dataset(config, cur)):
        print(f"Classifying {i+1}/{total_number_of_emails}")
        classification = classify_email(config, client, email)
        update_classification(
            cur,
            message_id=email["message_id"],
            classification=classification,
        )
        temp_data.append(ClassifiedEmail(classification=classification, **email))

    if globals().get("mode", "prod") == "dev":
        save_to_json(config, temp_data)


if __name__ == "__main__":
    try:
        main()
    finally:
        for item in CLOSEABLE:
            item.close()
