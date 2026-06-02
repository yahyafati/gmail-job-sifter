import logging
import pathlib
from configparser import ConfigParser
from logging import Logger
from typing import Optional

__formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def create_logger(
    config: Optional[ConfigParser],
    name: str,
    level: str | int = logging.INFO,
    console: bool = True,
    file_name: Optional[str] = None,
) -> Logger:

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(__formatter)

        logger.addHandler(console_handler)

    if file_name:
        if config:
            add_file_handler(config, logger, file_name)
        else:
            raise ValueError("Config is None, can't file logs root path")

    return logger


def add_file_handler(config: ConfigParser, logger: Logger, file_name: str):
    from utils.config import get_runtime_value

    log_path = pathlib.Path(config.get("default", "logs_path"))
    log_path = log_path / get_runtime_value(config, "run_id")
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path / file_name)
    file_handler.setFormatter(__formatter)

    logger.addHandler(file_handler)
