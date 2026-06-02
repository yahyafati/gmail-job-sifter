import os.path
import sqlite3
from configparser import ConfigParser
from datetime import datetime
from typing import Optional, TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

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


def generate_data(cur: sqlite3.Cursor, chunk_size=64):
    query = """
    SELECT message_id, category
    FROM emails
    WHERE category IS NOT NULL AND category != 'None'
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

    service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail service initialized")

    total_messages = 0
    total_batches = 0

    for batch in generate_data(read_cur):
        total_batches += 1

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
        main()
    finally:
        logger.info("Shutting down, closing DB connections")
        close_connections()
