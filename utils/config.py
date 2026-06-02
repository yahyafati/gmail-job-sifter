from configparser import ConfigParser
from typing import Literal, cast

from utils.log import create_logger

logger = create_logger(None, __name__)
RUNTIME_SECTION_NAME = "RUNTIME"
MODE = Literal["dev", "prod"]
DEFAULT_MODE: MODE = "prod"
mode: MODE = DEFAULT_MODE


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


def init_mode(config: ConfigParser) -> MODE:
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


def set_runtime_value(config: ConfigParser, option: str, value: str):
    if not config.has_section(RUNTIME_SECTION_NAME):
        config.add_section(RUNTIME_SECTION_NAME)
    config.set(RUNTIME_SECTION_NAME, option, value)


def get_runtime_value(config: ConfigParser, option: str) -> str:
    value = config.get(RUNTIME_SECTION_NAME, option)
    return value
