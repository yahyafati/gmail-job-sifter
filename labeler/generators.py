import sqlite3
import sys
from configparser import ConfigParser
from logging import Logger
from typing import Iterable, List, Dict, Optional

from googleapiclient.discovery import Resource

from classifier.text_cleaner import TextCleaner
from classifier.utils import (
    get_ranked_llms,
    create_clients,
    classify_email,
    NONE_CONTENT_FLAG,
)
from labeler.parser import normalize_email_date, parse_message


def _generate_data_from_db_(cur: sqlite3.Cursor, logger: Logger, chunk_size=64):
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
    service: Resource, chunk_size: int, logger: Logger, user_id: str = "me"
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


def _generate_data_from_gmail_(
    config: ConfigParser,
    service: Resource,
    logger: Logger,
    chunk_size=64,
    update_chunk_size: Optional[int] = None,
):
    logger.info("Starting Gmail data generation pipeline.")

    ranked_llms = get_ranked_llms(config)
    logger.debug("Ranked LLM configs loaded: %d entries", len(ranked_llms))

    if not ranked_llms:
        logger.fatal("No LLM definitions found. At least one is required.")
        sys.exit(32)

    logger.info("LLM configuration initialized (%d models).", len(ranked_llms))

    ranked_clients = create_clients(ranked_llms, logger)
    logger.debug("LLM clients initialized (%d clients).", len(ranked_clients))

    text_cleaner = TextCleaner(logger)
    logger.debug("TextCleaner initialized.")

    oldest_date = normalize_email_date(config.get("labeler", "after_date"))
    logger.info("Email cutoff date (after_date) resolved to: %s", oldest_date)

    continue_fetching = True
    batch_index = 0

    for batch_refs in list_message_refs(
        service=service, logger=logger, chunk_size=chunk_size
    ):
        batch_index += 1
        batch_size = len(batch_refs)

        logger.info(
            "Processing Gmail batch #%d (%d message refs)",
            batch_index,
            batch_size,
        )

        grouped_messages: dict[str, list[str]] = {}

        processed_count = 0
        skipped_old = 0
        skipped_no_classification = 0
        failed_fetch = 0

        for message_ref in batch_refs:
            message_id = message_ref["id"]
            logger.debug("Fetching Gmail message (id=%s)", message_id)

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
            except Exception:
                failed_fetch += 1
                logger.exception("Failed to fetch message (id=%s)", message_id)
                continue

            logger.debug("Message fetched successfully (id=%s)", message_id)

            message = parse_message(raw_message)
            email_date = message.get("date")

            logger.debug(
                "Parsed message metadata (id=%s, date=%s)",
                message_id,
                email_date,
            )

            if email_date and oldest_date and email_date < oldest_date:
                skipped_old += 1

                logger.info(
                    "Cutoff reached. Message too old (id=%s, date=%s < cutoff=%s). "
                    "Stopping batch early.",
                    message_id,
                    email_date,
                    oldest_date,
                )

                continue_fetching = False
                break

            logger.debug("Classifying message (id=%s)", message_id)

            classification = classify_email(
                ranked_clients, text_cleaner, ranked_llms, message, logger
            )

            logger.debug(
                "Classification result (id=%s): %r",
                message_id,
                classification,
            )

            if classification in [NONE_CONTENT_FLAG, "None", None]:
                skipped_no_classification += 1
                logger.debug(
                    "Message skipped (id=%s): no meaningful classification",
                    message_id,
                )
                continue

            category = classification.replace(" ", "/")
            grouped_messages.setdefault(category, []).append(message_id)

            logger.debug(
                "Assigned category (id=%s -> %s)",
                message_id,
                category,
            )

            processed_count += 1

            if update_chunk_size and processed_count % update_chunk_size == 0:
                logger.info(
                    "Yielding intermediate batch result (batch=%d, processed=%d)",
                    batch_index,
                    processed_count,
                )
                yield grouped_messages
                grouped_messages = {}

        category_summary = {k: len(v) for k, v in grouped_messages.items()}

        logger.info(
            "Completed Gmail batch #%d | processed=%d | fetched_failures=%d | "
            "skipped_old=%d | skipped_no_classification=%d | categories=%s",
            batch_index,
            processed_count,
            failed_fetch,
            skipped_old,
            skipped_no_classification,
            category_summary,
        )

        logger.debug("Yielding final batch result for batch #%d", batch_index)
        yield grouped_messages

        if not continue_fetching:
            logger.info(
                "Stopping pipeline: oldest_date cutoff reached (batch=%d).",
                batch_index,
            )
            break

    logger.info(
        "Gmail data generation pipeline finished (total_batches=%d).",
        batch_index,
    )


def generate_data(
    config: ConfigParser,
    logger: Logger,
    cur: Optional[sqlite3.Cursor] = None,
    service: Optional[Resource] = None,
    live_mode: bool = False,
    chunk_size=64,
    update_chunk_size: Optional[int] = None,
):
    if not live_mode:
        if not cur:
            logger.error(
                "Database Cursor argument missing for a offline mode data generation."
            )
            raise ValueError(
                "Database Cursor argument missing for a offline mode data generation."
            )
        return _generate_data_from_db_(cur, logger, chunk_size)

    if not service:
        logger.error("Service argument missing for a live_mode data generation.")
        raise ValueError("Service argument missing for a live_mode data generation.")
    return _generate_data_from_gmail_(
        config, service, logger, chunk_size, update_chunk_size
    )
