from typing import Protocol, TypedDict

from typing_extensions import runtime_checkable


@runtime_checkable
class Closeable(Protocol):
    def close(self) -> None: ...


class EmailObject(TypedDict):
    message_id: str
    subject: str
    body: str
    sender: str


class ClassifiedEmail(TypedDict):
    message_id: str
    subject: str
    body: str
    sender: str
    classification: str


class ExceptionEmails(TypedDict):
    message_id: str
    exception: str
    message: str
    body: object


class LLMConfig(TypedDict):
    name: str
    api_key: str
    base_url: str
    model: str
