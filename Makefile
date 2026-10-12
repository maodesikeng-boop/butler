.PHONY: check fmt test

# 提交前跑一遍；CI 跑的也是这个
check:
	uv run ruff check
	uv run ruff format --check
	uv run pyright
	uv run pytest

# 格式化代码并排好 import
fmt:
	uv run ruff check --select I --fix
	uv run ruff format

test:
	uv run pytest
