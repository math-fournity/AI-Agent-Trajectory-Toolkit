# devin-acp-protocol skill

## 用途

Devin CLI 支持 ACP（Agent Client Protocol）模式——通过 `devin acp` 子命令启动为 JSON-RPC over stdio 的 server，client（你的代码）通过 stdin/stdout 与其交换结构化消息。

ACP 模式的核心价值：**实时获取 AI 的所有工作状态信号**，包括 thinking 内容的流式推送（`agent_thought_chunk`），这是 `-p` 非交互模式无法提供的。

本 canonical body 最初基于 Devin CLI v3000.4.25 的三轮实测编写；2026-08-26 已按当前
Devin 3000.6.2 的 `devin --help`/`devin acp --help`、shared Broker 双向 wire 和真实长 Round raw
更新。旧测试继续证明历史字段，当前脚本/runtime 结论只外推到明列版本和来源。

## 核心意识

**ACP 是 `-p` 模式的结构化替代方案。**

| 维度 | `-p` 模式 | ACP 模式 |
|---|---|---|
| 通信 | stdout 纯文本 | JSON-RPC 2.0 over stdio |
| thinking | 退出时在 `--export` 的 conversation.json 中 | **实时流式推送**（`agent_thought_chunk`） |
| 完成信号 | 进程退出 | `session/prompt` response 含 `stopReason` |
| 权限 | `--permission-mode` 全局设置 | `session/request_permission` 每次请求 |
| trajectory | `--export` 退出时一次性写入 | `session/update` 通知实时推送 |
| 状态检测 | 无实时信号（thinking 期间无任何输出） | 精确信号（thought/message/tool_call/permission） |

**何时用 ACP**：需要实时检测 AI 工作状态（如 thinking spin 检测）、需要实时 trajectory 采集、需要精细权限控制。

**何时用 `-p`**：只需要最终结果、不需要实时监控、简单的一次性任务。

**Raw chunk 不是 thinking block**：`agent_thought_chunk`/`agent_message_chunk` 是 transport delta；一次
界面/逻辑活动可能有数千 chunks。不得让每个 chunk 触发 artifact scan、状态重写或上层语义判断，也
不得手工按换行/标点拼段。命中 capability index 的 `CAP-ACP-ACTIVITY-BLOCKS` 后，使用
`scripts/acp_activity_blocks.py` 按协议边界自动生成可重建 activity blocks；raw wire 仍是审计真值。

## 一、启动 ACP server

```bash
devin acp                          # 启动为 ACP server（stdio 传输）
devin acp --model glm-5-2          # 指定模型
devin acp --model opus             # 指定其他模型
```

ACP server 作为子进程运行，通过 stdin/stdout 交换 JSON-RPC 2.0 消息。stderr 输出日志（不影响协议通信）。

**认证**：ACP server 从 `WINDSURF_API_KEY` 环境变量或 `devin auth login` 存储的凭证读取认证。也可以通过 ACP 的 `auth/login` 方法在运行时认证。

**重要**：ACP server 不是交互式 TUI——它不渲染终端 UI，只通过 stdio 交换 JSON-RPC 消息。适合被代码（而非人类）驱动。

## 二、协议版本——Devin CLI 用 v1

**重要发现（实测）**：Devin CLI v3000.4.25 的 `devin acp` 实际使用 **ACP v1 协议**（`initialize` response 返回 `protocolVersion: 1`），不是 v2。

v1 与 v2 的关键差异：

| 特性 | v1 | v2 |
|---|---|---|
| 完成信号 | `session/prompt` response 含 `stopReason` | `state_update: idle` + `stopReason` |
| session 创建 | `session/new`（**必须** `mcpServers` 字段） | `session/new`（`mcpServers` 可选） |
| session 恢复 | `session/load`（replay 历史） | `session/resume`（不 replay） |
| session 关闭 | `session/close`（需 `sessionCapabilities.close`） | `session/close` |
| tool_call 创建 | `tool_call` 通知（首次）+ `tool_call_update`（后续） | 只有 `tool_call_update`（首次创建） |
| thinking 通知 | `agent_thought_chunk` | `agent_thought_chunk`（相同） |

**Devin CLI ACP 的 sessionCapabilities**：`list` / `delete` / `additionalDirectories`——**没有 `close`**，所以 `session/close` 报 Method not found。关闭 session 用 `session/cancel` + 进程终止。

