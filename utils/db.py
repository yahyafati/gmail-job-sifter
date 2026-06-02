import sqlite3
from configparser import ConfigParser
from typing import List

from utils.log import create_logger

logger = create_logger(None, __name__)

OPEN_CONNECTIONS: List[sqlite3.Connection] = []


def create_connection(
    config: ConfigParser,
) -> tuple[sqlite3.Connection, sqlite3.Cursor, sqlite3.Cursor]:
    db_path = config["classifier"]["db_path"]
    logger.info("Connecting to SQLite database at '%s'", db_path)
    try:
        con = sqlite3.connect(db_path)
        OPEN_CONNECTIONS.append(con)
        logger.debug("Database connection established and registered for cleanup")
    except sqlite3.Error as e:
        logger.exception("Failed to connect to database at '%s': %s", db_path, e)
        raise
    read_cursor = con.cursor()
    write_cursor = con.cursor()
    return con, read_cursor, write_cursor


def close_connections():
    for con in OPEN_CONNECTIONS:
        try:
            con.close()
            logger.debug("Closed resource: %s", con)
        except Exception as err:
            logger.warning("Failed to close resource %s: %s", con, err)
