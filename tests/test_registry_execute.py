import asyncio
import time
from datetime import datetime, timedelta

import pytest
from pydantic import BaseModel

from butler.messages import ToolCall
from butler.tools.base import Tool, ToolResult
from butler.tools.current_time import current_time_tool
from butler.tools.registry import ToolRegistry


class EchoArgs(BaseModel):
    text: str


async def echo(args: EchoArgs) -> str:
    return f"收到：{args.text}"


class AddArgs(BaseModel):
    a: int
    b: int


async def add(args: AddArgs) -> str:
    return str(args.a + args.b)


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(name="echo", description="原样返回收到的文字", args_model=EchoArgs, handler=echo)
    )
    registry.register(
        Tool(name="add", description="把两个整数相加", args_model=AddArgs, handler=add)
    )
    return registry


async def test_execute_runs_the_tool_and_returns_its_output() -> None:
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')

    result = await make_registry().execute(call)

    assert result.status == "ok"
    assert result.content == "收到：你好"


async def test_execute_returns_a_tool_result() -> None:
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')

    result = await make_registry().execute(call)

    assert isinstance(result, ToolResult)


async def test_the_result_carries_the_id_of_the_call() -> None:
    # 模型一次可能发起好几个调用，结果要靠这个编号对上
    call = ToolCall(id="call_42", name="echo", arguments='{"text": "你好"}')

    result = await make_registry().execute(call)

    assert result.call_id == "call_42"


async def test_execute_runs_the_tool_named_in_the_call() -> None:
    registry = make_registry()

    echoed = await registry.execute(ToolCall(id="c1", name="echo", arguments='{"text": "hi"}'))
    added = await registry.execute(ToolCall(id="c2", name="add", arguments='{"a": 2, "b": 3}'))

    assert echoed.content == "收到：hi"
    assert added.content == "5"


async def test_arguments_are_converted_to_the_types_the_tool_asks_for() -> None:
    # 模型有时会把数字写成文字 "5"
    call = ToolCall(id="call_1", name="add", arguments='{"a": "5", "b": 3}')

    result = await make_registry().execute(call)

    assert result.status == "ok"
    assert result.content == "8"


async def test_default_values_of_the_arguments_are_used() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    result = await registry.execute(ToolCall(id="call_1", name="current_time", arguments="{}"))

    assert result.status == "ok"
    assert datetime.fromisoformat(result.content).utcoffset() == timedelta(hours=8)


async def test_the_same_call_can_be_executed_twice() -> None:
    registry = make_registry()
    call = ToolCall(id="call_1", name="echo", arguments='{"text": "你好"}')

    assert await registry.execute(call) == await registry.execute(call)


async def test_an_unknown_tool_gives_an_error_result_instead_of_an_exception() -> None:
    call = ToolCall(id="call_9", name="no_such_tool", arguments="{}")

    result = await make_registry().execute(call)

    assert result.status == "error"
    assert result.content == "Tool no_such_tool not found"
    assert result.call_id == "call_9"


async def test_an_unknown_tool_is_reported_even_when_the_registry_is_empty() -> None:
    result = await ToolRegistry().execute(ToolCall(id="call_1", name="echo", arguments="{}"))

    assert result.status == "error"
    assert result.content == "Tool echo not found"


async def test_the_tool_name_must_match_exactly() -> None:
    result = await make_registry().execute(
        ToolCall(id="call_1", name="Echo", arguments='{"text": "你好"}')
    )

    assert result.status == "error"
    assert result.content == "Tool Echo not found"


async def test_an_unknown_tool_is_reported_before_its_arguments_are_looked_at() -> None:
    # 工具都不存在，参数写成什么样都不重要
    call = ToolCall(id="call_1", name="no_such_tool", arguments="{这不是合法的 JSON")

    result = await make_registry().execute(call)

    assert result.content == "Tool no_such_tool not found"


BAD_ARGUMENTS = [
    pytest.param("", id="empty"),
    pytest.param("{这不是合法的 JSON", id="broken_json"),
    pytest.param("[1, 2]", id="a_list_not_an_object"),
    pytest.param("null", id="null"),
    pytest.param('{"text": 5}', id="wrong_type"),
    pytest.param("{}", id="missing_field"),
]


@pytest.mark.parametrize("arguments", BAD_ARGUMENTS)
async def test_bad_arguments_give_an_error_result_instead_of_an_exception(arguments: str) -> None:
    call = ToolCall(id="call_7", name="echo", arguments=arguments)

    result = await make_registry().execute(call)

    assert result.status == "error"
    assert result.call_id == "call_7"


