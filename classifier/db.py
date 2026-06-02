import sqlite3
from configparser import ConfigParser
from logging import Logger
from typing import (
    Iterator,
)

from classifier.types import EmailObject


def get_row_count(config: ConfigParser, cur: sqlite3.Cursor, logger: Logger) -> int:
    logger.debug("Querying total email row count")
    skip_classified = config["classifier"]["skip_classified"].lower() in [
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
    config: ConfigParser,
    cur: sqlite3.Cursor,
    logger: Logger,
    chunk_size=64,
) -> Iterator[EmailObject]:
    skip_classified = config["classifier"]["skip_classified"].lower() in [
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
            logger.info(
                "No more rows to fetch after %d chunks (%d emails yielded total)",
                chunk_index,
                yielded_total,
            )
            break

        logger.info(
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


def update_classification(
    cur: sqlite3.Cursor, message_id: str, classification: str, logger: Logger
):
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
