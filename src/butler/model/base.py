from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from butler.messages import AssistantMessage, Message
from butler.tools.base import ToolSpec


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_config = ConfigDict(frozen=True)


class ModelReply(BaseModel):
    message: AssistantMessage
    usage: Usage | None = None
    model_config = ConfigDict(frozen=True)


class ModelClient(Protocol):
    async def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelReply: ...
