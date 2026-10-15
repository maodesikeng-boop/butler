import pytest
from pydantic import ValidationError

from butler.messages import AssistantMessage, ToolCall, UserMessage
from butler.model.base import ModelClient, ModelReply, Usage
from butler.model.scripted import ModelRequest, ScriptedModel
from butler.tools.base import ToolSpec


def reply(text: str) -> ModelReply:
    return ModelReply(message=AssistantMessage(content=text))


def clock_spec() -> ToolSpec:
    return ToolSpec(name="current_time", description="查询当前时间", parameters={})


def as_client(model: ScriptedModel) -> ModelClient:
    # 这一行由 pyright 检查：ScriptedModel 必须符合 ModelClient 的约定
    return model


async def ask(model: ScriptedModel, text: str = "你好") -> ModelReply:
    return await model.complete(system="提示词", messages=[UserMessage(content=text)], tools=[])


async def test_the_scripted_model_can_be_used_as_a_model_client() -> None:
    client = as_client(ScriptedModel([reply("好的")]))

    result = await client.complete(
        system="提示词", messages=[UserMessage(content="你好")], tools=[]
    )

    assert result.message.content == "好的"


async def test_replies_come_back_in_the_order_of_the_script() -> None:
    first, second, third = reply("一"), reply("二"), reply("三")
    model = ScriptedModel([first, second, third])

    assert await ask(model) is first
    assert await ask(model) is second
    assert await ask(model) is third


async def test_a_reply_with_tool_calls_and_usage_is_handed_back_unchanged() -> None:
    call = ToolCall(id="call_1", name="current_time", arguments="{}")
    usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    wanted = ModelReply(message=AssistantMessage(content=None, tool_calls=[call]), usage=usage)

    result = await ask(ScriptedModel([wanted]))

    assert result is wanted


async def test_the_script_can_be_a_tuple() -> None:
    model = ScriptedModel((reply("一"), reply("二")))

    assert (await ask(model)).message.content == "一"
    assert (await ask(model)).message.content == "二"


def test_nothing_is_recorded_before_the_first_call() -> None:
    assert ScriptedModel([reply("好的")]).requests == []


async def test_a_call_records_the_system_prompt_the_messages_and_the_tools() -> None:
    model = ScriptedModel([reply("好的")])
    spec = clock_spec()

    await model.complete(system="你是助手", messages=[UserMessage(content="几点了")], tools=[spec])

    assert len(model.requests) == 1
    request = model.requests[0]
    assert isinstance(request, ModelRequest)
    assert request.system == "你是助手"
    assert request.messages == [UserMessage(content="几点了")]
    assert request.tools == [spec]


async def test_every_call_is_recorded_in_the_order_it_was_made() -> None:
    model = ScriptedModel([reply("一"), reply("二"), reply("三")])

    await ask(model, "第一问")
    await ask(model, "第二问")
    await ask(model, "第三问")

    assert [r.messages[0].content for r in model.requests] == ["第一问", "第二问", "第三问"]


async def test_changing_the_callers_message_list_afterwards_does_not_change_the_record() -> None:
    model = ScriptedModel([reply("好的")])
    history = [UserMessage(content="你好")]

    await model.complete(system="提示词", messages=history, tools=[])
    history.append(UserMessage(content="之后才加的"))

    assert model.requests[0].messages == [UserMessage(content="你好")]


async def test_changing_the_callers_tool_list_afterwards_does_not_change_the_record() -> None:
    model = ScriptedModel([reply("好的")])
    specs = [clock_spec()]

    await model.complete(system="提示词", messages=[UserMessage(content="你好")], tools=specs)
    specs.clear()

    assert model.requests[0].tools == [clock_spec()]


async def test_a_growing_history_gives_each_request_its_own_snapshot() -> None:
    # 循环每一步都往同一个历史列表里追加，每次请求记录下的必须是"当时"的样子
    model = ScriptedModel([reply("一"), reply("二")])
    history = [UserMessage(content="第一句")]

    await model.complete(system="提示词", messages=history, tools=[])
    history.append(UserMessage(content="第二句"))
    await model.complete(system="提示词", messages=history, tools=[])

    assert len(model.requests[0].messages) == 1
    assert len(model.requests[1].messages) == 2


async def test_a_recorded_request_cannot_be_modified() -> None:
    model = ScriptedModel([reply("好的")])
    await ask(model)

    with pytest.raises(ValidationError):
        model.requests[0].system = "改一下"


async def test_asking_more_often_than_the_script_has_replies_is_an_error() -> None:
    model = ScriptedModel([reply("一"), reply("二")])
    await ask(model)
    await ask(model)

    with pytest.raises(RuntimeError):
        await ask(model)


async def test_the_error_says_which_call_ran_out_of_script() -> None:
    model = ScriptedModel([reply("一"), reply("二")])
    await ask(model)
    await ask(model)

    with pytest.raises(RuntimeError) as error:
        await ask(model)

    assert "3" in str(error.value)


async def test_an_empty_script_fails_on_the_first_call() -> None:
    with pytest.raises(RuntimeError) as error:
        await ask(ScriptedModel([]))

    assert "1" in str(error.value)


async def test_the_call_that_ran_out_of_script_is_recorded_too() -> None:
    model = ScriptedModel([reply("一")])
    await ask(model)

    with pytest.raises(RuntimeError):
        await ask(model, "多问的一句")

    assert len(model.requests) == 2
    assert model.requests[1].messages == [UserMessage(content="多问的一句")]


async def test_it_keeps_failing_after_the_script_has_run_out() -> None:
    model = ScriptedModel([reply("一")])
    await ask(model)

    for expected_call in ("2", "3"):
        with pytest.raises(RuntimeError) as error:
            await ask(model)
        assert expected_call in str(error.value)


async def test_changing_the_original_script_list_afterwards_does_not_change_the_model() -> None:
    first, second = reply("一"), reply("二")
    script = [first]
    model = ScriptedModel(script)

    script.append(second)

    assert await ask(model) is first
    with pytest.raises(RuntimeError):
        await ask(model)


async def test_the_model_does_not_use_up_the_callers_script_list() -> None:
    script = [reply("一"), reply("二")]
    model = ScriptedModel(script)

    await ask(model)
    await ask(model)

    assert len(script) == 2


async def test_two_scripted_models_do_not_share_anything() -> None:
    first = ScriptedModel([reply("甲")])
    second = ScriptedModel([reply("乙")])

    await ask(first)

    assert len(first.requests) == 1
    assert second.requests == []
    assert (await ask(second)).message.content == "乙"
