from dataclasses import dataclass
from typing import Any


@dataclass
class Delta:
    text: str


@dataclass
class Done:
    message_id: str
    usage: dict[str, Any] | None


@dataclass
class Error:
    message: str


StreamEvent = Delta | Done | Error
