import asyncio

from pydantic import BaseModel

from butler.loop import run_turn
from butler.messages import AssistantMessage, Messages, ToolCall, ToolMessage, UserMessage
from butler.model.base import ModelReply
from butler.model.scripted import ScriptedModel
from butler.tools.base import Tool
from butler.tools.registry import ToolRegistry


class TextArgs(BaseModel):
    text: str


class NoArgs(BaseModel):
    pass


async def echo(args: TextArgs) -> str:
    return f"收到：{args.text}"


def echo_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(name="echo", description="原样返回收到的文字", args_model=TextArgs, handler=echo)
    )
    return registry


def say(text: str) -> ModelReply:
    return ModelReply(message=AssistantMessage(content=text))


def call_tools(*calls: ToolCall) -> ModelReply:
    return ModelReply(message=AssistantMessage(content=None, tool_calls=list(calls)))


def assert_each_tool_call_has_exactly_one_result(history: Messages) -> None:
    # 每个工具调用后面，按同样的顺序，恰好有一条对应的工具结果，不能多也不能少
    pending: list[str] = []
    for message in history.content:
        if isinstance(message, AssistantMessage):
            assert pending == []
            pending = [call.id for call in message.tool_calls]
        elif isinstance(message, ToolMessage):
            assert pending
            assert message.tool_call_id == pending.pop(0)
        else:
            assert pending == []
    assert pending == []


async def run(
    model: ScriptedModel,
    registry: ToolRegistry,
    user_text: str,
    history: Messages | None = None,
    system: str = "你是管家",
) -> tuple[AssistantMessage, Messages]:
    if history is None:
        history = Messages()
    result = await run_turn(history, model, registry, UserMessage(content=user_text), system)
    assert isinstance(result, AssistantMessage)
    assert result == history.content[-1]
    assert_each_tool_call_has_exactly_one_result(history)
    return result, history


async def test_without_tool_calls_the_model_is_asked_once() -> None:
    registry = echo_registry()
    model = ScriptedModel([say("好的")])

    result, history = await run(model, registry, "你好")

    assert len(model.requests) == 1
    assert result.content == "好的"
    assert result.tool_calls == []
    assert model.requests[0].system == "你是管家"
    assert model.requests[0].messages == [UserMessage(content="你好")]
    assert model.requests[0].tools == registry.specs()
    assert history.content == [
        UserMessage(content="你好"),
        AssistantMessage(content="好的"),
    ]


async def test_one_tool_call_then_the_final_answer() -> None:
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')
    model = ScriptedModel([call_tools(call), say("现在是三点")])

    result, history = await run(model, echo_registry(), "几点了")

    assert len(model.requests) == 2
    assert result.content == "现在是三点"
    assert result.tool_calls == []
    assert history.content == [
        UserMessage(content="几点了"),
        AssistantMessage(content=None, tool_calls=[call]),
        ToolMessage(tool_call_id="call_1", content="收到：你好"),
        AssistantMessage(content="现在是三点"),
    ]


async def test_the_request_after_a_tool_call_includes_the_tool_result() -> None:
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')
    model = ScriptedModel([call_tools(call), say("现在是三点")])

    await run(model, echo_registry(), "几点了")

    assert model.requests[1].system == "你是管家"
    assert model.requests[1].messages == [
        UserMessage(content="几点了"),
        AssistantMessage(content=None, tool_calls=[call]),
        ToolMessage(tool_call_id="call_1", content="收到：你好"),
    ]


async def test_two_tool_calls_in_one_reply_run_in_call_order() -> None:
    # 名字按字母 apple 在前，但这一次先调用 mango。
    # 用来确认执行顺序跟着调用，而不是跟着工具清单的排序。
    order: list[str] = []

    async def mango(args: NoArgs) -> str:
        order.append("mango-start")
        await asyncio.sleep(0)
        order.append("mango-end")
        return "芒果"

    async def apple(args: NoArgs) -> str:
        order.append("apple")
        return "苹果"

    registry = ToolRegistry()
    registry.register(Tool(name="mango", description="先调用", args_model=NoArgs, handler=mango))
    registry.register(Tool(name="apple", description="后调用", args_model=NoArgs, handler=apple))
    mango_call = ToolCall(id="call_mango", name="mango", arguments="{}")
    apple_call = ToolCall(id="call_apple", name="apple", arguments="{}")
    model = ScriptedModel([call_tools(mango_call, apple_call), say("两个都好了")])

    result, history = await run(model, registry, "都查一下")

    assert order == ["mango-start", "mango-end", "apple"]
    assert result.content == "两个都好了"
    assert history.content == [
        UserMessage(content="都查一下"),
        AssistantMessage(content=None, tool_calls=[mango_call, apple_call]),
        ToolMessage(tool_call_id="call_mango", content="芒果"),
        ToolMessage(tool_call_id="call_apple", content="苹果"),
        AssistantMessage(content="两个都好了"),
    ]
    assert model.requests[1].messages == history.content[:4]


async def test_an_unknown_tool_writes_an_error_and_the_model_sees_it() -> None:
    call = ToolCall(id="call_x", name="missing", arguments="{}")
    model = ScriptedModel([call_tools(call), say("这个工具没有")])

    result, history = await run(model, ToolRegistry(), "用一个没有的工具")

    error = ToolMessage(tool_call_id="call_x", content="Tool missing not found")
    assert len(model.requests) == 2
    assert result.content == "这个工具没有"
    assert history.content == [
        UserMessage(content="用一个没有的工具"),
        AssistantMessage(content=None, tool_calls=[call]),
        error,
        AssistantMessage(content="这个工具没有"),
    ]
    assert model.requests[1].messages[-1] == error


async def test_a_second_turn_sends_the_whole_history() -> None:
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')
    model = ScriptedModel([call_tools(call), say("三点"), say("不客气")])
    registry = echo_registry()
    history = Messages()

    await run(model, registry, "几点了", history)
    result, history = await run(model, registry, "谢谢", history)

    first_turn = [
        UserMessage(content="几点了"),
        AssistantMessage(content=None, tool_calls=[call]),
        ToolMessage(tool_call_id="call_1", content="收到：你好"),
        AssistantMessage(content="三点"),
    ]
    assert result.content == "不客气"
    assert model.requests[2].messages == first_turn + [UserMessage(content="谢谢")]
    assert history.content == first_turn + [
        UserMessage(content="谢谢"),
        AssistantMessage(content="不客气"),
    ]
