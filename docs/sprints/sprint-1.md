# Sprint 1：基础 agent 循环

| 项目 | 内容 |
|---|---|
| 目标 | 在终端里和 agent 对话：它能调用工具，拿到结果后接着思考，直到给出回答 |
| 开始日期 | 2026-10-12 |
| 负责人 | maodesikeng-boop |
| 设计依据 | [设计文档 01：Agent 循环](../design/01-agent-loop.md) |

## 完成标准（Definition of Done）

- [ ] `uv run butler` 能和 DeepSeek 对话；问"现在几点"时，它会先调用 `current_time` 工具再回答
- [ ] 循环和工具执行的各种情况都有测试，测试不联网
- [ ] 每个 PR 的 CI 都通过；`main` 分支受保护
- [ ] README 写明如何配置 API key 并启动

## 工单

| 编号 | 分支 | 内容 | 依赖 |
|---|---|---|---|
| S1-1 | `feat/messages-and-tools` | 消息类型；工具的定义、注册和执行；第一个工具 `current_time` | — |
| S1-2 | `feat/model-interface` | 模型接口 `ModelClient`；按剧本回复的假模型 `ScriptedModel` | S1-1 |
| S1-3 | `feat/agent-loop` | `run_turn` 循环：工具串行执行，每个工具调用都有结果 | S1-1、S1-2 |
| S1-4 | `feat/chat-cli` | 接入 DeepSeek；终端对话 | S1-3 |

每张工单的接口约定和验收标准写在对应的 GitHub issue 里。

## 不在本 Sprint

下面这些都在设计文档 01 里，留到后面的 Sprint 做：

- SQLite 持久化对话历史、重启恢复（§4、§12）
- 重试、看门狗、死循环检测、运行时长上限（§3.3、§10）
- `/stop` 中断和插话（§6）
- 执行命令（放在 Docker 沙箱里）和审批（§7）
- 输出截断（§5.3）

## 工作约定

- **一张工单对应一个分支、一个 PR。** 分支命名为 `类型/简短描述`。
- **提交信息和 PR 标题**遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：`feat:` 新功能、`fix:` 修复、`docs:` 文档、`test:` 测试、`refactor:` 重构、`ci:` CI 配置、`chore:` 其他杂项。
- **只用 Squash and merge 合并**：一个 PR 在 `main` 上只留下一个 commit。
- **review**：每个 PR 由 Claude review，意见处理完再合并。
- **提交前先跑 `make check`**，CI 跑的也是它。
- **不提交密钥**：配置一律通过环境变量传入，仓库里只放 `.env.example`。
