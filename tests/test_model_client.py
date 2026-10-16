import inspect
import typing
from collections.abc import Sequence

from butler.messages import AssistantMessage, Message, ToolMessage, UserMessage
from butler.model.base import ModelClient, ModelReply
from butler.tools.base import ToolSpec


class EchoModel:
    """一个符合 ModelClient 约定的最小实现：把收到的东西数一数，写进回复里。"""

    async def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelReply:
        text = f"{system}|{len(messages)}|{len(tools)}"
        return ModelReply(message=AssistantMessage(content=text))


def as_client() -> ModelClient:
    # 这一行由 pyright 检查：EchoModel 必须符合 ModelClient 的约定，否则 make check 会报错
    return EchoModel()


def test_message_is_the_name_for_any_kind_of_message() -> None:
    # Message 是"任意一种消息"的名字：用户、助手、工具三种都算
    messages: list[Message] = [
        UserMessage(content="你好"),
        AssistantMessage(content="你好"),
        ToolMessage(tool_call_id="call_1", content="结果"),
    ]

    assert [m.role for m in messages] == ["user", "assistant", "tool"]


def test_model_client_is_a_protocol() -> None:
    assert typing.is_protocol(ModelClient)


def test_complete_is_an_async_method() -> None:
    assert inspect.iscoroutinefunction(ModelClient.complete)


def test_complete_takes_the_system_prompt_the_messages_and_the_tools_in_that_order() -> None:
    parameters = list(inspect.signature(ModelClient.complete).parameters)

    assert parameters == ["self", "system", "messages", "tools"]


def test_complete_gives_back_a_model_reply() -> None:
    hints = typing.get_type_hints(ModelClient.complete)

    assert hints["return"] is ModelReply


def test_the_system_prompt_is_a_piece_of_text() -> None:
    hints = typing.get_type_hints(ModelClient.complete)

    assert hints["system"] is str


async def test_a_class_with_the_right_method_can_be_used_as_a_model_client() -> None:
    client = as_client()

    reply = await client.complete(
        system="你是助手", messages=[UserMessage(content="你好")], tools=[]
    )

    assert isinstance(reply, ModelReply)
    assert reply.message.content == "你是助手|1|0"


async def test_the_arguments_can_also_be_given_by_position() -> None:
    spec = ToolSpec(name="current_time", description="查询当前时间", parameters={})

    reply = await as_client().complete("提示词", [UserMessage(content="你好")], [spec])

    assert reply.message.content == "提示词|1|1"