## 三、通信流程

### 3.1 完整流程

```
Client → Agent: initialize              # 协商协议版本和能力
Agent → Client: initialize response     # 返回 protocolVersion=1 + agentCapabilities
                                         # 如需认证：auth/login
Client → Agent: session/new             # 创建新 session（必须带 mcpServers 字段）
Agent → Client: session/new response    # 返回 sessionId
Client → Agent: session/prompt          # 发送用户消息（prompt）
Agent → Client: session/prompt response # 确认接受 prompt（空 result）
Agent → Client: session/update (多个)   # 实时推送 thought/message/tool_call 等
Agent → Client: session/prompt response # 处理完成后返回 {stopReason: "end_turn"}
                                         # （v1 中 session/prompt 是 request-response）
```

### 3.2 initialize

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {}
  }
}
```

Response 含 `agentCapabilities`（`loadSession` / `promptCapabilities` / `mcpCapabilities` / `sessionCapabilities`）、`authMethods`、`agentInfo`。

### 3.3 session/new

**v1 必须带 `mcpServers` 字段**（空数组也行），否则报 `Invalid params: missing field mcpServers`。

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/new",
  "params": {
    "cwd": "/path/to/working/directory",
    "mcpServers": []
  }
}
```

Response 返回 `sessionId`（如 `"curved-flannel"`——Devin 用随机英文单词作为 session ID）。

### 3.4 session/prompt

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/prompt",
  "params": {
    "sessionId": "curved-flannel",
    "prompt": [
      {
        "type": "text",
        "text": "Prove that √2 is irrational."
      }
    ]
  }
}
```

**v1 中 `session/prompt` 是 request-response**——Agent 处理完 prompt 后返回 response：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "stopReason": "end_turn",
    "usage": {
      "totalTokens": 23883,
      "inputTokens": 23096,
      "outputTokens": 787,
      "cachedReadTokens": 50
    }
  }
}
```

`stopReason` 值：`end_turn` / `max_tokens` / `max_turn_requests` / `refusal` / `cancelled`。

**在等待 response 期间**，Agent 会通过 `session/update` 通知实时推送所有内容（thought/message/tool_call）。

### 3.5 session/cancel

```json
{
  "jsonrpc": "2.0",
  "method": "session/cancel",
  "params": {
    "sessionId": "curved-flannel"
  }
}
```

这是 notification（无 id，无 response）。Agent 收到后中止当前操作，`session/prompt` 的 response 会以 `stopReason: "cancelled"` 返回。

## 四、session/update 通知——核心信号

`session/update` 是 Agent → Client 的 notification，推送所有实时内容。`update.sessionUpdate` 字段标识通知类型。

### 4.1 通知变体全览（实测验证）

| `sessionUpdate` 值 | 含义 | 实测验证 | 对检测的价值 |
|---|---|---|---|
| `agent_thought_chunk` | **thinking 内容流式更新** | ✅ 实测2: 22个, 实测3: 11个 | **核心信号——thinking 期间持续推送** |
| `agent_message_chunk` | message 内容流式更新 | ✅ 实测2: 754个, 实测3: 33个 | message 输出中 |
| `agent_thought` | thinking 整条消息 upsert | 未实测（v1 可能不支持） | - |
| `agent_message` | message 整条消息 upsert | 未实测 | - |
| `user_message` | 用户消息 upsert | 未实测 | - |
| `user_message_chunk` | 用户消息流式 | 未实测 | - |
| `tool_call` | **工具调用创建**（含 kind/title/status） | ✅ 实测3: 2个 (read+edit) | 工具调用开始 |
| `tool_call_update` | **工具状态更新** | ✅ 实测3: 6个 | pending→in_progress→completed |
| `tool_call_content_chunk` | 工具输出流式 | 未实测 | - |
| `plan` / `plan_update` | 执行计划 | 未实测 | - |
| `usage_update` | token 用量 | ✅ 全部测试 | token 统计 |
| `session_info_update` | session 信息 | ✅ 全部测试 | session 元数据 |
| `available_commands_update` | 可用命令 | ✅ 全部测试 | slash 命令列表 |
| `config_option_update` | 配置选项 | ✅ 全部测试 | model/mode 列表 |
| `current_mode_update` | 当前模式 | ✅ 全部测试 | 当前 permission mode |

