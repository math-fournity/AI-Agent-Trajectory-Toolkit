---
name: zcode-trajectory
description: >
  ZCode (z.ai 桌面客户端) model-io session trajectory 数据的完整存储位置、JSONL schema、字段语义、读取方法。
  覆盖 model_io 记录、request/response envelope、消息结构、messagesKind(full/tail/delta)、
  bodySource 双变体、error 记录、turn 分组、rate-limit 终止记录。
  WHEN to use: 需要提取/解析/审计 ZCode session 的模型对话数据时；需要读取 reasoning/thinking、
  tool_calls、tool 结果、usage 时；需要回溯某个 Master Agent 的工作脉络时；
  需要分析 ZCode 的上下文窗口管理(full→tail/delta)行为时；遇到 Rate Limit 中断需要恢复工作时。
  WHEN NOT to use: Devin CLI 的 trajectory（用 devin-cli-trajectory skill）；一般编码任务。
---

# zcode-trajectory skill

## 用途

ZCode（`z.ai` 的 Electron 桌面客户端，`ZCode/3.7.7`）会把每个 session 的所有模型 API 调用落盘成 NDJSON。
本 skill 说明存储位置、记录 schema、字段语义、读取方法，供数据提取、审计、工作脉络回溯使用。

schema 基于 `model-io-sess_681fe4c5-297a-4ee3-a3fe-f0e7e396fe6f.jsonl`（118 行 / 34MB，2026-08-21 实测）完整反推。

## 存储位置

```
~/.zcode/cli/rollout/model-io-sess_<session-id>.jsonl
```

- 一个 session 一个文件，文件名含 `sessionId`（`sess_<uuid>`）。
- NDJSON：每行一个 JSON 对象，对应**一次模型 API 调用**。
- 文件可很大（34MB / 118 行很常见——单行含完整 message 历史时体积爆炸）。
- session 运行中持续追加；Rate Limit / 用户中断 / 正常结束都会落盘。

## 顶层记录结构（每行一个 `model_io` 记录）

所有记录 `type: "model_io"`。顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 恒为 `"model_io"` |
| `sessionId` | string | `sess_<uuid>`，整文件共享 |
| `turnId` | string | `turn_<uuid>`，把记录分组为 turn（一个用户回合 → 多次模型调用） |
| `requestId` | string | `<uuid>`，每次请求唯一；**重试会换新 requestId** |
| `traceId` | string | `<uuid>`，一个 turn 内的请求共享 |
| `querySource` | string | `"session_title"` \| `"main_turn"` |
| `attempt` | int | 1 \| 2，turn 内重试计数 |
| `startedAt` / `completedAt` | string | ISO-8601 UTC（`...Z`） |
| `durationMs` | int | 墙钟耗时 |
| `model` | object | 见下 |
| `request` | object | 请求 envelope，见下 |
| `response` | object | 响应 envelope，见下 |
| `error` | null \| object | 失败时 `{name, message, stack}` |

### `model` 对象

```json
{"modelId":"GLM-5.2","providerId":"builtin:zai-coding-plan","role":"main","source":"session","variant":"high"}
```

- `role`: `"lite"`（标题生成等辅助调用）| `"main"`（主 agent 推理）
- `variant`: `"high"`（对应 GLM-5.2 High）

## `request` envelope

| 字段 | 类型 | 说明 |
|---|---|---|
| `body` | object | API 请求体，**两种变体**见下 |
| `headers` | object | HTTP 头（`user-agent: ZCode/3.7.7`、`x-zcode-*`、`x-request-id` 等） |
| `maxOutputTokens` | int | main=112000，lite=32000 |
| `messages` | array | **逻辑消息列表**（agent-runtime 视角），见消息结构 |
| `providerOptions` | object | `{endpoints, apiFormat, modelSupportedFormats, anthropic}` |
| `toolNames` | array | 可用工具名清单 |
| `messageCount` | int | 此刻对话总消息数（turn 内单调递增：6→10→12→…→316） |
| `messagesKind` | string | `"full"` \| `"tail"` \| `"delta"`，见下 |
| `messageOffset` | int | tail/delta 时的起始索引 |
| `bodyMessageCount/Kind/Offset` | int/string | **仅 bodySource=ai_sdk_options 记录出现**，描述 body 内原始消息视图 |

