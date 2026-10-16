.PHONY: check fmt test

# 提交前跑一遍；CI 跑的也是这个
# Ruff 不用缓存：整理 import 要看某个模块存不存在，而缓存不知道它后来才建好，
# 会让本地通过、CI 却失败（S1-2 遇到过）
check:
	uv run ruff check --no-cache
	uv run ruff format --check --no-cache
	uv run pyright
	uv run pytest

# 格式化代码并排好 import
fmt:
	uv run ruff check --no-cache --select I --fix
	uv run ruff format --no-cache

test:
	uv run pytest
