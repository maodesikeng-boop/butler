import pytest
from pydantic import ValidationError

from butler.messages import AssistantMessage, ToolCall, ToolMessage, UserMessage
from butler.model.base import ModelReply, Usage


def make_usage() -> Usage:
    return Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


def test_usage_holds_the_three_token_counts() -> None:
    usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


@pytest.mark.parametrize("missing", ["prompt_tokens", "completion_tokens", "total_tokens"])
def test_usage_requires_every_count(missing: str) -> None:
    data = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    del data[missing]

    with pytest.raises(ValidationError):
        Usage.model_validate(data)


def test_usage_counts_must_be_numbers() -> None:
    with pytest.raises(ValidationError):
        Usage.model_validate({"prompt_tokens": "很多", "completion_tokens": 5, "total_tokens": 15})


def test_usage_cannot_be_modified_after_creation() -> None:
    usage = make_usage()

    with pytest.raises(ValidationError):
        usage.total_tokens = 999


def test_a_reply_holds_the_assistant_message() -> None:
    message = AssistantMessage(content="你好")

    reply = ModelReply(message=message)

    assert reply.message == message


def test_a_reply_without_usage_is_allowed() -> None:
    # 假模型不用每次都编一个用量
    reply = ModelReply(message=AssistantMessage(content="你好"))

    assert reply.usage is None


def test_a_reply_can_carry_the_usage() -> None:
    usage = make_usage()

    reply = ModelReply(message=AssistantMessage(content="你好"), usage=usage)

    assert reply.usage == usage
    assert reply.usage is not None
    assert reply.usage.total_tokens == 15


def test_a_reply_can_ask_for_tool_calls() -> None:
    call = ToolCall(id="call_1", name="current_time", arguments="{}")

    reply = ModelReply(message=AssistantMessage(content=None, tool_calls=[call]))

    assert reply.message.tool_calls == [call]


def test_a_reply_requires_a_message() -> None:
    with pytest.raises(ValidationError):
        ModelReply.model_validate({"usage": None})


@pytest.mark.parametrize(
    "not_an_assistant_message",
    [UserMessage(content="我是用户"), ToolMessage(tool_call_id="call_1", content="工具结果")],
    ids=["user_message", "tool_message"],
)
def test_a_reply_must_be_an_assistant_message(not_an_assistant_message: object) -> None:
    # 模型回来的只可能是助手消息
    with pytest.raises(ValidationError):
        ModelReply.model_validate({"message": not_an_assistant_message})


def test_a_reply_cannot_be_modified_after_creation() -> None:
    reply = ModelReply(message=AssistantMessage(content="你好"))

    with pytest.raises(ValidationError):
        reply.usage = make_usage()


def test_a_reply_survives_a_round_trip_through_json() -> None:
    call = ToolCall(id="call_1", name="current_time", arguments='{"timezone": "UTC"}')
    reply = ModelReply(
        message=AssistantMessage(content=None, tool_calls=[call]), usage=make_usage()
    )

    restored = ModelReply.model_validate_json(reply.model_dump_json())

    assert restored == reply
