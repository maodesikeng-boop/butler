# butler

自托管的个人 AI 助手：只给自己用，部署在自己的服务器上，以微信为入口。它能读邮件，记住你的资料和习惯，调用命令行工具和 MCP，也能主动给你发消息。

核心是一个 agent 循环。邮箱等能力都以插件的形式接入。

> 状态：开发中，当前在做 [Sprint 1：基础 agent 循环](docs/sprints/sprint-1.md)

## 本地开发

需要先安装 [uv](https://docs.astral.sh/uv/)。Python 版本写在 `.python-version` 里，uv 会自动安装。

| 命令 | 作用 |
|---|---|
| `uv sync` | 安装依赖（第一次运行时，或者依赖有变化后） |
| `make check` | 提交前运行：lint、格式检查、类型检查、测试。CI 跑的也是这个 |
| `make fmt` | 格式化代码，排好 import |
| `make test` | 只跑测试 |
| `uv run butler` | 运行程序 |

## 目录结构

Sprint 1 结束时的样子：

| 位置 | 放什么 |
|---|---|
| `src/butler/messages.py` | 消息类型：用户消息、助手消息、工具调用、工具结果 |
| `src/butler/tools/` | 工具的定义、注册和执行，以及内置工具 |
| `src/butler/model/` | 模型接口，以及各家模型的适配 |
| `src/butler/loop.py` | agent 循环 |
| `src/butler/config.py` | 配置，从环境变量和 `.env` 读取 |
| `src/butler/cli.py` | 终端入口 |
| `tests/` | 测试，文件名用 `test_*.py` |
| `docs/design/` | 设计文档 |
| `docs/adr/` | 技术决策记录 |
| `docs/sprints/` | Sprint 计划 |

约定：

- 核心代码（循环、消息、工具）不依赖任何一家模型的 SDK。和具体模型打交道的代码只放在 `model/` 里。
- 配置和密钥一律通过环境变量传入，仓库里只放 `.env.example`。

## 文档

- [设计文档 01：Agent 循环](docs/design/01-agent-loop.md)
- [ADR-0001：技术栈选型](docs/adr/0001-tech-stack.md)
