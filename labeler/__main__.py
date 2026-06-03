import os.path
from configparser import ConfigParser
from datetime import datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from labeler.generators import generate_data
from labeler.label_loader import ensure_labels
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

    label_tree = ensure_labels(creds, logger)

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

    for batch in generate_data(
        config, logger, read_cur, service, live_mode, update_chunk_size=10
    ):
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
