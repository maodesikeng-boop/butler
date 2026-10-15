import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfoNotFoundError

import pytest

from butler.tools.current_time import CurrentTimeArgs, current_time


async def test_default_timezone_is_shanghai() -> None:
    result = await current_time(CurrentTimeArgs())

    assert datetime.fromisoformat(result).utcoffset() == timedelta(hours=8)


async def test_uses_the_timezone_given_in_the_arguments() -> None:
    result = await current_time(CurrentTimeArgs(timezone="UTC"))

    assert datetime.fromisoformat(result).utcoffset() == timedelta(0)


async def test_returns_the_current_time() -> None:
    before = datetime.now(UTC)

    result = datetime.fromisoformat(await current_time(CurrentTimeArgs()))

    assert before <= result <= datetime.now(UTC)


async def test_other_timezones_show_the_same_moment() -> None:
    shanghai = datetime.fromisoformat(await current_time(CurrentTimeArgs()))
    new_york = datetime.fromisoformat(
        await current_time(CurrentTimeArgs(timezone="America/New_York"))
    )

    assert abs(shanghai - new_york) < timedelta(seconds=5)
    assert shanghai.utcoffset() != new_york.utcoffset()


async def test_unknown_timezone_raises_an_error() -> None:
    # 不在这里处理：后面的 execute 会把任何错误变成结果交给模型
    with pytest.raises(ZoneInfoNotFoundError):
        await current_time(CurrentTimeArgs(timezone="Mars/Base"))


def test_timezone_parameter_tells_the_model_what_to_fill_in() -> None:
    timezone = CurrentTimeArgs.model_json_schema()["properties"]["timezone"]

    assert timezone["default"] == "Asia/Shanghai"
    assert timezone.get("description")  # 有一句给模型看的说明，不是空的


def test_timezone_description_gives_an_example_of_the_expected_format() -> None:
    # 函数只认标准时区名（Asia/Shanghai 这种）。说明里不给例子，模型会填"北京"、"UTC+8"，调用就失败
    timezone = CurrentTimeArgs.model_json_schema()["properties"]["timezone"]

    assert re.search(r"[A-Za-z]+/[A-Za-z_]+", timezone.get("description", ""))