@pytest.mark.parametrize("arguments", BAD_ARGUMENTS)
async def test_the_error_result_repeats_the_arguments_that_were_received(arguments: str) -> None:
    # 模型看到自己写了什么，才知道哪里写错了
    call = ToolCall(id="call_1", name="echo", arguments=arguments)

    result = await make_registry().execute(call)

    assert arguments in result.content
    assert len(result.content) > len(arguments)


async def test_the_error_result_says_which_field_is_missing() -> None:
    call = ToolCall(id="call_1", name="echo", arguments="{}")

    result = await make_registry().execute(call)

    assert "text" in result.content


async def test_the_error_result_says_what_is_wrong_with_a_value() -> None:
    call = ToolCall(id="call_1", name="add", arguments='{"a": "abc", "b": 3}')

    result = await make_registry().execute(call)

    assert "integer" in result.content.lower()


async def test_the_tool_is_not_run_when_the_arguments_are_bad() -> None:
    calls: list[EchoArgs] = []

    async def spy(args: EchoArgs) -> str:
        calls.append(args)
        return "ran"

    registry = ToolRegistry()
    registry.register(
        Tool(name="spy", description="记录有没有被运行", args_model=EchoArgs, handler=spy)
    )

    result = await registry.execute(ToolCall(id="call_1", name="spy", arguments='{"wrong": 1}'))

    assert result.status == "error"
    assert calls == []


async def test_the_registry_still_works_after_a_call_with_bad_arguments() -> None:
    registry = make_registry()
    await registry.execute(ToolCall(id="call_1", name="echo", arguments="{坏的"))

    result = await registry.execute(ToolCall(id="call_2", name="echo", arguments='{"text": "好"}'))

    assert result.status == "ok"
    assert result.content == "收到：好"


def registry_with_failing_tool(error: BaseException) -> ToolRegistry:
    async def failing(args: EchoArgs) -> str:
        raise error

    registry = make_registry()
    registry.register(
        Tool(name="failing", description="总是出错的工具", args_model=EchoArgs, handler=failing)
    )
    return registry


FAILURES = [
    pytest.param(ValueError("值不对"), "值不对", id="ValueError"),
    pytest.param(KeyError("没有这个键"), "没有这个键", id="KeyError"),
    pytest.param(RuntimeError("出事了"), "出事了", id="RuntimeError"),
    pytest.param(ZeroDivisionError("division by zero"), "division by zero", id="ZeroDivisionError"),
]


@pytest.mark.parametrize(("error", "message"), FAILURES)
async def test_a_tool_that_raises_gives_an_error_result_instead_of_an_exception(
    error: Exception, message: str
) -> None:
    call = ToolCall(id="call_5", name="failing", arguments='{"text": "你好"}')

    result = await registry_with_failing_tool(error).execute(call)

    assert result.status == "error"
    assert result.call_id == "call_5"


@pytest.mark.parametrize(("error", "message"), FAILURES)
async def test_the_error_result_names_the_kind_of_error_and_its_message(
    error: Exception, message: str
) -> None:
    call = ToolCall(id="call_1", name="failing", arguments='{"text": "你好"}')

    result = await registry_with_failing_tool(error).execute(call)

    assert type(error).__name__ in result.content
    assert message in result.content


async def test_the_kind_of_error_is_named_even_when_it_has_no_message() -> None:
    call = ToolCall(id="call_1", name="failing", arguments='{"text": "你好"}')

    result = await registry_with_failing_tool(RuntimeError()).execute(call)

    assert "RuntimeError" in result.content


async def test_a_real_tool_failing_is_reported_to_the_model() -> None:
    # 时区名写错了：current_time 会抛 ZoneInfoNotFoundError，模型要能看到这个错误
    registry = ToolRegistry()
    registry.register(current_time_tool)
    call = ToolCall(id="call_1", name="current_time", arguments='{"timezone": "Mars/Base"}')

    result = await registry.execute(call)

    assert result.status == "error"
    assert "ZoneInfoNotFoundError" in result.content
    assert "Mars/Base" in result.content


async def test_a_failing_tool_is_run_only_once() -> None:
    calls: list[str] = []

    async def failing(args: EchoArgs) -> str:
        calls.append(args.text)
        raise RuntimeError("出事了")

    registry = ToolRegistry()
    registry.register(
        Tool(name="failing", description="总是出错的工具", args_model=EchoArgs, handler=failing)
    )

    await registry.execute(ToolCall(id="call_1", name="failing", arguments='{"text": "你好"}'))

    assert calls == ["你好"]


