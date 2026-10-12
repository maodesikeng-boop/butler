# 设计文档 01：Agent 循环

| 项目 | 内容 |
|---|---|
| 状态 | 已确定 |
| 日期 | 2026-10-09 起草，2026-10-12 确定 |
| 作者 | Claude（技术负责人） |
| 评审 | maodesikeng-boop |
| 参考源码 | OpenAI Codex `19b7bffd7bd5c325a45b91111ce64c85610b90ba`（Rust，`codex-rs/`）；OpenClaw `245b7f6fb2ad8974a5c481359635f9fa50070caf`（TypeScript，版本 2026.9.8） |

本文只讲**一个任务从受理到完成的全过程**，也就是 agent 循环本身。上下文与记忆、插件机制、权限规则、执行环境、通道、定时任务各有单独的设计文档，本文只写到和它们的接口为止。

文中的引用格式：源码引用写成"Codex `文件:行号`"或"OpenClaw `文件:行号`"。Codex 的路径相对于 `codex-rs/`，OpenClaw 的路径相对于仓库根目录。

---

## 1. 两个参考实现的对比

| 方面 | Codex | OpenClaw | 我们的选择 |
|---|---|---|---|
| 组织方式 | 每个会话一个操作队列（`Op`）、一个事件队列，一个分发循环；每一轮任务跑在独立的异步任务里 | 进程级的"车道"队列：先拿到会话车道，再进入全局车道 | 照 Codex 的做法：每个会话一个操作队列、一个分发循环；并发控制简化为"每个会话一把锁 + 全局信号量" |
| 循环何时结束 | 模型不再调用工具，并且没有排队的输入；**没有步数上限** | 同上；**没有步数上限**，用"死循环检测"代替 | 两者结合：死循环检测 + 运行时长上限；没人值守的定时任务额外设步数上限 |
| 多个工具调用 | 工具默认串行，声明了可并行的才并行；结果按调用顺序写回 | 默认并行，有一个工具声明串行时整批改为串行；结果按调用顺序写回 | **默认串行**（更安全），工具自己声明可并行 |
| 工具出错 | 当作工具结果交给模型；只有内部错误才中止本轮 | 当作带 `isError` 标记的工具结果交给模型 | 一样 |
| 每个工具调用都有结果 | 每次发请求前做一次规范化：缺结果的补一条 `aborted`，没有对应调用的结果删掉；这些补丁不存盘 | 被跳过、被拒绝、被中断的调用，都会生成一条真实的合成结果 | 两层都要（见第 5 节） |
| 中途插话 | 新消息先存起来，下一次调用模型前合并进去；还能立即打断正在生成的回复（只支持 Responses 接口） | 在边界处插入：调用模型前、每批工具执行完后、串行工具之间；还没开始的工具会被跳过 | 照搬 OpenClaw 的边界插入（我们用的 chat-completions 接口也只能这样做） |
| 等待审批 | 在工具调用内部挂起等待；**不存盘**，重启后就丢了 | 先把审批请求存进 SQLite 再等待；**重启后一律当作拒绝** | 存盘，**重启后重新问你**（两家都没做到，见第 7 节） |
| 重启恢复 | 回放 JSONL 日志，重建对话历史；排队的输入、审批、正在运行的进程都不恢复 | 给没有结果的工具调用补上"结果未知"，然后**只开放只读工具**继续这一轮 | 照 OpenClaw 的做法 |
| 存储 | JSONL 日志文件（只追加） | SQLite（只追加，带写入权校验） | SQLite，只追加 |

---

## 2. 总体结构

```
 微信 / 终端 / 定时器
        │  Op（操作）
        ▼
 ┌─────────────── 会话执行器（每个会话一个）───────────────┐
 │  ops: asyncio.Queue[Op]                                  │
 │  分发循环：只负责"受理"，马上返回结果，不在这里跑长任务        │
 │  active_turn: 当前这一轮（最多一个），跑在独立的 asyncio.Task │
 │  pending_input: 运行中收到、还没合并进上下文的消息            │
 │  approvals: 等待审批的请求（同时存进数据库）                  │
 └──────────────────────────────────────────────────────────┘
        │ 事件（Event）
        ▼
 通道：决定怎么展示（微信只发完整消息和"正在输入"，终端逐字显示）
```

