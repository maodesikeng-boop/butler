import pytest

from butler.tools.base import Tool, ToolSpec
from butler.tools.current_time import CurrentTimeArgs, current_time, current_time_tool
from butler.tools.registry import ToolRegistry


def make_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"测试用的工具 {name}",
        args_model=CurrentTimeArgs,
        handler=current_time,
    )


def test_a_new_registry_has_no_tools() -> None:
    registry = ToolRegistry()

    assert registry.get("current_time") is None


def test_a_registered_tool_can_be_found_by_its_name() -> None:
    registry = ToolRegistry()

    registry.register(current_time_tool)

    assert registry.get("current_time") is current_time_tool


def test_each_tool_is_found_under_its_own_name() -> None:
    registry = ToolRegistry()
    first = make_tool("first")
    second = make_tool("second")

    registry.register(first)
    registry.register(second)

    assert registry.get("first") is first
    assert registry.get("second") is second


def test_an_unknown_name_gives_none_instead_of_an_error() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    assert registry.get("no_such_tool") is None


def test_the_name_must_match_exactly() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    assert registry.get("Current_Time") is None
    assert registry.get("current_time ") is None


def test_every_registry_has_its_own_list_of_tools() -> None:
    first = ToolRegistry()
    second = ToolRegistry()

    first.register(current_time_tool)

    assert second.get("current_time") is None


def test_registering_the_same_name_twice_is_an_error() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("clock"))

    with pytest.raises(ValueError):
        registry.register(make_tool("clock"))


def test_the_error_message_names_the_duplicate() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    with pytest.raises(ValueError, match="current_time"):
        registry.register(make_tool("current_time"))


def test_a_duplicate_does_not_replace_the_first_tool() -> None:
    registry = ToolRegistry()
    first = make_tool("clock")
    registry.register(first)

    with pytest.raises(ValueError):
        registry.register(make_tool("clock"))

    assert registry.get("clock") is first


def test_registering_the_very_same_tool_twice_is_also_an_error() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    with pytest.raises(ValueError):
        registry.register(current_time_tool)


def test_the_registry_still_works_after_a_duplicate_error() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("clock"))
    with pytest.raises(ValueError):
        registry.register(make_tool("clock"))

    other = make_tool("other")
    registry.register(other)

    assert registry.get("other") is other


def test_specs_of_an_empty_registry_is_an_empty_list() -> None:
    assert ToolRegistry().specs() == []


def test_specs_is_a_list_of_tool_specs() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    specs = registry.specs()

    assert isinstance(specs, list)
    assert all(isinstance(spec, ToolSpec) for spec in specs)


def test_a_spec_carries_the_name_description_and_parameter_schema_of_its_tool() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    specs = registry.specs()

    assert len(specs) == 1
    assert specs[0].name == current_time_tool.name
    assert specs[0].description == current_time_tool.description
    assert specs[0].parameters == CurrentTimeArgs.model_json_schema()


def test_the_parameters_are_the_schema_itself_not_the_function_that_makes_it() -> None:
    # 函数名后面不加括号，传进去的是"生成说明的函数"，而不是说明本身
    registry = ToolRegistry()
    registry.register(current_time_tool)

    parameters = registry.specs()[0].parameters

    assert isinstance(parameters, dict)
    assert "timezone" in parameters["properties"]


def test_every_registered_tool_gets_its_own_spec() -> None:
    registry = ToolRegistry()
    for name in ("first", "second", "third"):
        registry.register(make_tool(name))

    specs = registry.specs()

    assert len(specs) == 3
    assert sorted(spec.name for spec in specs) == ["first", "second", "third"]


def test_each_spec_belongs_to_its_own_tool_and_is_not_mixed_up_with_another() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("first"))
    registry.register(make_tool("second"))

    descriptions = {spec.name: spec.description for spec in registry.specs()}

    assert descriptions == {"first": "测试用的工具 first", "second": "测试用的工具 second"}


def test_a_spec_does_not_carry_the_function_that_does_the_work() -> None:
    # 给模型看的"菜单"里只有说明，没有真正干活的函数
    registry = ToolRegistry()
    registry.register(current_time_tool)

    spec = registry.specs()[0]

    assert not hasattr(spec, "handler")
    assert not hasattr(spec, "args_model")


def test_specs_gives_the_same_answer_every_time_it_is_called() -> None:
    registry = ToolRegistry()
    registry.register(current_time_tool)

    assert registry.specs() == registry.specs()


def test_a_tool_registered_later_shows_up_in_the_next_specs() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("first"))
    assert [spec.name for spec in registry.specs()] == ["first"]

    registry.register(make_tool("second"))

    assert sorted(spec.name for spec in registry.specs()) == ["first", "second"]


def test_calling_specs_does_not_change_the_registry() -> None:
    registry = ToolRegistry()
    tool = make_tool("first")
    registry.register(tool)

    registry.specs()

    assert registry.get("first") is tool


def spec_names(registry: ToolRegistry) -> list[str]:
    return [spec.name for spec in registry.specs()]


def test_specs_are_sorted_by_name() -> None:
    registry = ToolRegistry()
    for name in ("charlie", "alpha", "bravo"):
        registry.register(make_tool(name))

    assert spec_names(registry) == ["alpha", "bravo", "charlie"]


def test_specs_are_sorted_when_the_tools_were_registered_in_reverse_order() -> None:
    registry = ToolRegistry()
    for name in ("delta", "charlie", "bravo", "alpha"):
        registry.register(make_tool(name))

    assert spec_names(registry) == ["alpha", "bravo", "charlie", "delta"]


def test_the_order_does_not_depend_on_the_order_of_registration() -> None:
    # 工具清单每次请求都必须一模一样，模型服务才能复用缓存（设计文档 01 §4.4）
    forward = ToolRegistry()
    backward = ToolRegistry()
    for name in ("alpha", "bravo", "charlie"):
        forward.register(make_tool(name))
    for name in ("charlie", "bravo", "alpha"):
        backward.register(make_tool(name))

    assert forward.specs() == backward.specs()


def test_specs_are_sorted_by_name_not_by_description() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(name="a_tool", description="zzz", args_model=CurrentTimeArgs, handler=current_time)
    )
    registry.register(
        Tool(name="b_tool", description="aaa", args_model=CurrentTimeArgs, handler=current_time)
    )

    assert spec_names(registry) == ["a_tool", "b_tool"]


def test_sorting_keeps_each_spec_together_with_its_own_description() -> None:
    registry = ToolRegistry()
    for name in ("charlie", "alpha", "bravo"):
        registry.register(make_tool(name))

    assert [(spec.name, spec.description) for spec in registry.specs()] == [
        ("alpha", "测试用的工具 alpha"),
        ("bravo", "测试用的工具 bravo"),
        ("charlie", "测试用的工具 charlie"),
    ]


def test_a_tool_registered_after_a_call_is_put_in_its_sorted_place() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha"))
    registry.register(make_tool("charlie"))
    assert spec_names(registry) == ["alpha", "charlie"]

    registry.register(make_tool("bravo"))

    assert spec_names(registry) == ["alpha", "bravo", "charlie"]
