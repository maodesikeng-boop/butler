import pytest
from pydantic import BaseModel, ValidationError

from butler.messages import AssistantMessage, Messages, ToolCall, ToolMessage, UserMessage


def make_history() -> Messages:
    """用户问 → 助手发起调用 → 工具结果 → 助手回答。"""
    return Messages(
        content=[
            UserMessage(content="现在几点？"),
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="current_time",
                        arguments='{"timezone": "Asia/Shanghai"}',
                    )
                ],
            ),
            ToolMessage(tool_call_id="call_1", content="2026-10-12T15:02:00+08:00"),
            AssistantMessage(content="现在是下午 3 点 02 分。"),
        ]
    )


def test_history_round_trips_through_json() -> None:
    history = make_history()

    restored = Messages.model_validate_json(history.model_dump_json())

    assert restored == history
    assert [type(m) for m in restored.content] == [
        UserMessage,
        AssistantMessage,
        ToolMessage,
        AssistantMessage,
    ]


def test_roles_match_the_values_the_api_expects() -> None:
    # role 的值写错（比如 "assitant"）pyright 和 Ruff 都查不出来，只能靠这个测试
    roles = [m.role for m in make_history().content]

    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.parametrize(
    ("message", "field"),
    [
        (UserMessage(content="你好"), "content"),
        (AssistantMessage(content="你好"), "content"),
        (ToolMessage(tool_call_id="call_1", content="ok"), "content"),
        (ToolCall(id="call_1", name="current_time", arguments="{}"), "name"),
    ],
    ids=["user", "assistant", "tool", "tool_call"],
)
def test_messages_cannot_be_modified_after_creation(message: BaseModel, field: str) -> None:
    with pytest.raises(ValidationError):
        setattr(message, field, "改一下")


@pytest.mark.parametrize(
    "item",
    [
        {"id": "call_1", "name": "current_time", "arguments": "{}"},
        {"role": "assitant", "content": "role 拼错了"},
    ],
    ids=["tool_call_is_not_a_message", "misspelled_role"],
)
def test_history_rejects_items_that_are_not_messages(item: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Messages.model_validate({"content": [item]})


def test_tool_message_requires_tool_call_id() -> None:
    with pytest.raises(ValidationError):
        ToolMessage.model_validate({"role": "tool", "content": "没有 tool_call_id"})


def test_assistant_message_may_have_no_text_when_calling_a_tool() -> None:
    call = ToolCall(id="call_1", name="current_time", arguments="{}")

    message = AssistantMessage(content=None, tool_calls=[call])

    assert message.content is None
    assert message.tool_calls == [call]


def test_assistant_message_has_no_tool_calls_by_default() -> None:
    first = AssistantMessage(content="你好")
    second = AssistantMessage(content="再见")

    assert first.tool_calls == []
    assert first.tool_calls is not second.tool_calls  # 每个对象各有一份列表，不共用


def test_tool_call_keeps_arguments_even_if_they_are_not_valid_json() -> None:
    # 参数是模型写出来的文字，可能被截断。创建消息时不解析，执行工具时才处理
    truncated = '{"timezone": "Asia/Shan'

    call = ToolCall(id="call_1", name="current_time", arguments=truncated)

    assert call.arguments == truncated


def test_history_can_be_appended_to() -> None:
    history = Messages()

    history.content.append(UserMessage(content="你好"))

    assert len(history.content) == 1
    assert Messages().content == []  # 新建的历史不共用同一个列表
