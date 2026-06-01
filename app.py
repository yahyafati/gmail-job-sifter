from configparser import ConfigParser

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionSystemMessageParam,
)


def load_config(config_path="config.ini"):
    config = ConfigParser()
    config.read(config_path)
    return config


def main():
    config = load_config()
    client = OpenAI(
        api_key=config["llm"]["api_key"], base_url=config["llm"]["base_url"]
    )

    completion = client.chat.completions.create(
        model="kimi-k2.6",
        messages=[
            ChatCompletionSystemMessageParam(
                role="system",
                content="You are Kimi, an AI assistant provided by Moonshot AI. You are proficient in Chinese and English conversations. You provide users with safe, helpful, and accurate answers. You will reject any requests involving terrorism, racism, or explicit content. Moonshot AI is a proper noun and should not be translated.",
            ),
            ChatCompletionUserMessageParam(
                role="user", content="Hello, my name is Li Lei. What is 1+1?"
            ),
        ],
    )

    print(completion.choices[0].message.content)


if __name__ == "__main__":
    main()
