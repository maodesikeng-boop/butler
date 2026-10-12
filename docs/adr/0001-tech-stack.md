# ADR-0001：技术栈选型

| 项目 | 内容 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-10-12 |
| 作者 | Claude（技术负责人） |
| 评审 | maodesikeng-boop |

## 背景

butler 是一个只给自己用的个人 AI 助手，部署在一台香港或海外的服务器上（要访问 Gmail）。它的核心是 agent 循环（见[设计文档 01](../design/01-agent-loop.md)），邮箱、微信、命令行工具、MCP 都以插件的形式接在循环外面。

约束：

- 一个人开发和维护，组件越少越好。
- 首要目标是学习：agent 循环要自己实现，不能让框架包办。
- 国内模型（DeepSeek、通义千问）都兼容 OpenAI 的 chat-completions 接口，这是各家共同支持的格式。
- 单用户、单进程，部署和运维要尽量简单。
- 循环里有大量并发等待（模型、工具、微信、审批），需要成熟的异步支持。

## 决策

| 方面 | 选择 |
|---|---|
| 语言 | Python 3.13，用 asyncio 处理并发 |
| 依赖和环境管理 | uv |
| 数据结构与校验 | Pydantic v2：消息类型、工具参数（自动生成交给模型的 JSON Schema），配置用 pydantic-settings |
| agent 框架 | 不用框架，按设计文档 01 自己实现 |
| 调用模型 | 官方 `openai` SDK 的 chat-completions 接口，通过 `base_url` 接入 DeepSeek、通义等兼容服务。核心代码只依赖自己定义的 `ModelClient` 接口 |
| 存储 | SQLite（从 Sprint 2 开始用） |
| 测试 | pytest + pytest-asyncio。用按剧本回复的假模型，测试不联网、不花钱 |
| 代码质量 | Ruff 做 lint 和格式化，pyright 做类型检查（standard 模式） |
| CI | GitHub Actions，运行 `make check` |
| 仓库结构 | 单个 Python 包，src 布局 |

## 备选方案与放弃理由

**语言**

- TypeScript / Node.js：OpenClaw 用的就是它，MCP 和微信相关的库也很多。但你已经有 Python 基础，国内 AI 应用岗位也普遍要求 Python。
- Rust：Codex 用的是它，性能和可靠性最好，但学习成本太高，会拖慢整个项目。
- Go：并发模型好，但 AI 生态较弱。

**agent 框架**

- LangChain / LangGraph、OpenAI Agents SDK、Pydantic AI：能很快跑起来，但循环被框架封装起来，就学不到最核心的部分。另外，设计文档 01 要求的持久化审批、在边界处插话、重启恢复，都需要完全掌控循环，用框架反而碍事。

**调用模型**

- OpenAI 的 Responses 接口：功能更多，DeepSeek 也已经支持，但各家国内模型的支持程度不一。chat-completions 仍然是兼容性最好的公共格式。
- 各家的原生 SDK：每家一套写法。统一走 OpenAI 兼容接口，换模型只需要改配置。
- LiteLLM：多一层依赖，而各家兼容层的差异（比如 DeepSeek 的 `reasoning_content`）还是得自己处理。

**存储**

- PostgreSQL：单用户、单进程用不上，还要多维护一个服务。SQLite 只是一个文件，备份就是复制文件。以后需要向量检索时，可以考虑 sqlite-vec 扩展，在设计文档 02 里再定。

**类型检查**

- mypy：也很成熟，但 pyright 更快。而且 Sublime 里的 LSP-pyright 用的就是 pyright，编辑器里看到的和 CI 检查的结果一致。

**Web 框架**

- FastAPI：第一阶段只有终端入口，用不上。接微信时再评估：微信 iLink 走的是长轮询，不一定需要 HTTP 服务。

## 后果

- 重试、持久化、并发控制都要自己写，工作量更大。但这正是这个项目想学的内容。
- asyncio 代码里不能有阻塞调用，否则整个循环都会被卡住。Ruff 的 `ASYNC` 规则会帮忙检查。
- 依赖版本锁在 `uv.lock` 里，CI 用 `uv sync --locked` 安装，保证本地和 CI 用的版本一致。
