import asyncio

from pydantic import ValidationError

from butler.messages import ToolCall
from butler.tools.base import Tool, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"{tool.name}已经注册过")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        if name in self._tools:
            return self._tools[name]
        return None

    def specs(self) -> list[ToolSpec]:
        result: list[ToolSpec] = []
        for tool_name in self._tools:
            name = self._tools[tool_name].name
            description = self._tools[tool_name].description
            parameters = self._tools[tool_name].args_model.model_json_schema()
            result.append(ToolSpec(name=name, description=description, parameters=parameters))
        return sorted(result, key=lambda tool_spec: tool_spec.name)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        name = tool_call.name
        call_id = tool_call.id
        if name in self._tools:
            tool = self._tools[name]
            try:
                form = tool.args_model.model_validate_json(tool_call.arguments)
            except ValidationError as error:
                return ToolResult(
                    call_id=call_id,
                    content=f"参数校验有误:{error}\n收到的原文:{tool_call.arguments}",
                    status="error",
                )
            try:
                async with asyncio.timeout(tool.timeout_s):
                    result = await tool.handler(form)
            except TimeoutError:
                return ToolResult(
                    call_id=call_id,
                    content=f"Tool {name} timed out after {tool.timeout_s}s",
                    status="timeout",
                )
            except Exception as error:
                return ToolResult(
                    call_id=call_id, content=f"{type(error).__name__}: {error}", status="error"
                )

            return ToolResult(call_id=call_id, content=result, status="ok")
        else:
            return ToolResult(call_id=call_id, content=f"Tool {name} not found", status="error")