### 4.2 agent_thought_chunk——thinking 实时流式推送

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "billowy-theory",
    "update": {
      "sessionUpdate": "agent_thought_chunk",
      "messageId": "msg_thought_a12",
      "content": {
        "type": "text",
        "text": "The user wants"
      }
    }
  }
}
```

**实测验证**：thinking 期间持续推送多个 chunk，拼接后得到完整 thinking 内容。

实测2（√2 无理数证明）的 thinking 内容（22 个 chunk 拼接）：
> "The user wants a proof that √2 is irrational. This is a pure math task, no tools needed."

实测3（文件读写）的 thinking 内容（11 个 chunk 拼接）：
> "I need to read /etc/hostname and create a file. Let me do both."

**时间分布**：短任务历史实测中 chunks 可在数秒内结束；当前长任务实测也可能在一个 thinking
block 内持续数分钟并产生数万 chunks。Chunk 数、流动或 elapsed 都不能单独证明交付进展或 stall。

### 4.2a Raw chunks 自动归并为 activity blocks

Canonical 脚本：

```bash
A=/Users/user/skills-devin/scripts/acp_activity_blocks.py

# 对正在增长的 raw wire 做只读 aggregate；默认不打印正文
python3 "$A" summary /private/state/workers/<worker_id>/wire.jsonl

# 只有明确需要有界 tail 时才显式请求
python3 "$A" summary /private/wire.jsonl --tail-chars 4000 --recent 3

# Round/worker 结束后物化 private derived blocks
python3 "$A" build /private/wire.jsonl \
  --output /private/evidence/activity_blocks.jsonl
```

脚本接受三种来源：shared Broker `{timestamp,direction,message}` wire、math-manify `{t,message}` incoming
JSONL、bare JSON-RPC。分块只使用以下可审计边界：

- thought/message stream kind 转换；
- 两边都存在且变化的可靠 `messageId`；
- `tool_call*`；
- 当前确为 thinking 时的 `_cognition.ai/thinking_complete`；
- prompt request/response、cancel、agent stopped、source EOF。

`_cognition.ai/thinking_complete` 可能在 message 已开始后迟到，不能无条件切断 message。缺 messageId
时，同 kind chunks 持续归并直到下一个协议边界，禁止用 UI 换行、标点或 NLP 猜分段。

双向 wire 同时保留 inbound updates 和 outbound prompt/cancel，才有资格声明 exact live boundary replay。
Incoming-only/方向不明来源仍可完整统计 chunks/chars并生成有界派生视图，但必须标
`partial_without_*outbound_control_boundaries`；它可能把跨 cancel/continuation 的相邻同类 chunks 合并。
Block 是 routing/navigation evidence，不取代 raw，也不自动证明数学或 artifact progress。

### 4.3 agent_message_chunk——message 实时流式推送

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "billowy-theory",
    "update": {
      "sessionUpdate": "agent_message_chunk",
      "messageId": "msg_agent_c42b9",
      "content": {
        "type": "text",
        "text": "# Proof"
      }
    }
  }
}
```

message chunks 拼接后得到 AI 的完整输出（proof 全文、回答内容等）。

### 4.4 tool_call——工具调用创建

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "gaudy-request",
    "update": {
      "sessionUpdate": "tool_call",
      "toolCallId": "chatcmpl-tool-bdd742",
      "title": "Read file",
      "kind": "read",
      "status": "pending"
    }
  }
}
```

`kind` 枚举：`read` / `edit` / `delete` / `move` / `search` / `execute` / `think` / `fetch` / `other`

### 4.5 tool_call_update——工具状态更新

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "gaudy-request",
    "update": {
      "sessionUpdate": "tool_call_update",
      "toolCallId": "chatcmpl-tool-bdd742",
      "status": "in_progress"
    }
  }
}
```

`status` 流转：`pending` → `in_progress` → `completed`（或 `failed`）

**实测状态流转**：
```
tool_call     kind=read   status=pending     title='Read file'
tool_call_upd              status=in_progress
tool_call_upd              status=in_progress
tool_call_upd              status=completed
```

### 4.6 Devin CLI 自定义通知

Devin CLI 在标准 ACP 通知之外，发送 `_` 前缀的自定义通知（ACP 协议允许的扩展）：