async def test_the_registry_still_works_after_a_tool_failed() -> None:
    registry = registry_with_failing_tool(RuntimeError("出事了"))
    await registry.execute(ToolCall(id="call_1", name="failing", arguments='{"text": "你好"}'))

    result = await registry.execute(ToolCall(id="call_2", name="echo", arguments='{"text": "好"}'))

    assert result.status == "ok"
    assert result.content == "收到：好"


async def test_cancelling_the_task_is_not_swallowed() -> None:
    # 以后用户发 /stop 要取消正在运行的任务，取消信号不能被当成"工具出错"吞掉
    call = ToolCall(id="call_1", name="failing", arguments='{"text": "你好"}')

    with pytest.raises(asyncio.CancelledError):
        await registry_with_failing_tool(asyncio.CancelledError()).execute(call)


def registry_with_sleepy_tool(sleep_s: float, timeout_s: float) -> ToolRegistry:
    async def sleepy(args: EchoArgs) -> str:
        await asyncio.sleep(sleep_s)
        return f"睡醒了：{args.text}"

    registry = make_registry()
    registry.register(
        Tool(
            name="sleepy",
            description="睡一会儿再回答",
            args_model=EchoArgs,
            handler=sleepy,
            timeout_s=timeout_s,
        )
    )
    return registry


SLEEPY_CALL = ToolCall(id="call_8", name="sleepy", arguments='{"text": "你好"}')


async def test_a_tool_that_takes_too_long_gives_a_timeout_result() -> None:
    result = await registry_with_sleepy_tool(sleep_s=1.0, timeout_s=0.05).execute(SLEEPY_CALL)

    assert result.status == "timeout"
    assert result.call_id == "call_8"


async def test_the_timeout_result_says_which_tool_and_how_many_seconds() -> None:
    result = await registry_with_sleepy_tool(sleep_s=1.0, timeout_s=0.05).execute(SLEEPY_CALL)

    assert result.content == "Tool sleepy timed out after 0.05s"


async def test_execute_gives_up_waiting_when_the_time_is_up() -> None:
    start = time.monotonic()

    await registry_with_sleepy_tool(sleep_s=1.0, timeout_s=0.05).execute(SLEEPY_CALL)

    assert time.monotonic() - start < 0.5


async def test_a_tool_that_finishes_in_time_is_not_affected() -> None:
    result = await registry_with_sleepy_tool(sleep_s=0.01, timeout_s=1.0).execute(SLEEPY_CALL)

    assert result.status == "ok"
    assert result.content == "睡醒了：你好"


async def test_each_tool_has_its_own_time_limit() -> None:
    # 同样睡 0.2 秒：限时 0.05 秒的超时，限时 1 秒的没事
    short = registry_with_sleepy_tool(sleep_s=0.2, timeout_s=0.05)
    long = registry_with_sleepy_tool(sleep_s=0.2, timeout_s=1.0)

    assert (await short.execute(SLEEPY_CALL)).status == "timeout"
    assert (await long.execute(SLEEPY_CALL)).status == "ok"


async def test_a_tool_that_timed_out_is_stopped_and_does_not_keep_running() -> None:
    finished: list[str] = []

    async def slow(args: EchoArgs) -> str:
        await asyncio.sleep(0.2)
        finished.append("done")
        return "done"

    registry = ToolRegistry()
    registry.register(
        Tool(name="slow", description="很慢", args_model=EchoArgs, handler=slow, timeout_s=0.05)
    )

    result = await registry.execute(ToolCall(id="call_1", name="slow", arguments='{"text": "x"}'))
    await asyncio.sleep(0.4)

    assert result.status == "timeout"
    assert finished == []


async def test_the_registry_still_works_after_a_timeout() -> None:
    registry = registry_with_sleepy_tool(sleep_s=1.0, timeout_s=0.05)
    await registry.execute(SLEEPY_CALL)

    result = await registry.execute(ToolCall(id="call_2", name="echo", arguments='{"text": "好"}'))

    assert result.status == "ok"
    assert result.content == "收到：好"


async def test_a_timeout_is_reported_as_timeout_and_not_as_an_error() -> None:
    result = await registry_with_sleepy_tool(sleep_s=1.0, timeout_s=0.05).execute(SLEEPY_CALL)

    assert result.status == "timeout"
    assert "TimeoutError" not in result.content
