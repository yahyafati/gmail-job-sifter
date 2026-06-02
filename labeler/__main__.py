import os.path
import sqlite3
import sys
from configparser import ConfigParser
from datetime import datetime
from typing import Optional, TypedDict, Iterable, List, Dict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from classifier.text_cleaner import TextCleaner
from classifier.utils import (
    classify_email,
    get_ranked_llms,
    create_clients,
    NONE_CONTENT_FLAG,
)
from labeler.parser import parse_message, normalize_email_date
from utils.config import load_config, set_runtime_value
from utils.db import create_connection, close_connections
from utils.log import create_logger, add_file_handler

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

logger = create_logger(None, __name__)


def load_creds(config: ConfigParser) -> Credentials | None:
    token_path = config["labeler"].get("token_path", "token.json")
    credentials_path = config["labeler"].get("credentials_path", "credentials.json")

    logger.info("Loading credentials (token_path=%s)", token_path)

    creds: Optional[Credentials] = None

    if os.path.exists(token_path):
        logger.debug("Token file exists, attempting to load")
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        logger.info("Credentials invalid or missing, refreshing/reauthenticating")

        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials")
            try:
                creds.refresh(Request())
            except Exception:
                logger.exception("Failed to refresh credentials")
                raise
        else:
            logger.info("Starting OAuth flow")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        if creds:
            logger.debug("Saving refreshed credentials to %s", token_path)
            with open(token_path, "w") as token:
                token.write(creds.to_json())

    logger.info("Credentials ready (valid=%s)", bool(creds and creds.valid))
    return creds


class LabelNode(TypedDict):
    id: Optional[str]
    children: dict[str, "LabelNode"]


class GMailLabel(TypedDict):
    id: str
    name: str


