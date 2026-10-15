from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class UserMessage(FrozenModel):
    role: Literal["user"] = "user"
    content: str


class ToolCall(FrozenModel):
    id: str
    name: str
    arguments: str


class AssistantMessage(FrozenModel):
    role: Literal["assistant"] = "assistant"
    content: str | None
    tool_calls: list[ToolCall] = []


class ToolMessage(FrozenModel):
    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str


message = Annotated[UserMessage | AssistantMessage | ToolMessage, Field(discriminator="role")]


class Messages(BaseModel):
    content: list[message] = []
