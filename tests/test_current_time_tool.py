from datetime import datetime, timedelta

from butler.tools.base import Tool
from butler.tools.current_time import CurrentTimeArgs, current_time, current_time_tool


def test_current_time_tool_is_a_tool() -> None:
    assert isinstance(current_time_tool, Tool)


def test_current_time_tool_is_called_current_time() -> None:
    # 模型靠这个名字来调用它，所以不能随便改
    assert current_time_tool.name == "current_time"


def test_current_time_tool_uses_the_args_class_and_the_function() -> None:
    assert current_time_tool.args_model is CurrentTimeArgs
    assert current_time_tool.handler is current_time


def test_current_time_tool_is_read_only() -> None:
    # 查时间不会改变任何东西。重启后恢复时，只允许只读工具继续运行（设计文档 01 §12）
    assert current_time_tool.read_only is True


def test_current_time_tool_has_a_description_for_the_model() -> None:
    assert len(current_time_tool.description.strip()) >= 8


async def test_current_time_tool_works_from_arguments_text_to_result() -> None:
    # 后面的 execute 做的就是这两步
    args = current_time_tool.args_model.model_validate_json('{"timezone": "UTC"}')

    result = await current_time_tool.handler(args)

    assert datetime.fromisoformat(result).utcoffset() == timedelta(0)


async def test_current_time_tool_uses_shanghai_when_no_timezone_is_given() -> None:
    args = current_time_tool.args_model.model_validate_json("{}")

    result = await current_time_tool.handler(args)

    assert datetime.fromisoformat(result).utcoffset() == timedelta(hours=8)