### `messagesKind` 语义（ZCode 的上下文窗口管理）

| 值 | 含义 | `request.messages` 内容 |
|---|---|---|
| `full` | 发送完整对话（offset=0） | 全部 N 条 |
| `tail` | 只发尾部（offset=K, count=N） | 最近 N-K 条（丢弃最旧消息） |
| `delta` | 只发增量（offset=K, count=N） | 自上次调用后新增的 N-K 条 |

一个 turn 内典型演化：早期 `full` → 上下文超窗后切 `tail`/`delta` 交替。这是 ZCode 自动上下文压缩的直接证据——**回溯工作脉络时，`tail`/`delta` 记录的 `request.messages` 不含完整历史，需要向前找 `full` 记录或用 `messageOffset` 拼接**。

### `request.body` —— 两种变体

#### 变体 A：正常记录（无 `bodySource`，占绝大多数）

keys: `model, max_tokens, thinking, output_config, metadata, system, tools, tool_choice, stream`
**不含 `messages`**——消息在 `request.messages`。

| 字段 | 值 |
|---|---|
| `model` | `"GLM-5.2"` |
| `max_tokens` | main=128000，lite=32000 |
| `thinking` | `{type:"enabled", budget_tokens:16000}`（main）；`null`（lite，禁用思考） |
| `output_config` | `{effort:"high"}`（main）；`null`（lite） |
| `metadata` | `{user_id:"[REDACTED]"}` |
| `system` | `[{type:"text", text:string}, ...]`——系统提示（多条拼接） |
| `tools` | `[{name, description, input_schema}, ...]`（main，24个）；`null`（lite） |
| `tool_choice` | `{type:"auto"}`（main）；`null`（lite） |
| `stream` | `true` |

#### 变体 B：`bodySource=ai_sdk_options` 记录（错误/流式记录）

keys: `bodySource, experimental_include, maxOutputTokens, messages, model, providerOptions, stream, tools`
**含 `messages`**——这是从 AI SDK options 层抓取的**原始 outgoing HTTP body**（完整消息）。

| 字段 | 值 |
|---|---|
| `bodySource` | `"ai_sdk_options"` |
| `experimental_include` | `{requestBody:true, responseBody:true}`（日志包含标志） |
| `maxOutputTokens` | int（镜像 `request.maxOutputTokens`） |
| `messages` | array——**完整原始消息体**（`bodyMessageCount` 条） |
| `model/providerOptions/stream/tools` | 与 envelope 重复 |

> 关键区别：变体 B 同时记录了「逻辑视图」(`request.messages`，tail/delta) 和「原始 body」(`request.body.messages`，full)。变体 A 只记逻辑视图。**遇到 error 记录想看完整请求时，读 `request.body.messages`**。

### `request.providerOptions`

```json
{
  "endpoints": {"baseURL":"https://api.z.ai/api/anthropic","paths":{"anthropic":"/v1/messages"}},
  "apiFormat": "anthropic-messages",
  "modelSupportedFormats": {},
  "anthropic": {"effort":"high","thinking":{"budgetTokens":16000,"type":"enabled"}}
}
```

API 走 Anthropic Messages 兼容格式（`/v1/messages`），baseURL 指向 `api.z.ai/api/anthropic`。

## 消息结构（`request.messages` / `body.messages` 内每条）

所有消息共享 `role` + `content`，其余键按 role 不同：

### system 消息
`{role:"system", content: string}`
- content 是纯字符串（system-reminder 注入、AGENTS.md 上下文、技能/规则注入等）
- 一个请求里可有多条 system 消息穿插在 user/assistant 之间（运行时注入）

### user 消息
`{role:"user", content: string | array}`
- 通常为字符串

### assistant 消息
`{role:"assistant", content: array, toolCalls?: array, modelRef?: object, cacheControl?: object}`

`content` 是 part 数组，part 类型**在本数据集只见到两种**：
- `{type:"reasoning", text:string, providerOptions:{anthropic:{signature:string}}}` —— **思考内容**（注意：ZCode 用 `reasoning` 而非 `thinking` 作为 part type；signature 是思考签名）
- `{type:"text", text:string}` —— 可见文本回复