| 自定义通知 | 含义 |
|---|---|
| `_cognition.ai/thinking_complete` | thinking 阶段结束——在最后一个 `agent_thought_chunk` 之后、第一个 `agent_message_chunk` 或 `tool_call` 之前 |
| `_cognition.ai/agent_stopped` | agent 停止——session 结束 |

## 五、权限处理

### 5.1 session/request_permission

Agent 在执行需要权限的工具调用前，会发送 `session/request_permission` 请求（注意：这是 request，不是 notification，需要 response）：

```json
{
  "jsonrpc": "2.0",
  "id": "4089e451-45d4-4996-8da6-4d9d3f432895",
  "method": "session/request_permission",
  "params": {
    "sessionId": "gaudy-request",
    "toolCall": {
      "toolCallId": "chatcmpl-tool-b25771"
    },
    "options": [
      {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
      {"optionId": "allow_session", "name": "Yes, allow edits in /private/tmp (this session)", "kind": "allow_always"},
      {"optionId": "allow_always", "name": "Yes, always allow edits in /private/tmp", "kind": "allow_always"},
      {"optionId": "switch_bypass", "name": "Yes, switch to bypass mode", "kind": "allow_always"},
      {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"}
    ]
  }
}
```

**重要**：`id` 是 **string UUID**（不是 number）——response 必须用相同的 id。

### 5.2 权限响应格式

```json
{
  "jsonrpc": "2.0",
  "id": "4089e451-45d4-4996-8da6-4d9d3f432895",
  "result": {
    "outcome": {
      "outcome": "selected",
      "optionId": "allow_once"
    }
  }
}
```

**不是** `{outcome: "allow"}`——正确格式是 `{outcome: {outcome: "selected", optionId: "..."}}`。

`outcome` 值：
- `{"outcome": "selected", "optionId": "..."}`——选择某个选项
- `{"outcome": "cancelled"}`——prompt turn 被取消

### 5.3 自动批准策略

对应 `-p` 模式的 `--permission-mode`：

| `-p` 模式 | ACP 自动批准策略 |
|---|---|
| `dangerous` | 所有 `session/request_permission` 都回复 `allow_once` |
| `auto` | read 类工具自动批准，edit/execute 类需要判断 |
| `accept-edits` | read/edit 类自动批准，execute 类需要判断 |
| `smart` | 用快速模型判断每个请求是否安全 |

**ACP 的优势**：可以按工具 `kind` 和 `toolCallId` 精细决定是否批准，比 `-p` 的全局设置更灵活。

## 六、thinking spin、transport 与 delivery 必须分层

固定 5 分钟或“仍有 thought chunk”都不是通用结论。监督至少分开：

| 事实 | 证据 | 不能推出 |
|---|---|---|
| transport 活着 | raw update 最近仍到达 | artifact/数学仍推进 |
| thinking block 增长 | aggregate block chars/chunks/tail | 正常或值得无限等待 |
| tool active | tool call/status/age/argv | 工具可在可接受时间完成 |
| artifact progress | 目标 path/hash/mtime 变化 | 数学正确/final |
| delivery stall | thought持续而tool/artifact停 | 自动 cancel 授权 |

任意秒数阈值只触发升级检查。Master 应先运行 block summary，再对账 active/last tool、目标 artifact、
stderr、PID/session/cwd 和必要的 raw/native trajectory。长 block 若仍解决新问题可继续；跨多次 snapshot
重复“现在写入”而工具与目标文件持续零变化，才是可用的语义循环证据。取消必须按 exact session/
turn，并在动作后确认 response、trajectory、lease 和 artifact 收据。

## 七、raw wire、activity blocks 与 post-run trajectory

当前 `devin --help` 的全局 `--export [PATH]` 可在命令行先于 `acp` 表达“每 turn 导出”请求；但真实
Devin 3000.6.2 cancel 和 natural-end ACP runs 都曾没有生成目标 `conversation.json`。因此不能把参数
可解析冒充 export 已落盘：先请求并检查 native file，缺失/不完整时按 exact session/cwd/model 从
`sessions.db` 使用 `scripts/devin_traj.py` 私有导出 full forest/active chain/thinking/tools。

Live 阶段始终逐条保存 raw wire；`acp_activity_blocks.py` 只产生可重建派生视图。两者和 post-run
`sessions.db` 是 sibling evidence，不把 DB 当 live raw chunks 的上游。

### 7.1 低层组装不再手写

