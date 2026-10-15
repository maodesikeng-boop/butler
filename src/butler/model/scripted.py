from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from butler.messages import Message
from butler.model.base import ModelReply
from butler.tools.base import ToolSpec


class ModelRequest(BaseModel):
    system: str
    messages: Sequence[Message]
    tools: Sequence[ToolSpec]
    model_config = ConfigDict(frozen=True)


class ScriptedModel:
    def __init__(self, responses: Sequence[ModelReply]) -> None:
        self.requests: list[ModelRequest] = []
        self.responses: list[ModelReply] = list(responses)

    async def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelReply:
        self.requests.append(ModelRequest(system=system, messages=messages, tools=tools))
        try:
            response = self.responses[len(self.requests) - 1]
            return response
        except IndexError:
            raise RuntimeError(
                f"this is the {len(self.requests)}th request, \
                but only {len(self.responses)} responses are available"
            ) from None