可选键：
- `toolCalls`: `[{id, name, input}, ...]`——当 `finishReason="tool-calls"` 时存在。`id` 形如 `call_<hex>`，`input` 是对象
- `modelRef`: `{providerId, modelId, role, source, variant}`——产生该消息的模型
- `cacheControl`: `{type:"ephemeral"}`——该消息是缓存断点

### tool 消息（工具结果）
`{role:"tool", content:string, toolCallId:string, toolName:string, isError:boolean, cacheControl?:object}`
- `content`: 工具输出（常为 JSON 字符串）
- `toolCallId`: 对应 assistant.toolCalls[].id
- `toolName`: 被调工具名
- `isError`: `true` 表示工具执行失败（如 Bash exit≠0）
- `cacheControl`: 可选 ephemeral 断点

## `response` envelope

| 字段 | 类型 | 说明 |
|---|---|---|
| `finishReason` | string \| null | `"stop"` \| `"tool-calls"` \| `null`（error 时 null） |
| `headers` | object | 响应头（`content-type: text/event-stream`、`x-request-id`、`x-log-id`、`x-process-time` 等） |
| `modelId` | string \| null | 实际服务的模型（如 `"glm-5.3"`，可能与请求模型不同）；error 时 null |
| `responseId` | string \| null | `msg_<...>`，provider 响应 id；error 时 null |
| `text` | string \| null | 可见文本。**tool-calls 响应也有 text**（工具调用前的前言）；error 时 null |
| `toolCalls` | array | `[{id, name, input}, ...]`；error 时 `[]` |
| `usage` | object | `{inputTokens, outputTokens, totalTokens, cacheReadTokens, cacheWriteTokens}`；error 时 `{}` |
| `providerMetadata` | object | `{anthropic:{usage, cacheCreationInputTokens, stopSequence, iterations, container, contextManagement}}`——原始 provider 元数据 |

> `response.usage` 是归一化用量；`response.providerMetadata.anthropic.usage` 是原始 Anthropic 用量（含 `cache_read_input_tokens`、`server_tool_use` 等）。两者数值应一致。

## `error` 对象（顶层，失败时）

`{name, message, stack}`
- `name`: `"TypeError"` / `"Error"` / `"TerminalStreamChunkError"` 等
- `message`: 人读消息
- `stack`: Node.js 堆栈（指向 `ZCode.app/Contents/Resources/glm/zcode.cjs`）

**重要 error 类型**：
- `TerminalStreamChunkError` 且 message 含 `[1308][Usage limit reached for 5 hour. Your limit will reset at <时间>]` —— **5 小时用量限额触发**，session 被强制终止。这是本次 schema 反推样本的终止原因。
- `TypeError: terminated` —— 流被中断（undici Fetch.onAborted）
- `Error: v4 sendQueuedNow preempts active turn` —— 用户发新消息抢占当前 turn

error 记录的 `response` 是桩：`{headers, toolCalls:[], usage:{}}`，`finishReason/text/modelId/responseId` 均为 null。

## turn 结构与回溯要点

- 一个 session = N 个 turn（`turnId` 分组）。样本 118 行 = 3 个 turn。
- 一个用户回合 = 一个 turn = 多次模型调用（agent 循环：model→tool→model→tool→…→stop）。
- `messageCount` 在 turn 内单调递增（6→316），是定位「对话进展到哪」的可靠指针。
- **重试**：`attempt=2`，新 `requestId`，同 `turnId`（样本 line 67 是 line 66 失败后的重试）。
- **Rate Limit 终止**：turn 末尾出现 `error.name=TerminalStreamChunkError` 的记录，session 结束。回溯时该 turn 的工作**未完成**，需从最后一个 `finishReason=stop` 或 `tool-calls` 的成功记录接续。

### `querySource`

| 值 | 含义 | 特征 |
|---|---|---|
| `session_title` | 标题生成辅助调用 | `role=lite`、无 tools、`thinking=null`、2 条消息、`maxOutputTokens=32000`、`finishReason=stop` 返回 `{"title":"..."}` JSON。**总是第 0 行** |
| `main_turn` | 主 agent 推理调用 | `role=main`、24 个 tools、thinking 启用、`maxOutputTokens=112000` |

## 配套脚本：`scripts/zcode_traj.py`

**位置**：`/Users/user/skills-devin/scripts/zcode_traj.py`