def populate_label_tree(
    service: Resource,
    label_tree: dict[str, LabelNode],
    labels_dict: dict[str, GMailLabel],
    prefix="",
):
    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")

        logger.debug("Processing label: %s", full_name)

        label = labels_dict.get(full_name)

        if label:
            logger.debug("Label exists: %s (id=%s)", full_name, label["id"])
            label_node["id"] = label["id"]
        else:
            logger.info("Creating label: %s", full_name)
            try:
                created_label: GMailLabel = (
                    service.users()
                    .labels()
                    .create(
                        userId="me",
                        body={
                            "name": full_name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                    .execute()
                )
            except Exception:
                logger.exception("Failed to create label: %s", full_name)
                raise

            label_node["id"] = created_label["id"]
            labels_dict[full_name] = created_label

            logger.info("Created label: %s (id=%s)", full_name, created_label["id"])

        populate_label_tree(
            service,
            label_node["children"],
            labels_dict,
            prefix=full_name,
        )


def flatten_tree(label_tree: dict[str, LabelNode], prefix=""):
    tree: dict[str, LabelNode] = {}

    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")
        tree[full_name] = label_node

        logger.debug("Flattened label: %s -> %s", full_name, label_node["id"])

        flattened_child = flatten_tree(label_node["children"], prefix=full_name)
        tree.update(flattened_child)

    return tree


def ensure_labels(creds: Credentials) -> dict[str, LabelNode]:
    logger.info("Ensuring Gmail labels exist")

    service = build("gmail", "v1", credentials=creds)

    try:
        results = service.users().labels().list(userId="me").execute()
    except Exception:
        logger.exception("Failed to fetch existing labels")
        raise

    labels: list[GMailLabel] = results.get("labels", [])
    logger.info("Fetched %d existing labels", len(labels))

    labels_dict = {label["name"]: label for label in labels}

    label_tree: dict[str, LabelNode] = {
        "Job": LabelNode(
            id=None,
            children={
                "Application": LabelNode(id=None, children={}),
                "Interview": LabelNode(id=None, children={}),
                "Rejection": LabelNode(id=None, children={}),
                "Advertisement": LabelNode(id=None, children={}),
            },
        )
    }

    populate_label_tree(service, label_tree, labels_dict, "")
    flat = flatten_tree(label_tree)

    logger.info("Label tree ready (%d labels)", len(flat))

    return flat


def _generate_data_from_db_(cur: sqlite3.Cursor, chunk_size=64):
    query = """
            SELECT message_id, category
            FROM emails
            WHERE category IS NOT NULL AND category != 'None' \
            """

    logger.info("Executing query for labeled emails")

    try:
        res = cur.execute(query)
    except sqlite3.Error:
        logger.exception("Database query failed")
        raise

    batch_index = 0

    while True:
        rows = res.fetchmany(chunk_size)

        if not rows:
            logger.info("No more rows to process")
            break

        batch_index += 1
        logger.debug("Fetched batch %d (%d rows)", batch_index, len(rows))

        grouped_messages: dict[str, list[str]] = {}

        for message_id, category in rows:
            category = category.replace(" ", "/")

            grouped_messages.setdefault(category, []).append(message_id)

        logger.info(
            "Batch %d grouped into %d labels", batch_index, len(grouped_messages)
        )

        yield grouped_messages


def list_message_refs(
    service: Resource, chunk_size: int, user_id: str = "me"
) -> Iterable[List[Dict[str, str]]]:
    page_token = None
    page_number = 0
    logger.info(
        "Starting to list messages for user: %s with batch size: %s",
        user_id,
        chunk_size,
    )

    while True:
        page_number += 1
        response = (
            service.users()
            .messages()
            .list(
                userId=user_id,
                maxResults=chunk_size,
                pageToken=page_token,
            )
            .execute()
        )
        messages = response.get("messages", [])
        if messages:
            logger.info(
                "Fetched Gmail message reference page %s with %s messages",
                page_number,
                len(messages),
            )
            yield messages

        page_token = response.get("nextPageToken")
        if not page_token:
            logger.info("Reached end of Gmail message list after %s pages", page_number)
            break


def _generate_data_from_gmail_(config: ConfigParser, service: Resource, chunk_size=64):
    logger.info("Starting Gmail data generation pipeline.")

    ranked_llms = get_ranked_llms(config)
    logger.debug(f"Ranked LLMs retrieved: {ranked_llms}")
    if len(ranked_llms) == 0:
        logger.fatal("At least one LLM definition needed.")
        sys.exit(32)
    logger.info(f"{len(ranked_llms)} ranked LLM(s) loaded.")

    ranked_clients = create_clients(ranked_llms, logger)
    logger.debug(f"{len(ranked_clients)} OpenAI clients initialized.")

    text_cleaner = TextCleaner(logger)
    logger.debug("TextCleaner initialized.")

    oldest_date = normalize_email_date(config.get("labeler", "after_date"))
    logger.info(f"Oldest allowed email date (after_date): {oldest_date}")

    continue_fetching = True
    batch_index = 0

    for batch_refs in list_message_refs(service=service, chunk_size=chunk_size):
        batch_index += 1
        batch_size = len(batch_refs)
        logger.info(
            f"Processing batch #{batch_index} with {batch_size} message ref(s)."
        )

        grouped_messages: dict[str, list[str]] = {}
        processed_count = 0
        skipped_old = 0
        skipped_no_classification = 0

        for message_ref in batch_refs:
            message_id = message_ref["id"]
            logger.debug(f"Fetching full message for ID: {message_id}")

            try:
                raw_message = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="full",
                    )
                    .execute()
                )
                logger.debug(f"Successfully fetched raw message for ID: {message_id}")
            except Exception as e:
                logger.error(
                    f"Failed to fetch message ID {message_id}: {e}", exc_info=True
                )
                continue

            message = parse_message(raw_message)
            email_date = message.get("date")
            logger.debug(f"Message ID {message_id} — parsed date: {email_date}")

            if email_date and oldest_date and email_date < oldest_date:
                logger.info(
                    f"Message ID {message_id} dated {email_date} is older than cutoff "
                    f"{oldest_date}. Stopping fetch."
                )
                skipped_old += 1
                continue_fetching = False
                break

            logger.debug(f"Classifying message ID: {message_id}")
            classification = classify_email(
                ranked_clients, text_cleaner, ranked_llms, message, logger
            )
            logger.debug(
                f"Message ID {message_id} — classification result: '{classification}'"
            )

            if classification in [NONE_CONTENT_FLAG, "None"]:
                logger.debug(
                    f"Message ID {message_id} skipped — no meaningful content classification."
                )
                skipped_no_classification += 1
                continue

            if classification:
                category = classification.replace(" ", "/")
                grouped_messages.setdefault(category, []).append(message_id)
                logger.debug(
                    f"Message ID {message_id} assigned to category: '{category}'"
                )
            else:
                logger.warning(
                    f"Message ID {message_id} returned a falsy classification: {classification!r}"
                )
                skipped_no_classification += 1

            processed_count += 1

        category_summary = {cat: len(ids) for cat, ids in grouped_messages.items()}
        logger.info(
            f"Batch #{batch_index} complete — processed: {processed_count}, "
            f"skipped (too old): {skipped_old}, skipped (no classification): {skipped_no_classification}. "
            f"Categories: {category_summary}"
        )

        yield grouped_messages

        if not continue_fetching:
            logger.info("Reached oldest_date cutoff — stopping batch iteration.")
            break

    logger.info(
        f"Gmail data generation pipeline finished after {batch_index} batch(es)."
    )


