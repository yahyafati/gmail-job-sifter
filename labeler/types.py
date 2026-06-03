from typing import TypedDict, Optional


class LabelNode(TypedDict):
    id: Optional[str]
    children: dict[str, "LabelNode"]


class GMailLabel(TypedDict):
    id: str
    name: str
