from configparser import ConfigParser

RUNTIME_SECTION_NAME = "RUNTIME"


def set_runtime_value(config: ConfigParser, option: str, value: str):
    if not config.has_section(RUNTIME_SECTION_NAME):
        config.add_section(RUNTIME_SECTION_NAME)
    config.set(RUNTIME_SECTION_NAME, option, value)


def get_runtime_value(config: ConfigParser, option: str) -> str:
    value = config.get(RUNTIME_SECTION_NAME, option)
    return value