### 2.1 操作（Op）

所有外部输入都转换成 `Op`，放进会话的队列。每个 `Op` 都带一个 `Future`，用来立即回复受理结果。

```python
class Op: ...
class UserInput(Op):          text, channel, message_id, received_at
class Stop(Op):               reason                 # /stop、"停止"、"停下"
class ApprovalDecision(Op):   approval_id, decision  # 同意一次 / 以后都允许 / 拒绝
class ScheduledTrigger(Op):   job_id, kind, prompt   # kind: heartbeat | cron
class NewSession(Op): ...                            # /new
class Compact(Op):            focus | None           # /compact

class Admission(Enum):
    STARTED     # 开始了新的一轮
    STEERED     # 并入了正在运行的这一轮
    QUEUED      # 排队，等当前这一轮结束后再处理
    REJECTED    # 拒绝，并附上原因
```

**为什么要分开"受理"和"执行"**：这一轮任务跑在独立的 Task 里，所以它运行期间，分发循环照样能处理 `Stop` 和 `ApprovalDecision`。这一点照抄 Codex（Codex `core/src/session/handlers.rs:439-715`、`tasks/mod.rs:272-425`）。

### 2.2 受理规则

| 输入 | 空闲时 | 正在运行时 |
|---|---|---|
| 你发的普通消息 | 等待合并窗口结束后开始新的一轮（2.3） | **插入**当前这一轮（第 6 节） |
| `Stop` | 什么都不做，回复"现在没有在运行的任务" | 中断当前这一轮（第 6 节） |
| 对审批的回复 | 走第 7 节的"续跑"路径 | 唤醒正在等待审批的工具调用 |
| 定时任务 | 开始新的一轮（定时任务用自己独立的会话，见第 9 节） | 心跳任务：跳过，下次再来；cron 任务：排队 |

定时任务**永远不会插入或抢占**你正在进行的那一轮。这对应 Codex 的 `StartIfIdle` 模式（Codex `protocol/src/turn_input.rs:155-167`）。

### 2.3 合并连发的消息

用微信的人习惯把一句话拆成好几条连着发。空闲时收到第一条消息后，先等待 **1.5 秒**（可以配置）。等待期间每来一条新消息就重新计时，但从第一条算起，最多只等 **6 秒**。到时间后，把这些消息按顺序拼成一条输入，开始新的一轮。

OpenClaw 这项功能默认是关闭的（OpenClaw `src/auto-reply/inbound-debounce.ts:8-28`），它的子任务报告建议微信场景打开。图片、文件和控制命令（`/stop` 这类）不参与合并，立即处理（OpenClaw `src/channels/inbound-debounce-policy.ts:18-32`）。

### 2.4 并发

- **同一个会话内**：同一时间最多只有一轮在运行（用一把 `asyncio.Lock` 加上 `active_turn` 这个位置来保证）。
- **不同会话之间**：主会话和各个定时任务的会话可以同时运行，由一个全局信号量限制总数，默认 3。
- 定时任务里如果还要调用模型，比如做压缩，要用单独的名额，否则可能互相等待、卡死。OpenClaw 专门为此加了 `cron-nested` 车道（OpenClaw `src/agents/embedded-agent-runner/lanes.ts:25-29`）。

---

## 3. 一轮任务的生命周期

```
受理 → 落盘输入 → （需要的话）预先压缩 → 组装上下文
     → ┌→ 合并插话 → 调用模型（看门狗 + 重试） → 回复落盘
       │      ├ 没有工具调用、也没有新的插话 → 结束
       │      └ 有工具调用 → 执行这一批工具 → 结果落盘 → 死循环检测
       └──────────────────────────────────────┘
     → 投递最终回复 → 收尾（压缩、记忆整理）
```

