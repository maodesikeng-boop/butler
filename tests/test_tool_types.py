import pytest
from pydantic import ValidationError

from butler.tools.base import ToolResult, ToolSpec


@pytest.mark.parametrize("status", ["ok", "error", "timeout"])
def test_tool_result_accepts_the_three_statuses(status: str) -> None:
    result = ToolResult.model_validate({"call_id": "call_1", "content": "结果", "status": status})

    assert result.status == status


def test_tool_result_rejects_an_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"call_id": "call_1", "content": "结果", "status": "done"})


@pytest.mark.parametrize("missing", ["call_id", "content", "status"])
def test_tool_result_requires_every_field(missing: str) -> None:
    data = {"call_id": "call_1", "content": "结果", "status": "ok"}
    del data[missing]

    with pytest.raises(ValidationError):
        ToolResult.model_validate(data)


def test_tool_result_cannot_be_modified_after_creation() -> None:
    result = ToolResult(call_id="call_1", content="结果", status="ok")

    with pytest.raises(ValidationError):
        result.content = "改一下"


def test_tool_spec_holds_name_description_and_parameters() -> None:
    parameters = {"type": "object", "properties": {"timezone": {"type": "string"}}}

    spec = ToolSpec(name="current_time", description="查询当前时间", parameters=parameters)

    assert spec.name == "current_time"
    assert spec.description == "查询当前时间"
    assert spec.parameters == parameters


@pytest.mark.parametrize("missing", ["name", "description"])
def test_tool_spec_requires_name_and_description(missing: str) -> None:
    data = {"name": "current_time", "description": "查询当前时间", "parameters": {}}
    del data[missing]

    with pytest.raises(ValidationError):
        ToolSpec.model_validate(data)


def test_tool_spec_cannot_be_modified_after_creation() -> None:
    spec = ToolSpec(name="current_time", description="查询当前时间", parameters={})

    with pytest.raises(ValidationError):
        spec.name = "改一下"
