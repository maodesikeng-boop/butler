from butler.messages import AssistantMessage, Messages, ToolMessage, UserMessage
from butler.model.base import ModelClient
from butler.tools.registry import ToolRegistry


async def run_turn(
    messages: Messages,
    model: ModelClient,
    tool_registry: ToolRegistry,
    user_message: UserMessage,
    system_message: str,
) -> AssistantMessage:
    messages.content.append(user_message)
    reply = await model.complete(system_message, messages.content, tool_registry.specs())
    messages.content.append(reply.message)
    while reply.message.tool_calls:
        for tool_call in reply.message.tool_calls:
            result = await tool_registry.execute(tool_call)
            messages.content.append(
                ToolMessage(role="tool", tool_call_id=tool_call.id, content=result.content)
            )
        reply = await model.complete(system_message, messages.content, tool_registry.specs())
        messages.content.append(reply.message)
    return reply.message