```python
async def run_turn(turn: Turn) -> None:
    await compaction.preflight(turn)                     # 3.2：失败也不能丢掉这次的输入
    while True:
        await turn.commit_pending_input()                # 插话合并点 ①
        request = context.build(history.for_prompt())    # 第 4 节：规范化 + 前缀保持不变
        reply = await model_call(request, turn)          # 第 10 节：看门狗 + 重试
        await history.append(reply)                      # 先落盘，再执行工具
        if not reply.tool_calls:
            if turn.has_pending_input():                 # 插话合并点 ②
                continue
            break
        results = await tools.execute_batch(reply.tool_calls, turn)   # 第 5、6、7 节
        turn.loop_guard.observe(reply.tool_calls, results)            # 3.3
        if results and all(r.terminate for r in results):
            break
    await deliver_final(turn)                             # 第 11 节
    await post_turn_maintenance(turn)                     # 压缩、记忆整理（设计文档 02）
```

### 3.1 继续还是结束

满足下面任一条件就继续循环：这一步执行了工具，并且不是所有结果都要求结束；或者还有没合并进来的插话。否则本轮结束。这对应 OpenClaw 的 `packages/agent-core/src/agent-loop.ts:320-325` 和 Codex 的 `core/src/session/turn.rs:574`。

**每一轮都必须以一条给你的消息结束。** 如果工具都执行完了，模型却没有给出任何可见的回答，就再请求一次，这次只要文字、不带工具，让它给出结论。OpenClaw 的 `incomplete-turn-recovery.ts:28-41` 专门处理了这种情况。

### 3.2 预先压缩

压缩发生在**新输入写进历史之前**。如果压缩失败，新输入照样写进去，不能丢掉（Codex 的代码注释原文是："Compaction runs before the new input is recorded, so preserve it on every failure."，见 `turn.rs:192`）。什么时候压缩、怎么压缩，在设计文档 02 里讲；本文只规定这个调用的时机。

### 3.3 防止一直转下去

| 机制 | 规则 | 依据 |
|---|---|---|
| 死循环检测 | 对"工具名 + 字段排序后的参数 JSON + 执行结果"取哈希，记录最近 30 次。同样的情况出现 10 次：在工具结果里提醒模型；出现 20 次：拦下这次调用，告诉模型"不要重复这个操作，重新评估任务"；第二次触发拦截：结束本轮，并告诉你原因 | OpenClaw `src/agents/tool-loop-detection.ts:47-71`、`tool-loop-thresholds.ts:1` |
| 运行时长上限 | 你发起的任务：2 小时；定时任务：10 分钟。**等待审批期间暂停计时**，审批完成后继续计算剩余时间 | OpenClaw `run/attempt-timeout-prepare.ts:12-16,117-131`。OpenClaw 默认 48 小时，我们这里个人使用，收紧一些 |
| 步数上限 | 只对定时任务设置：40 步 | Codex 没有步数上限。子任务报告建议没人值守的任务加上 |
| 每日花费上限 | 按 token 数换算成金额，超出后停止，并在微信上提醒你 | 我们自己加的 |

---

## 4. 对话历史

### 4.1 存储

对话历史存在 SQLite 里，**只追加、不修改**：

```sql
CREATE TABLE transcript (
  session_id  TEXT    NOT NULL,
  seq         INTEGER NOT NULL,          -- 会话内单调递增
  kind        TEXT    NOT NULL,          -- message | compaction | reset | turn_aborted | interruption
  role        TEXT,                      -- system | user | assistant | tool
  payload     TEXT    NOT NULL,          -- JSON，序列化时字段排序固定
  turn_id     TEXT    NOT NULL,
  created_at  TEXT    NOT NULL,
  PRIMARY KEY (session_id, seq)
);
```

压缩、`/new` 和中断都不会删除或改写已有记录，而是**追加一条特殊记录**。重建上下文时，从最后一条 `compaction` 或 `reset` 记录开始读。Codex（`rollout_reconstruction.rs:60-91`）和 OpenClaw 都是这么做的。