维护一个按 `messageId` 索引的消息列表，处理 chunk 和 upsert：

```python
messages = {}  # 历史示意；新调用者应使用 canonical block script

# 收到 agent_thought_chunk:
if update.sessionUpdate == "agent_thought_chunk":
    mid = update.messageId
    if mid not in messages:
        messages[mid] = {"role": "thought", "content": []}
    messages[mid]["content"].append(update.content)

# 收到 agent_message_chunk:
elif update.sessionUpdate == "agent_message_chunk":
    mid = update.messageId
    if mid not in messages:
        messages[mid] = {"role": "assistant", "content": []}
    messages[mid]["content"].append(update.content)

# 收到 tool_call / tool_call_update:
elif update.sessionUpdate == "tool_call":
    # 记录工具调用
elif update.sessionUpdate == "tool_call_update":
    # 更新工具状态
```

### 7.2 与 --export 的差异

| 维度 | `--export`（-p 模式） | ACP 组装 |
|---|---|---|
| 落盘时机 | 退出时一次性 | 实时（每收到 chunk 就可落盘） |
| thinking 字段 | `reasoning_content` | `agent_thought_chunk` 的 content |
| 完整性 | 保证完整 | 需要正确处理所有通知变体 |
| 格式 | Devin CLI 内部格式 | 自定义（可匹配 ATIF 或其他格式） |

Raw wire 应实时追加并 flush，避免崩溃丢失；block summary 可随时从当前 raw 重建，finished block file
默认写入 mode 0600 且父目录必须 0700。CLI receipt 只打印计数/hash/path，不打印 block 正文；显式
`--tail-chars` 是调用者承担隐私边界后的有界查看。

## 八、参考实现与 canonical 自动化

- Canonical raw-to-block：`/Users/user/skills-devin/scripts/acp_activity_blocks.py`；
- Canonical post-run Devin forest：`/Users/user/skills-devin/scripts/devin_traj.py`；
- Shared role-separated Broker raw wire：`/Users/user/codex/tools/agent_session_broker.py`；
- math-manify 的 `kernel/acp_control.py` 是 block v1 的真实业务参考和运行证据，不是共享黄金标准。

`scripts/test_acp_signals.py`（在 AI-Math-Competition-Problem-Solving-System 项目中）是最小 ACP 客户端参考实现，约 300 行，包含：

- `initialize` / `session/new` / `session/prompt` / `session/cancel`
- `session/update` 通知处理（所有变体）
- `session/request_permission` 权限处理（自动批准）
- 信号统计和日志

**用法**：
```bash
python scripts/test_acp_signals.py --prompt "Your prompt" --model glm-5-2 --timeout 120
python scripts/test_acp_signals.py --prompt-file problem.txt --model glm-5-2
```

## 九、实测验证数据

本 skill 的所有信号均经过实测验证（2026-08-21，Devin CLI v3000.4.25）：

| 测试 | prompt | 关键信号验证 |
|---|---|---|
| 实测1 | "What is 1+1?" | initialize / session/new / agent_message_chunk / stopReason |
| 实测2 | "Prove √2 is irrational" | **agent_thought_chunk (22个)** / agent_message_chunk (754个) |
| 实测3 | "Read file + write file" | tool_call (read+edit) / tool_call_update (in_progress→completed) / session/request_permission / _cognition.ai/thinking_complete |

2026-08-26 当前补充：Devin 3000.6.2 shared Broker E4 双向 wire 为 2,898 raw lines、2,883
session updates、2,801 text chunks/9,679 chars；canonical 脚本自动形成 8 blocks（thinking=4、message=4），
input/output mode 均0600、invalid=0，并标 exact-boundary eligible。`sessions.db` session=`verdant-puppy`
为45 nodes/8 assistant occurrences；4个DB unique payload均存在于blocks，另4个blocks保留live中间活动，
证明wire/DB是互补视图。真实 R17 incoming-only 25,326 chunks/67,456 chars被正确标为partial boundary
source，不能冒充恢复live cancel分界。

**完整实测报告**：`AI-Math-Competition-Problem-Solving-System/dev-docs/035-ACP模式调研与检测方案对比.md`

## 十、常见问题

### Q: session/new 报 "missing field mcpServers"
**A**: v1 协议要求 `mcpServers` 字段，即使没有 MCP server 也要传空数组 `"mcpServers": []`。

