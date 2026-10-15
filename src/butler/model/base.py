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


class ScriptedModel(ModelClient):
    def __init__(self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> None:
        self.system = system
        self.messages = messages
        self.tools = tools
        self.times = 0

    async def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelReply:
        self.times += 1
        return ModelReply(
            message=AssistantMessage(content=f"这是第{self.times}次回答"),
            usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
