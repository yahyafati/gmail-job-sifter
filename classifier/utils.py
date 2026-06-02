import json
import re
from collections import OrderedDict
from configparser import ConfigParser
from logging import Logger
from pathlib import Path
from typing import (
    List,
    Optional,
    Tuple,
)

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)

from classifier.prompts import system_prompt, user_prompt
from classifier.text_cleaner import TextCleaner
from classifier.types import LLMConfig, EmailObject, ClassifiedEmail
from utils.misc import get_override_safe_path

NONE_CONTENT_FLAG = "CONTENT_WAS_NONE"


def get_ranked_llms(config: ConfigParser) -> List[LLMConfig]:
    llms: List[Tuple[int, LLMConfig]] = []

    for section in config.sections():
        match = re.match(r"llm\.(\d+)", section)
        if match:
            rank = int(match.group(1))
            llms.append(
                (
                    rank,
                    LLMConfig(
                        name=config.get(section, "name", fallback=f"llm_{rank}"),
                        api_key=config.get(section, "api_key"),
                        base_url=config.get(section, "base_url"),
                        model=config.get(section, "model"),
                    ),
                )
            )

    llms.sort(key=lambda x: x[0])

    return [llm for _, llm in llms]


def create_clients(llms: List[LLMConfig], logger: Logger) -> OrderedDict[str, OpenAI]:
    logger.info("Initialising OpenAI clients")
    clients: OrderedDict[str, OpenAI] = OrderedDict()
    for llm_config in llms:
        logger.info(
            "Initialising client (name = '%s', base_url = '%s', model='%s', api_key = '%s')",
            llm_config["name"],
            llm_config["base_url"],
            llm_config["model"],
            "YOU WISH",
        )
        client = OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config["base_url"],
        )
        clients[llm_config["name"]] = client
    return clients


def classify_email(
    clients: OrderedDict[str, OpenAI],
    text_cleaner: TextCleaner,
    llm_configs: List[LLMConfig],
    email: EmailObject,
    logger: Logger,
) -> Optional[str]:

    for i, (provider_name, client) in enumerate(clients.items()):
        model = llm_configs[i]["model"]
        try:
            logger.info(
                "Classifying email message_id='%s' and title='%s' using model='%s', provider='%s'",
                email["message_id"],
                email["subject"][:30],
                model,
                provider_name,
            )
            clean_email = EmailObject(**email)
            clean_email["body"] = text_cleaner.clean_text(email["body"])
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    ChatCompletionSystemMessageParam(
                        role="system", content=system_prompt()
                    ),
                    ChatCompletionUserMessageParam(
                        role="user",
                        content=user_prompt(clean_email),
                    ),
                ],
            )

            response_content = completion.choices[0].message.content

            if response_content is None:
                logger.warning(
                    "LLM returned None content for message_id='%s'; flagging as '%s'",
                    email["message_id"],
                    NONE_CONTENT_FLAG,
                )
                return NONE_CONTENT_FLAG

            classification = response_content.strip()
            logger.debug(
                "Classified message_id='%s' as '%s'",
                email["message_id"],
                classification,
            )
            return classification
        except Exception as err:
            logger.exception(
                "LLM API call failed for message_id='%s': %s", email["message_id"], err
            )

    return None


def save_to_json(
    config: ConfigParser, temp_data: List[ClassifiedEmail], logger: Logger
):
    parent_path = Path(config["dev"]["output_path"])
    logger.info(
        "Saving %d classified emails to JSON under '%s'", len(temp_data), parent_path
    )

    parent_path.mkdir(parents=True, exist_ok=True)
    logger.debug("Output directory ensured: '%s'", parent_path)

    output_path = get_override_safe_path(parent_path / "sample.json")
    logger.info("Writing JSON output to '%s'", output_path)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(temp_data, f, indent=4, ensure_ascii=False)
        logger.info("JSON file written successfully: '%s'", output_path)
    except OSError as e:
        logger.exception("Failed to write JSON output to '%s': %s", output_path, e)
        raise