### Q: session/close 报 "Method not found"
**A**: Devin CLI 的 `sessionCapabilities` 没有 `close`。用 `session/cancel` + 进程终止替代。

### Q: 权限请求的 response 报 "Parse error"
**A**: 检查 response 格式——`id` 必须是 string UUID（与请求相同），`result.outcome` 必须是 `{"outcome": "selected", "optionId": "..."}`，不是简单的 `{"outcome": "allow"}`。

### Q: 收不到 agent_thought_chunk
**A**: 简单问题（如 1+1）不触发 thinking，所以没有 thought chunk。用需要推理的数学题测试。

### Q: session/prompt 一直不返回 response
**A**: 检查是否有未处理的 `session/request_permission`——Agent 在等待权限响应时不会继续处理 prompt。

## 十·补、与 OpenCode ACP 的对比

Devin CLI 不是唯一支持 ACP 的 coding agent。OpenCode（`opencode acp`）也支持 ACP，且两者有重要差异。完整对比在 `opencode-acp-protocol` skill 中，此处列出关键差异速查表：

| 维度 | Devin CLI ACP | OpenCode ACP |
|---|---|---|
| **启动** | `devin acp --model <model>` | `opencode acp --cwd <dir>` |
| **模型指定** | `--model` 命令行参数 | `opencode.json` provider 配置 |
| **session/prompt response** | ✅ 返回 `{stopReason, usage}` | ⚠️ **可能不返回**——需通知流静默检测 |
| **session/close** | ❌ 不支持 | ✅ 支持 |
| **session/fork** | ❌ 不支持 | ✅ 支持 |
| **session/resume** | ❌ 不支持（只有 load） | ✅ 支持 |
| **权限处理** | 每次发 `request_permission`，需手动回复 | 配置 `allow` 后**自动批准**，不发请求 |
| **自定义通知** | `_cognition.ai/thinking_complete` / `_cognition.ai/agent_stopped` | 未观察到 |
| **thinking 结束标记** | 有显式标记 | 无显式标记（靠观察通知流转变） |
| **trajectory 导出** | 全局 `--export` 语法可请求，但3000.6.2 ACP真实运行可能不落文件；必须检查并以raw wire + exact `sessions.db` fallback闭合 | ✅ 原生 `opencode export [sessionID]`（SQLite 落盘，ACP session 同样可导出，含 thinking 实文——2026-08-21 实测） |

**选方案建议**：
- 需要**精确完成检测** → Devin ACP（有 `stopReason`）
- 需要**简化权限处理** → OpenCode ACP（配置 allow 后自动批准）
- 需要**session fork/resume/close** → OpenCode ACP
- 需要**显式 thinking 结束标记** → Devin ACP（`_cognition.ai/thinking_complete`）
- 需要**免费无限量模型** → OpenCode ACP + OpenRouter Ox Alpha（1M context, free）
- 需要**进程死后回收完整 trajectory** → OpenCode 用原生 export；Devin 先查 requested native export，
  缺失时用 exact `sessions.db` full-forest fallback。Raw wire 未保存仍会失去 live protocol timing/boundary。

详见 `opencode-acp-protocol` skill。

## 十一、参考文档

- Devin CLI ACP 命令：https://docs.devin.ai/cli/reference/commands#devin-acp
- ACP 协议 v1 概览：https://agentclientprotocol.com/protocol/v1/overview
- ACP 协议 v1 Prompt Turn：https://agentclientprotocol.com/protocol/v1/prompt-turn
- ACP 协议 v1 Session Setup：https://agentclientprotocol.com/protocol/v1/session-setup
- ACP 协议 v1 Tool Calls：https://agentclientprotocol.com/protocol/v1/tool-calls
- ACP 协议 v1 Content：https://agentclientprotocol.com/protocol/v1/content
- ACP 协议 v2 概览（对比参考）：https://agentclientprotocol.com/protocol/v2/overview
- ACP 协议 v2 Migration（v1→v2 变化）：https://agentclientprotocol.com/protocol/v2/migration
- Zed 集成 Devin ACP：https://docs.devin.ai/cli/acp/zed
- JetBrains 集成 Devin ACP：https://docs.devin.ai/cli/acp/jetbrains
- Xcode 集成 Devin ACP：https://docs.devin.ai/cli/acp/xcode