**设计**：两层遍历——第一层 `scan` 输出带 `idx` 定位参数的概览，第二层 `inspect` 用 `idx` 取细节。避免逐行手写 inline 解析脚本。

### 第一层：`scan` —— 高层次遍历

```bash
# 人类可读表格（默认）
python3 /Users/user/skills-devin/scripts/zcode_traj.py scan <jsonl>

# JSONL 输出（供程序消费，每行一个紧凑对象）
python3 /Users/user/skills-devin/scripts/zcode_traj.py scan <jsonl> --json

# 过滤某个 turn
python3 /Users/user/skills-devin/scripts/zcode_traj.py scan <jsonl> --turn turn_af628876
```

输出列：`idx | turn | qs | role | kind | off | cnt | att | finish | err | dur | tools | text_head`
- `idx`（0-based 行号）= 深层次定位参数
- `kind` = messagesKind（full/tail/delta）
- `tools` = response.toolCalls 的工具名列表
- `text_head` = response.text 前 80 字

**只解析顶层字段，不展开 messages content**——单行可能几 MB，scan 阶段绝不展开。

### 第二层：`inspect` —— 深层次定位

```bash
# 基本展开：顶层元数据 + request 概要 + messages 结构摘要 + response + error
python3 /Users/user/skills-devin/scripts/zcode_traj.py inspect <jsonl> <idx>

# 展开第 N 条消息的 reasoning 全文（不截断）
python3 /Users/user/skills-devin/scripts/zcode_traj.py inspect <jsonl> <idx> --msg <N> --reasoning

# 展开工具调用输入全文
python3 /Users/user/skills-devin/scripts/zcode_traj.py inspect <jsonl> <idx> --tool-input

# 控制文本截断长度（默认 500）
python3 /Users/user/skills-devin/scripts/zcode_traj.py inspect <jsonl> <idx> --truncate 2000
```

`inspect` 默认输出：
- 顶层元数据（sessionId/turnId/requestId/attempt/时间/duration/model）
- request 概要（messagesKind/offset/count/bodySource/thinking/tools 等）
- response（finishReason/modelId/usage/text/toolCalls）
- error 详情（name/message/stack，如有）
- messages 结构摘要（每条 `[i] role content=[part_types] toolCalls=[names]`）

`--msg <N>` 深入第 N 条消息：展开 content 各 part（reasoning text / text / tool_use input / tool_result），assistant 的 toolCalls，tool 消息的 content。

### 典型工作流

```bash
# 1. scan 看工作脉络
python3 scripts/zcode_traj.py scan <jsonl>

# 2. 找到感兴趣的 idx（如 idx=71 是最后的 stop 响应）
python3 scripts/zcode_traj.py inspect <jsonl> 71

# 3. 想看某步的思考全文
python3 scripts/zcode_traj.py inspect <jsonl> 21 --msg 4 --reasoning

# 4. 想看工具调用的完整输入
python3 scripts/zcode_traj.py inspect <jsonl> 1 --tool-input
```

### 回溯被 Rate Limit 中断的工作

1. `scan` 找到 `err=TerminalStreamChunkError` 的行（Rate Limit 终止点）
2. 该 turn 内向前找最后一个 `finish=tool-calls` 或 `finish=stop` 的成功记录 = 工作断点
3. `inspect <断点idx>` 看最后做了什么（response.text + response.toolCalls）
4. `inspect <断点idx> --msg <N> --reasoning` 看最后一步的思考 = 接续点

> 注意：直接 `json.load` 整文件会爆内存（单行 34MB 级）。脚本内部逐行 `json.loads`，scan 阶段不展开 messages。

## 与 Devin CLI trajectory 的区别

| 维度 | ZCode | Devin CLI |
|---|---|---|
| 位置 | `~/.zcode/cli/rollout/model-io-sess_*.jsonl` | `~/.local/share/devin/cli/transcripts/*.json` (ATIF) |
| 格式 | NDJSON，每行一次模型调用 | 单文件 ATIF JSON |
| 思考 part type | `reasoning` | 见 devin-cli-trajectory skill |
| 上下文管理 | `messagesKind: full/tail/delta` 显式 | ATIF 内部处理 |
| 客户端 | ZCode Electron (`ZCode/3.7.7`) | devin CLI |

分析 ZCode 数据时**用本 skill**；分析 Devin CLI 数据时用 `devin-cli-trajectory` skill。