### 4.2 写入顺序

1. **先写进历史，再落盘，最后通知通道**（Codex `session/mod.rs:2594-2612`）。
2. **带工具调用的助手消息，要在执行任何工具之前落盘**。OpenClaw 的代码注释是："every executed call has a durable owner"（`agent-stream-response.ts:365-367`）。这一条是重启恢复能做下去的前提。
3. 每条工具结果一产生就立即落盘。

### 4.3 每个工具调用都必须有结果

chat-completions 接口要求：每个 `tool_call` 后面都必须跟一条对应 `tool_call_id` 的 `tool` 消息，否则整个请求会被拒绝。我们分两层来保证。

**第一层：生成真实的结果。** 下面这些情况都要生成一条真实的 `tool` 消息，并且落盘：

| 情况 | 返回给模型的内容 |
|---|---|
| 工具不存在 | `Tool X not found` |
| 参数校验失败 | 校验错误的明细 + 收到的原始参数（OpenClaw `llm-core/src/validation.ts:392-432`） |
| 因为插话被跳过 | `Skipped to process an incoming message.`（OpenClaw `agent-loop.ts:62`） |
| 审批被拒绝 | `用户拒绝执行：<原因>` |
| 被你中断 | `aborted by user after Xs`（Codex `parallel.rs:258-318`） |
| 重启时还没有结果 | `Tool call interrupted before a result was recorded; its outcome is unknown.`（OpenClaw `llm-core/src/types.ts:352-353`） |

**第二层：发请求前做一次规范化，作为最后的保险。** `history.for_prompt()` 会给仍然缺结果的调用补一条 `aborted`，并删掉没有对应调用的结果。这一步的结果**不存盘**，并且处理结果是固定的（同样的输入总是得到同样的输出），否则会破坏前缀缓存（Codex `context_manager/normalize.rs:18-225`）。

### 4.4 保持前缀稳定，让缓存命中

agent 的输入远比输出多，Manus 统计的比例大约是 100:1，所以前缀缓存的命中率直接决定了成本和速度。规则如下：

1. **系统提示词完全不变**：不放时间，不放任何会变化的信息。
2. 会变化的环境信息（当前日期、时区、可用插件等）作为**追加的消息**发送，并且只在发生变化时才追加。Codex 就是这样追加 `<environment_context>` 的变化部分（`context/world_state/environment.rs:241-330`）。
3. **每条用户消息前面加上时间**，比如 `[10-09 14:03] 帮我看看邮件`。模型能知道现在几点，又不用去改前缀。
4. 序列化 JSON 时一律用 `sort_keys=True`。工具列表按名字排序，**整个会话期间固定不变**。MCP 服务中途通知工具列表变了，也要等到下一个会话才生效（Codex 博客对这一点有说明）。
5. 历史记录只追加；只有压缩时才会更换起点。

### 4.5 DeepSeek 和通义的特殊要求

- DeepSeek：后续请求里，助手消息要原样带上之前返回的 `reasoning_content`（OpenClaw `openai-completions-compat.ts:226`）。
- 通义：消息内容不能是空的（同一个文件 `:227`）。
- 模型只返回了思考内容、或者返回了空内容：前者最多重试 2 次，后者最多 1 次，重试时提示它"直接给出可见的回答"（OpenClaw `incomplete-turn-recovery.ts:30-35`）。
- 模型把工具调用写成了普通文本：第一版先记录日志，第二版再尝试自动修复（OpenClaw `packages/tool-call-repair`）。

---

## 5. 工具执行

### 5.1 工具的描述

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                       # MCP 工具统一命名为 mcp__<插件>__<工具>（Codex 的规则）
    description: str
    parameters: dict                # JSON Schema
    parallel_safe: bool = False     # 默认串行
    read_only: bool = False         # 重启恢复时只允许只读工具
    default_timeout_s: float = 60

