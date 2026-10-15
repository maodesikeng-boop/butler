from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict
    model_config = ConfigDict(frozen=True)


class ToolResult(BaseModel):
    call_id: str
    content: str
    status: Literal["ok", "error", "timeout"]
    model_config = ConfigDict(frozen=True)


class Tool(BaseModel):
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[str]]
    read_only: bool = False
    parallel_safe: bool = False
    timeout_s: float = 60.0
    model_config = ConfigDict(frozen=True)
