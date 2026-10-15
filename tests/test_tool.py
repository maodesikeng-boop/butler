from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from butler.tools.base import Tool
from butler.tools.current_time import CurrentTimeArgs, current_time


def tool_data() -> dict[str, Any]:
    return {
        "name": "current_time",
        "description": "查询当前时间",
        "args_model": CurrentTimeArgs,
        "handler": current_time,
    }


def test_tool_keeps_everything_it_was_given() -> None:
    tool = Tool(**tool_data())

    assert tool.name == "current_time"
    assert tool.description == "查询当前时间"
    assert tool.args_model is CurrentTimeArgs
    assert tool.handler is current_time


def test_tool_defaults_are_the_cautious_ones() -> None:
    tool = Tool(**tool_data())

    assert tool.read_only is False
    assert tool.parallel_safe is False
    assert tool.timeout_s == 60.0


def test_tool_options_can_be_changed() -> None:
    tool = Tool(**tool_data(), read_only=True, parallel_safe=True, timeout_s=5.0)

    assert tool.read_only is True
    assert tool.parallel_safe is True
    assert tool.timeout_s == 5.0


async def test_tool_can_parse_arguments_and_run_its_handler() -> None:
    # 后面的 execute 做的就是这两步：用工具的参数类解析模型写的文字，再运行工具的函数
    tool = Tool(**tool_data())

    args = tool.args_model.model_validate_json('{"timezone": "UTC"}')
    result = await tool.handler(args)

    assert datetime.fromisoformat(result).utcoffset() == timedelta(0)


def test_tool_cannot_be_modified_after_creation() -> None:
    tool = Tool(**tool_data())

    with pytest.raises(ValidationError):
        setattr(tool, "name", "改一下")  # noqa: B010


@pytest.mark.parametrize("missing", ["name", "description", "args_model", "handler"])
def test_tool_requires_name_description_args_model_and_handler(missing: str) -> None:
    data = tool_data()
    del data[missing]

    with pytest.raises(ValidationError):
        Tool.model_validate(data)


@pytest.mark.parametrize(
    "bad_args_model",
    ["CurrentTimeArgs", CurrentTimeArgs(), dict],
    ids=["a_string", "a_filled_form_not_the_template", "not_a_pydantic_class"],
)
def test_args_model_must_be_the_parameter_class_itself(bad_args_model: object) -> None:
    data = tool_data()
    data["args_model"] = bad_args_model

    with pytest.raises(ValidationError):
        Tool.model_validate(data)


def test_handler_must_be_a_function() -> None:
    data = tool_data()
    data["handler"] = "不是函数"

    with pytest.raises(ValidationError):
        Tool.model_validate(data)
