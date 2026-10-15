from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from butler.tools.base import Tool


class CurrentTimeArgs(BaseModel):
    timezone: str = Field(
        default="Asia/Shanghai", description="用户所在的时区，标准时区名，比如 Asia/Shanghai, UTC"
    )


async def current_time(args: CurrentTimeArgs) -> str:
    return datetime.now(ZoneInfo(args.timezone)).isoformat()


current_time_tool = Tool(
    name="current_time",
    description="查询用户所在时区的当前时间，需要用户当前时间时使用",
    args_model=CurrentTimeArgs,
    handler=current_time,
    parallel_safe=False,
    read_only=True,
    timeout_s=30.0,
)