@dataclass
class ToolResult:
    call_id: str
    content: str                    # 交给模型的文本
    status: Literal["ok", "error", "skipped", "denied", "aborted", "timeout", "unknown"]
    terminate: bool = False
```

### 5.2 一批工具调用怎么执行

照 Codex 的读写锁写法（`tools/parallel.rs:202-220`）：

- `parallel_safe` 的工具拿**读锁**，可以同时执行；
- 其他工具拿**写锁**，一个一个执行；
- 所有结果**按调用顺序**写回历史。

每个调用依次经过下面几步：

1. 找到工具。找不到就返回错误结果。
2. 解析参数 JSON，按 Schema 校验，能转换的类型先转换，比如 `"5"` 转成 `5`。
3. 检查权限，结果有三种：直接执行、先问你（第 7 节）、禁止。
4. 带超时执行。
5. 截断输出，然后落盘。

### 5.3 输出截断

- 交给模型的输出**最多 16,000 个字符**。超过时**保留开头和结尾各一半，砍掉中间**，在中间留一句：`…省略 N 个字符…完整输出见 /workspace/.butler/outputs/<call_id>.txt，可以用 grep 缩小范围`。
- 完整的输出写进执行环境里的这个文件，模型需要时可以自己去读。这正是 Manus 说的"可以恢复的压缩"，也比 Codex 只保留在日志里更有用（Codex `utils/string/src/truncate.rs:62-167`）。
- 命令类工具的输出开头固定加上 `Exit code / Wall time` 两行（Codex `tools/mod.rs:101-149`）。

### 5.4 命令执行的超时

- 默认 60 秒；模型可以在参数里自己指定 `timeout_s`，最多 30 分钟，用于安装软件这类慢任务。
- 超时后杀掉进程，并告诉模型：`command timed out after N s`。
- Codex 用的是"10 秒后先返回一个进程编号，模型再来查询"的模式（`unified_exec.rs:28-69`），这样更灵活，但也更复杂。第一版先不做，放到第二版。

---

## 6. 中断和插话

### 6.1 `/stop`：中断

触发条件：收到 `/stop`，或者整条消息只有"停""停止""停下""别做了"。这类消息走快速通道，不进排队（OpenClaw `abort-trigger-text.ts:4-48`）。

中断的顺序照搬 Codex（`tasks/mod.rs:925-1030,569-573`），**顺序不能乱**：

1. 取消当前任务，最多等 100 毫秒让它自己收尾；
2. 还没结束就强制停止，杀掉执行环境里正在运行的命令；
3. 给已经开始、但还没有结果的工具调用写入 `aborted by user after Xs`；
4. 追加一条中断记录，告诉模型："上一轮被用户中断了，可能有命令只执行了一半，重复之前先检查当前状态"（OpenClaw `turn-interruption.ts:32-34`）；
5. 落盘，然后通知通道"已停止"；
6. **最后**才清理正在等待的审批。如果先清理审批，等待中的审批会被模型看成"被拒绝"，然后它会继续往下做（Codex `tasks/mod.rs:570-571` 的注释）。

### 6.2 插话

插话只能在**边界处**合并进来。chat-completions 接口没办法打断一个已经在生成的回复，OpenClaw 也只在 Responses 接口上支持这种打断。

| 合并点 | 位置 |
|---|---|
| ① | 每次调用模型之前 |
| ② | 模型的回复里没有工具调用时：如果有插话，就继续循环，不结束本轮 |
| ③ | 串行执行的工具之间：一旦有插话，**还没开始的工具全部跳过**，各自写入 `Skipped to process an incoming message.`。正在执行的工具会让它执行完；同时执行的那一批不会被跳过（OpenClaw `agent-loop.ts:561-593,1358-1395`） |

两个细节：

- 插话被取出、但还没写进历史的那段时间，如果这一轮失败了，要把这些插话**放回队列最前面**，不能丢（OpenClaw `agent.ts:150-256` 的 `PendingMessageQueue`）。
- 有审批在等待时，你发来的消息先判断是不是在回复审批（第 7 节），不是的话才当作插话处理。

---

## 7. 审批：暂停与恢复

两个参考实现都有缺陷：Codex 的等待状态只存在内存里，OpenClaw 重启后一律当作拒绝。我们的场景里，你可能隔几个小时才看微信，中间服务也可能重启过。所以采用**"进程内等待 + 先存盘 + 重启后重新问你"**的做法。

### 7.1 审批记录先于通知存盘

```sql
CREATE TABLE approvals (
  id           TEXT PRIMARY KEY,
  short_code   INTEGER NOT NULL,   -- 微信里显示成 #3
  session_id   TEXT NOT NULL,
  turn_id      TEXT NOT NULL,
  tool_call_id TEXT NOT NULL,
  tool_name    TEXT NOT NULL,
  arguments    TEXT NOT NULL,      -- JSON，字段排序固定
  binding_hash TEXT NOT NULL,      -- sha256(规范化后的命令 + 工作目录 + 环境变量)
  status       TEXT NOT NULL,      -- pending | approved | denied | expired | executed
  created_at   TEXT NOT NULL,
  expires_at   TEXT NOT NULL       -- 默认 30 分钟
);
```

**先写进数据库，再发微信消息。** OpenClaw 的注释提醒过：顺序反过来的话，你的回复可能比记录先到，结果对不上号（`bash-tools.exec-approval-request.ts:110-111`）。

### 7.2 正常流程：服务一直在运行

1. 工具调用挂起等待，这一轮的运行时长停止计时。
2. 微信发出：`[#3] 要执行：apt-get install -y ffmpeg（在工作区里）。回复 1 同意 / 2 拒绝 / 3 以后都允许这类命令`。
3. 你回复后，用一条**原子的状态转换**把 `pending` 改成 `approved`。只有转换成功的那一次才会继续执行，所以重复点了两次也只会执行一次。
4. 执行前再算一次 `binding_hash`。和存盘的值不一致，就不执行。这保证了"你批准的命令，就是实际执行的命令"（OpenClaw `system-run-approval-binding.ts:57-161`）。
5. 超过 30 分钟没有回复，就当作拒绝。告诉模型"用户没有批准"，模型自己决定接下来怎么做。

### 7.3 怎么判断你的消息是在回复审批

- 你的消息是 `1`、`2`、`3`、`同意`、`拒绝`、`#3 1` 这类格式，并且**确实有审批在等待**：当作审批回复。
- 只有一个审批在等待时，可以不写编号；有多个时，必须写编号，否则 agent 会反问你指的是哪一个。
- 其他消息都当作普通的插话。

### 7.4 重启后怎么办

1. 启动时，把状态还是 `pending` 的审批全部查出来。
2. 在微信上重新问你：`服务重启过，之前的 [#3] 还要执行吗？回复 1 同意 / 2 拒绝`。
3. 你同意后，开始一轮"续跑"：校验 `binding_hash`，执行这个工具，把结果用**原来的 `tool_call_id`** 写回历史，然后接着正常的循环继续。
4. 你拒绝或者超时：写入"拒绝"作为这个调用的结果，然后续跑一轮，让模型收尾。

"以后都允许"这个规则具体怎么保存、匹配范围多大（比如只匹配完全一样的命令，还是匹配"apt-get install"这一类命令），放在**设计文档 04（权限与安全）**里定。

---

## 8. 上下文窗口（这里只写接口，细节见设计文档 02）

- **估算 token 数**：上一次请求时接口返回的 `total_tokens`，加上之后新增内容的估算值，再乘以 1.2 作为余量。新增内容的估算：英文按每 4 个字符算 1 个 token，中文按每个字算 1 个 token（Codex `history.rs:919-951`；OpenClaw 把中文按字符计算）。
- **压缩阈值**：上下文窗口减去预留空间，预留空间取 `min(20000, 窗口的 1/4)`（OpenClaw `compaction.ts:210-214`；Codex 设的是 90%）。
- **压缩时的切分点**只能在用户消息之前，**不能把一个工具调用和它的结果拆到两边**（OpenClaw `compaction.ts:382-401`）。
- 每个模型的上下文窗口大小**必须在配置里写明**。OpenClaw 不知道窗口大小时默认按 200k 算，对 DeepSeek 和通义并不适用。

---

## 9. 定时任务触发的轮次（这里只写接口，细节见设计文档 07）

- **cron 任务**：每次运行都用一个全新的独立会话，`cron:<job_id>:<时间>`，不会塞满你的主会话（OpenClaw 也是这样）。
- 定时任务的提示词开头加一段说明："这是无人值守的定时任务，没有人能回答你的问题或批准操作；没有需要汇报的内容就只回复 `NO_REPLY`"（OpenClaw `run-prepare-runtime.ts:136-146`）。
- **定时任务里需要审批的操作，一律当作拒绝**，因为没有人能即时批准。需要你批准的事情，在结果里写明，推送给你，由你在主会话里决定。
- **只有整条回复恰好是 `NO_REPLY` 时，才不发送。** 不能用"回复里包含 NO_REPLY"来判断，否则有实质内容的回复也会被吞掉（OpenClaw `tokens.ts:61` 的注释）。
- 如果没有可用的推送路径（还没有保存过微信的 `context_token`），**在调用模型之前**就跳过，省下这次的花费（OpenClaw `heartbeat-runner-execution.ts:453-465`）。

---

## 10. 调用模型：看门狗、重试、出错

### 10.1 只在一个地方重试

调用 `AsyncOpenAI` 时设置 `max_retries=0`，所有重试都由循环自己负责，否则 SDK 内部的重试会让我们算不准重试次数。OpenClaw 的注释原文是："SDK-internal retries would hide attempts from its budget"（`openai-transport-params.ts:383-385`）。

| 错误类型 | 处理 |
|---|---|
| 限流（429）、服务端出错（5xx）、网络错误、超时、过载 | 重试。等待时间 = 1 秒 × 2 的 n 次方 × 0.5 到 1.5 之间的随机系数，最长 30 秒；如果接口返回了 `Retry-After`，等待时间不少于它。90 秒内最多重试 8 次 |
| 中文的限流提示，比如"请求过于频繁""调用频率""频率限制" | 按限流处理（OpenClaw `retry-evidence.ts:32-33`） |
| 额度用完（日额度、余额不足）、超出上下文长度、认证失败、其他 4xx | **不重试**。超出上下文长度时先压缩（最多 3 次），其余情况直接告诉你 |

**重试时接着当前的历史继续请求，绝不重新提交你原来的那条消息。** 如果这一次尝试里已经执行过有副作用的工具，或者已经给你发过消息，不能假装什么都没发生、从头再来一遍（OpenClaw `attempt-recovery.ts:385-386` 的注释）。

### 10.2 看门狗：防止模型调用卡住

- **首个数据块**：120 秒内必须收到。
- **空闲超时**：120 秒内没有收到任何数据，就中止这次请求。
- **进展超时**：240 秒内没有实质进展，也中止。只有正文、`reasoning_content`、工具调用、结束原因、用量统计算作进展；保活用的空数据块不算（OpenClaw `llm-idle-timeout.ts:243-349`）。
- 超时后**主动关闭 HTTP 连接**，因为有些服务商会忽略取消信号。
- 连续 5 次超时、并且一直没有产出，就停止，避免一直白白花钱（OpenClaw `idle-timeout-breaker.ts:3`）。

### 10.3 重试期间给你反馈

第一次重试时不打扰你。连续重试超过 30 秒，在微信上发一条"模型服务暂时不可用，正在重试"。同一轮里这类消息最多发一次，避免让你以为它卡死了，又不至于刷屏（Codex `responses_retry.rs:151-152` 的注释）。

---

## 11. 投递和事件

- 循环会发出这些事件：`turn_started`、`assistant_delta`、`assistant_message`、`tool_started`、`tool_finished`、`approval_requested`、`turn_finished{status}`、`error`。
- 微信通道只发送最终的回复。如果这一轮超过 30 秒还没有结束，就补发一条进度消息，比如"正在安装 ffmpeg"；之后最多每 2 分钟发一次。
- 发送消息要先写进一个**发件箱表**，再真正发出去。如果状态停在"已开始发送、结果未知"，重启后**不能盲目重发**，否则你会收到两条重复的消息（OpenClaw `delivery-queue-recovery.ts:564-635`）。具体在设计文档 06 里定。
- 审计日志**只记录元数据**：哪一轮、调用了什么工具、结果状态码、耗时、用了多少 token。不记录消息正文、工具参数和工具结果，因为里面可能有你的邮件内容（OpenClaw 的审计账本就是这样做的）。

---

## 12. 重启恢复

启动时按顺序执行：

1. 加锁文件（记录进程号和启动时间），保证同一份数据同一时间只被一个进程使用（OpenClaw `gateway-lock.ts:68-89`）。
2. 找出状态还是 `running` 的轮次。对其中有工具调用、但缺少结果的，补写一条"结果未知"。
3. 如果是主会话：追加一条中断说明，"服务重启过，上一轮被中断了。重复任何操作之前，先确认当时的实际状态"，然后**只开放只读工具**续跑一轮，向你汇报情况（OpenClaw `tool-replay-safety.ts:6-28`、`restart-recovery-prompt.ts:1-5`）。
4. 如果是定时任务的会话：标记为中断，等下一次定时触发时再运行。
5. 状态还是 `pending` 的审批：按 7.4 重新问你。

---

## 13. 测试策略

写一个**脚本化的假模型**：按事先写好的剧本，逐步返回"要求调用工具 X"或"给出最终回答"。下面这些情况都要有测试：

| 测试项 | 验证什么 |
|---|---|
| 基本循环 | 调用工具 → 拿到结果 → 给出回答；历史记录的顺序正确 |
| 工具结果配对 | 工具出错、被跳过、被拒绝、被中断时，每个调用都有对应的结果；规范化之后，请求可以正常发送 |
| 并行与串行 | 同时执行的工具，结果仍然按调用顺序写回 |
| 插话 | 在 ①②③ 三个合并点插入的消息都能被合并进来；还没开始的串行工具会被跳过 |
| 中断 | 第 6.1 节的 6 个步骤按顺序发生；中断时正在等待的审批，最终状态是"中断"而不是"被拒绝" |
| 审批 | 重复回复只执行一次；`binding_hash` 不一致时拒绝执行；超时按拒绝处理；重启后重新询问 |
| 死循环检测 | 同样的调用达到 10 次时提醒、20 次时拦截、再次触发时结束 |
| 重试 | 各类错误按 10.1 的规则处理；重试时不会重新提交原来的消息 |
| 重启恢复 | 缺少结果的调用补上"结果未知"；续跑时只开放只读工具 |
| 前缀稳定 | 连续两次请求时，前一次的消息列表正好是后一次的开头（逐字节比较） |

---

## 14. 第一版的范围

| 第一版做 | 以后再做 |
|---|---|
| 第 2 到第 13 节的全部内容 | 命令执行返回进程编号、可以轮询（Codex 的 unified exec） |
| 默认串行，工具可以声明并行 | 自动修复写成文本的工具调用 |
| 重启恢复、审批持久化 | 卡死检测：每 30 秒检查一次，2 分钟告警，5 分钟中止 |
| 看门狗和重试 | 多个模型之间自动切换（OpenClaw 的 fallback 链） |

---

## 15. 已确定的事项（2026-10-12）

以下 4 项原为待定，评审时全部按建议值确定：

1. 合并连发消息的等待窗口：1.5 秒，最长 6 秒。
2. 运行时长上限：你发起的任务 2 小时；定时任务 10 分钟，最多 40 步。
3. 工具执行默认串行，照 Codex 的做法；工具自己声明可以并行时才并行。
4. 审批的超时时间：30 分钟。