def generate_data(
    config: ConfigParser,
    cur: Optional[sqlite3.Cursor],
    service: Optional[Resource] = None,
    live_mode: bool = False,
    chunk_size=64,
):
    if not live_mode:
        if not cur:
            logger.error(
                "Database Cursor argument missing for a offline mode data generation."
            )
            raise ValueError(
                "Database Cursor argument missing for a offline mode data generation."
            )
        return _generate_data_from_db_(cur, chunk_size)

    if not service:
        logger.error("Service argument missing for a live_mode data generation.")
        raise ValueError("Service argument missing for a live_mode data generation.")
    return _generate_data_from_gmail_(config, service, chunk_size)


def main():
    logger.info("=== Gmail Labeler Started ===")

    config = load_config()
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    set_runtime_value(config, "run_id", run_id)
    add_file_handler(config, logger, "labeler.log")

    con, read_cur, write_cur = create_connection(config)
    logger.info("Database connection established")

    creds = load_creds(config)
    if not creds:
        logger.error("No credentials available, exiting")
        return

    label_tree = ensure_labels(creds)

    live_mode = config.get("labeler", "live_mode").lower().strip() in [
        "true",
        "on",
        "1",
    ]
    logger.info(f"Live Mode: {'on' if live_mode else 'off'}")

    service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail service initialized")

    total_messages = 0
    total_batches = 0

    for batch in generate_data(config, read_cur, service, live_mode):
        total_batches += 1

        if len(batch) == 0:
            logger.info("No more data in batch!")
            break

        for label, ids in batch.items():
            label_id = label_tree[label]["id"]

            logger.info(
                "Applying label '%s' (id=%s) to %d messages",
                label,
                label_id,
                len(ids),
            )

            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": ids, "addLabelIds": [label_id]},
                ).execute()
            except Exception:
                logger.exception(
                    "Failed to label messages (label=%s, count=%d)",
                    label,
                    len(ids),
                )
                continue

            total_messages += len(ids)

    logger.info(
        "Processing complete (batches=%d, messages=%d)",
        total_batches,
        total_messages,
    )


if __name__ == "__main__":
    try:
        logger.debug("Labeler Entry point reached")
        main()
    except KeyboardInterrupt:
        logger.fatal("User interrupted; aborting.")
    except Exception:
        logger.exception("Unhandled exception in main(); aborting")
        raise
    finally:
        logger.debug("Running cleanup for any closeable resource(s)")
        close_connections()
        logger.info("Cleanup complete")
