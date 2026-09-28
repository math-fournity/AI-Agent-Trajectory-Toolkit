# opencode-acp-protocol skill

## 用途

OpenCode 支持 ACP（Agent Client Protocol）模式——通过 `opencode acp` 子命令启动为 JSON-RPC over stdio 的 server，client（你的代码）通过 stdin/stdout 与其交换结构化消息。

ACP 模式的核心价值：**实时获取 AI 的所有工作状态信号**，包括 thinking 内容的流式推送（`agent_thought_chunk`），这是普通 TUI/CLI 模式无法程序化获取的。

本 skill 的初始信号基线来自 OpenCode v1.18.19；model/config 与 `session/resume` 合同已在 1.18.21
重新核对当前官方同版本源码和真实 ACP。版本变化后仍须重探，不能外推。

## 核心意识

**OpenCode ACP 是 OpenCode 的结构化通信模式，与 Devin CLI ACP 是平行的两套实现。**

| 维度 | `opencode run` / TUI | `opencode acp` |
|---|---|---|
| 通信 | stdout 纯文本 / TUI 渲染 | JSON-RPC 2.0 over stdio |
| thinking | TUI 中显示，`run` 不显示 | **实时流式推送**（`agent_thought_chunk`） |
| 完成信号 | 进程退出 / TUI 停止 | `session/prompt` response（⚠️ 可能不返回）或通知流停止 |
| 权限 | `opencode.json` permission 配置 | 同配置，ACP 模式下自动按配置批准 |
| trajectory | 内部存储 | `session/update` 通知实时推送 |
| 状态检测 | 无程序化信号 | 精确信号（thought/message/tool_call） |

**何时用 ACP**：需要实时检测 AI 工作状态、需要实时 trajectory 采集、需要被编辑器（Zed/JetBrains/Neovim）驱动。

**何时用 `opencode run`**：只需要最终结果、简单的一次性任务、不需要实时监控。

## 一、启动 ACP server

```bash
opencode acp                          # 启动为 ACP server（stdio 传输）
opencode acp --cwd /path/to/project   # 指定工作目录（默认 process.cwd()）
```

**环境变量**：
- `OPENCODE_CLIENT=acp`——opencode 内部设置，标识 ACP 模式
- `OPENCODE_ENABLE_QUESTION_TOOL=1`——启用 QuestionTool（默认 ACP 排除）

**认证**：ACP server 从 `~/.local/share/opencode/auth.json` 读取 provider 凭证。模型通过 `opencode.json` 的 `provider` 配置指定。

**内部架构**（与 Devin 不同）：OpenCode ACP 不是薄层——它在同一进程内启动完整的 OpenCode runtime（HTTP server + 工具注册表 + 文件系统 + shell），通过 localhost HTTP 与自己通信，然后在 stdio 上暴露 JSON-RPC façade。内置工具（read/write/edit/bash/grep/glob/webfetch）在 agent 进程的本地文件系统/shell 上执行。

## 二、协议版本——v1

OpenCode ACP 使用 **ACP v1 协议**（`initialize` response 返回 `protocolVersion: 1`）。

`initialize` response 的 `agentCapabilities`：

```json
{
  "loadSession": true,
  "mcpCapabilities": {"http": true, "sse": true},
  "promptCapabilities": {"embeddedContext": true, "image": true},
  "sessionCapabilities": {
    "close": {},
    "fork": {},
    "list": {},
    "resume": {}
  }
}
```

**`agentInfo`**：`{"name": "OpenCode", "version": "1.18.19"}`

**sessionCapabilities 比 Devin CLI 更完整**——Devin 只有 `list` / `delete` / `additionalDirectories`，OpenCode 有 `close` / `fork` / `list` / `resume`。

## 三、通信流程

### 3.1 完整流程

```
Client → Agent: initialize              # 协商协议版本和能力
Agent → Client: initialize response     # protocolVersion=1 + agentCapabilities
Client → Agent: session/new             # 创建新 session（需 mcpServers 字段）
Agent → Client: session/new response    # 返回 sessionId（如 "ses_fdb783a14ffelmiTKfnyqvAizS"）
Agent → Client: session/update          # available_commands_update 等元信息
Client → Agent: session/prompt          # 发送用户消息
Agent → Client: session/update (多个)   # 实时推送 thought/message/tool_call
Agent → Client: session/prompt response # ⚠️ 可能不返回——见 §六
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

### 3.3 session/new

**v1 必须带 `mcpServers` 字段**（空数组也行）。

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

Response 返回 `sessionId`（如 `"ses_fdb783a14ffelmiTKfnyqvAizS"`——OpenCode 用 `ses_` 前缀 +随机字符串）。

### 3.4 session/prompt

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/prompt",
  "params": {
    "sessionId": "ses_fdb783a14ffelmiTKfnyqvAizS",
    "prompt": [
      {
        "type": "text",
        "text": "Write 'hello' to /tmp/test.txt, then read it back."
      }
    ]
  }
}
```

**⚠️ 重要差异**：OpenCode ACP 的 `session/prompt` **可能不返回 response**。在实测中，简单问答和工具调用任务都没有收到 `session/prompt` response（id=3）。这与 Devin CLI ACP 不同——Devin 的 `session/prompt` 是严格的 request-response，处理完后返回 `{stopReason: "end_turn"}`。

**完成检测替代方案**：见 §六。

### 3.5 session/cancel

```json
{
  "jsonrpc": "2.0",
  "method": "session/cancel",
  "params": {
    "sessionId": "ses_fdb783a14ffelmiTKfnyqvAizS"
  }
}
```

### 3.6 session/close（OpenCode 独有，Devin 不支持）

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "session/close",
  "params": {
    "sessionId": "ses_fdb783a14ffelmiTKfnyqvAizS"
  }
}
```

### 3.7 session/list / session/resume / session/fork（OpenCode 独有）

OpenCode 支持 `session/list`（列出所有 session）、`session/resume`（恢复已存在 session）、`session/fork`（从现有 session 分叉）。Devin CLI 不支持这些。

OpenCode 1.18.21 的精确 resume 请求是：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/resume",
  "params": {
    "cwd": "/absolute/original/workdir",
    "sessionId": "ses_...",
    "mcpServers": []
  }
}
```

Response 返回该 Session 当前 `configOptions`；随后仍须校验 exact model，再发送新的 `session/prompt`。
同版本官方测试证明 resume 本身不 replay user/agent message chunks。2026-08-26 math-manify 真实恢复两个
被错误 cancel 的 Z.AI/OpenCode Session，Session ID 与 cwd 均保持，证明 cancel 后不应先假定上下文不可恢复。
业务系统仍拥有 resume 合法性、Round/attempt、资产和停止语义；ACP adapter 不擅自决定是否续跑。

### 3.8 模型选择与思考强度——session/set_config_option（2026-08-21 实测，管线必用）

**⚠️ 默认模型陷阱（U1 冒烟实证）**：不显式选模型时，ACP session 落到 opencode
内建默认 **`opencode/big-pickle`**——opencode.json 里配了 openrouter/ox-alpha 也
不会自动用！037 只配了 provider 没钉默认模型，任何依赖"配置即生效"的假设都是错的。

**正确姿势——session/new 之后立即两步设置并验证**：

```jsonc
// 第 1 步：换模型。方法名是 set_config_option（SDK 0.16.1；dev 最新源码已改名
// session/set_config——客户端应对两者做兼容探测）
→ {"jsonrpc":"2.0","id":N,"method":"session/set_config_option",
   "params":{"sessionId":"...","configId":"model","value":"openrouter/stealth/ox-alpha"}}
← 响应回显 {"configOptions":[{"id":"model","currentValue":"openrouter/stealth/ox-alpha",...}, ...]}

// 验证方法（问题 2 的答案）：断言响应回显的 currentValue == 你设的值。
// 这就是"确认 OpenCode 确实接受"的唯一可靠通道——不接受时会回显旧值或报错。

// 第 2 步：思考强度。切模型后 configOptions 会【新增 "effort" 项】——
// 该项只在所选模型声明了 variants 时出现（variants 来自 models.dev 的
// reasoning_options 元数据）。
→ {"method":"session/set_config_option",
   "params":{"sessionId":"...","configId":"effort","value":"max"}}
← 回显 currentValue="max"
```

**ox-alpha 实测数据**：variants = `["low", "high", "max"]`，**默认 "low"**——
不设 effort 就是 low 强度思考！管线代码（V1）必须在 session/new 后：
set model → 断言回显 → 读 effort 项 → 设目标强度 → 断言回显。

**探针脚本**：`scripts/probe_acp_model_config.py`（可重跑复验）；
原始数据 `tmp/wp_probe_model.jsonl`。

## 四、session/update 通知——核心信号

### 4.1 通知变体全览（实测验证）

| `sessionUpdate` 值 | 含义 | 实测验证 |
|---|---|---|
| `agent_thought_chunk` | **thinking 内容流式更新** | ✅ 实测: 823个（工具调用任务） |
| `agent_message_chunk` | message 内容流式更新 | ✅ 实测: 378个 |
| `tool_call` | **工具调用创建**（含 kind/title/status） | ✅ 实测: 3个 (edit+read+read) |
| `tool_call_update` | **工具状态更新** | ✅ 实测: 6个 (pending→in_progress→completed) |
| `available_commands_update` | 可用命令 | ✅ 实测: 1个 |

### 4.2 agent_thought_chunk——thinking 实时流式推送

格式与 Devin ACP 相同：

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "ses_fdb783a14ffelmiTKfnyqvAizS",
    "update": {
      "sessionUpdate": "agent_thought_chunk",
      "messageId": "msg_thought_a12",
      "content": {
        "type": "text",
        "text": "The user asks"
      }
    }
  }
}
```

**实测数据**（工具调用任务）：
- 823 个 thought_chunk
- 内容覆盖：任务理解 → 工具选择 → 执行计划 → 结果分析 → 总结生成
- thinking 期间持续推送，拼接后得到完整 thinking 内容

**注意**：OpenCode 的 thinking 内容比 Devin 更丰富——不仅包含任务推理，还包含"总结生成"的 thinking（如生成结构化摘要时的思考过程）。

### 4.3 tool_call——工具调用创建

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "ses_fdb783a14ffelmiTKfnyqvAizS",
    "update": {
      "sessionUpdate": "tool_call",
      "toolCallId": "call_001",
      "title": "write",
      "kind": "edit",
      "status": "pending"
    }
  }
}
```

`kind` 枚举：`read` / `edit` / `delete` / `move` / `search` / `execute` / `think` / `fetch` / `other`

**实测工具调用序列**（文件写入+读取任务）：
```
TOOL_CALL: kind=edit status=pending title='write'
TOOL_UPDATE: status=in_progress
TOOL_UPDATE: status=completed
TOOL_CALL: kind=read status=pending title='read'
TOOL_UPDATE: status=in_progress
TOOL_UPDATE: status=completed
```

### 4.4 自定义通知

**实测未观察到** `_cognition.ai/*` 或其他自定义通知。这与 Devin CLI 不同——Devin 发送 `_cognition.ai/thinking_complete` 和 `_cognition.ai/agent_stopped`。

OpenCode 的 thinking 结束需要靠观察通知流——最后一个 `agent_thought_chunk` 之后开始出现 `agent_message_chunk` 或 `tool_call`，即表示 thinking 结束。

## 五、权限处理——OpenCode 的关键差异

### 5.1 自动批准机制

OpenCode 的权限通过 `opencode.json` 的 `permission` 配置：

```json
{
  "permission": {
    "*": "allow",
    "bash": {
      "*": "allow",
      "git push*": "deny",
      "gh *": "deny"
    }
  }
}
```

**关键差异**：OpenCode 在 ACP 模式下**按配置自动批准**，不发送 `session/request_permission` 请求。实测中工具调用任务（写文件+读文件）权限请求数为 0——全部自动批准。

Devin CLI ACP 对每个需要权限的工具调用都发送 `session/request_permission`，需要 client 手动回复。

### 5.2 如需精细权限控制

配置 `"ask"` 模式，OpenCode 会发送 `session/request_permission`，client 需要回复（格式与 Devin 相同）：

```json
{
  "jsonrpc": "2.0",
  "id": "请求的id",
  "result": {
    "outcome": {
      "outcome": "selected",
      "optionId": "allow_once"
    }
  }
}
```

## 六、完成检测——OpenCode 的关键差异

### 6.1 问题

OpenCode ACP 的 `session/prompt` **可能不返回 response**。实测中：
- 简单问答（2+2）：未收到 prompt response
- 工具调用任务（写文件+读文件）：未收到 prompt response

Devin CLI ACP 的 `session/prompt` 是严格的 request-response，处理完后返回 `{stopReason: "end_turn", usage: {...}}`。

### 6.2 替代完成检测方案

**方案A：通知流静默检测**（推荐）
- 设定静默窗口（如 30 秒无任何 `session/update` 通知）
- 最后一个通知后 30 秒无新通知 = 认为 prompt 处理完成

**方案B：主动 cancel**
- 设定 max_runtime，超时后发 `session/cancel`

**推荐**：方案A + 方案B 组合。

### 6.3 thinking spin 检测逻辑

与 Devin ACP 类似，但需注意 OpenCode 不发 `_cognition.ai/thinking_complete`：

```
检测窗口：5 分钟

条件：session/prompt 已发送
  且 5 分钟内无任何以下信号：
    - agent_thought_chunk（thinking 中）
    - agent_message_chunk（message 输出中）
    - tool_call / tool_call_update（工具调用中）
    - session/request_permission（等待权限中）
  = 疑似卡住 → 创建 alert
```

## 七、与 Devin CLI ACP 的完整对比

| 维度 | OpenCode ACP | Devin CLI ACP |
|---|---|---|
| **协议版本** | v1 | v1 |
| **启动命令** | `opencode acp --cwd <dir>` | `devin acp --model <model>` |
| **模型指定** | `opencode.json` provider 配置 | `--model` 命令行参数 |
| **认证** | `~/.local/share/opencode/auth.json` | `WINDSURF_API_KEY` 或 `devin auth login` |
| **内部架构** | 完整 runtime（HTTP server + 工具 + shell） | 轻量 agent（依赖 devin 后端） |
| **session/new** | 需 `mcpServers` 字段 | 需 `mcpServers` 字段 |
| **sessionId 格式** | `ses_<random>` | `<english-words>` (如 "curved-flannel") |
| **session/prompt response** | ⚠️ **可能不返回** stopReason | ✅ 返回 `{stopReason, usage}` |
| **完成检测** | 通知流静默检测 | `session/prompt` response |
| **session/close** | ✅ 支持 | ❌ 不支持（用 cancel + 进程终止） |
| **session/fork** | ✅ 支持 | ❌ 不支持 |
| **session/list** | ✅ 支持 | ✅ 支持 |
| **session/resume** | ✅ 支持 | ❌ 不支持（只有 load） |
| **session/load** | ✅ 支持（replay 历史） | ✅ 支持（replay 历史） |
| **agent_thought_chunk** | ✅ 实测 823个 | ✅ 实测 22个 |
| **agent_message_chunk** | ✅ 实测 378个 | ✅ 实测 754个 |
| **tool_call** | ✅ 实测 3个 | ✅ 实测 2个 |
| **tool_call_update** | ✅ 实测 6个 | ✅ 实测 6个 |
| **权限处理** | 配置 `allow` 后**自动批准**，不发请求 | 每次发 `session/request_permission`，需手动回复 |
| **自定义通知** | 未观察到 | `_cognition.ai/thinking_complete` / `_cognition.ai/agent_stopped` |
| **thinking 结束标记** | 无显式标记（靠观察通知流转变） | `_cognition.ai/thinking_complete` |
| **agent 停止标记** | 无显式标记 | `_cognition.ai/agent_stopped` |
| **AGENTS.md 支持** | ✅ 自动加载项目 AGENTS.md | ✅ 自动加载项目 AGENTS.md |
| **MCP 支持** | ✅ `mcpServers` 配置 | ✅ `mcpServers` 配置 |
| **工具集** | read/write/edit/bash/grep/glob/webfetch | read/edit/exec/grep/glob/web_search/webfetch/... |

### 关键差异详解

**1. session/prompt response——最大的行为差异**

Devin CLI：`session/prompt` 是严格的 request-response。Agent 处理完 prompt 后返回 `{stopReason: "end_turn", usage: {...}}`。Client 等待这个 response 就知道完成了。

OpenCode：`session/prompt` 可能不返回 response。Agent 处理完 prompt 后继续运行（可能在做总结、等待下一个 prompt）。Client 需要用通知流静默检测来判断完成。

**影响**：写 ACP 客户端时，不能依赖 `session/prompt` response 作为完成信号。需要实现静默检测逻辑。

**2. 权限处理——OpenCode 更简单**

Devin CLI：每个需要权限的工具调用都发 `session/request_permission`，client 必须回复。不回复 = Agent 卡住。

OpenCode：按 `opencode.json` 的 `permission` 配置自动批准。配置 `"*": "allow"` 后，所有工具调用自动批准，不发 `session/request_permission`。只有配置 `"ask"` 时才发请求。

**影响**：OpenCode ACP 客户端的权限处理更简单——配置好 `allow` 就不用管了。Devin ACP 客户端必须实现权限响应逻辑。

**3. session 管理——OpenCode 更完整**

Devin CLI：只有 `session/new` / `session/load` / `session/list` / `session/cancel`。没有 `close` / `fork` / `resume`。

OpenCode：有 `session/new` / `session/load` / `session/list` / `session/close` / `session/fork` / `session/resume` / `session/cancel`。

**影响**：OpenCode 的 session 管理更灵活——可以 fork session、resume session、close session。Devin 只能 cancel + 进程终止。

**4. 自定义通知——Devin 有显式标记**

Devin CLI：发送 `_cognition.ai/thinking_complete`（thinking 结束）和 `_cognition.ai/agent_stopped`（agent 停止）。

OpenCode：未观察到自定义通知。thinking 结束和 agent 停止需要靠观察通知流转变推断。

**影响**：Devin 的 thinking spin 检测更精确——有显式的 `thinking_complete` 标记。OpenCode 需要靠"最后一个 thought_chunk 后开始出现 message_chunk 或 tool_call"来推断。

## 八、模型配置——OpenRouter + Ox Alpha

### 8.1 opencode.json 配置

```json
{
  "provider": {
    "openrouter": {
      "models": {
        "stealth/ox-alpha": {
          "name": "Ox Alpha (GLM stealth, 1M context, free)",
          "attachment": true,
          "reasoning": true,
          "limit": {
            "context": 1048576,
            "output": 131072
          },
          "modalities": {
            "input": ["text", "image", "video"],
            "output": ["text"]
          },
          "options": {
            "reasoning": {
              "effort": "high"
            }
          }
        }
      }
    }
  }
}
```

### 8.2 auth.json 配置

`~/.local/share/opencode/auth.json`：

```json
{
  "openrouter": {
    "type": "api",
    "key": "sk-or-v1-your-key"
  }
}
```

### 8.3 使用

```bash
# 非交互
opencode run --model openrouter/stealth/ox-alpha "your prompt"

# ACP 模式
opencode acp --cwd /path/to/project
```

### 8.4 Ox Alpha 实测结论

- **完全免费**：pricing prompt=0 completion=0
- **无限量**：20 次连续请求全部成功，零限速（账户 is_free_tier=false）
- **1M 上下文**：1048576 tokens
- **131K 最大输出**
- **支持 reasoning**：thinking 内容通过 `agent_thought_chunk` 实时推送
- **支持 tool calling**
- **多模态**：text + image + video 输入

## 九、trajectory 组装与导出

> **2026-08-21 实测纠正**：本节初版写"OpenCode ACP 没有直接的 trajectory 导出功能"——
> **这个说法是错的**。OpenCode 有原生 export 命令，且 ACP 创建的 session 同样落盘可导出
> （本机 v1.18.20 实测验证，见 9.3）。

### 9.1 通知流自行组装（实时，主来源）

维护一个按 `messageId` 索引的消息列表，处理 chunk：

```python
messages = {}  # messageId -> {role, content_parts}
tool_calls = []  # [{id, kind, status, title}]

# agent_thought_chunk → messages[mid] = {"role": "thought", "content": [...]}
# agent_message_chunk → messages[mid] = {"role": "assistant", "content": [...]}
# tool_call → tool_calls.append({...})
# tool_call_update → 更新对应 tool_call 状态
```

**建议实时落盘**（每收到 chunk 追加写入 jsonl），避免进程崩溃丢失数据。

### 9.2 原生 export 机制（官方命令，实测可用）

```bash
opencode export [sessionID]    # 导出 session 为 JSON（--sanitize 可脱敏）
opencode import <file>         # 反向导入（本地文件或 opncd.ai 分享链接）
opencode session list          # 列出全部 session
opencode session delete <id>   # 删除 session
```

存储机制：全部 session 持久化在全局 SQLite `~/.local/share/opencode/opencode.db`
（表：`session`/`message`/`part` 等；历史上曾是 JSON 文件存储后迁移）。`storage/`
目录只有辅助元数据，不是消息本体。

**★ ACP 创建的 session 与 TUI/run 创建的在存储层完全同构**——ACP 只是前端，
落盘走同一条路。实测：本机 037 调研时的 ACP 测试 session（`Calculating 1+1`，
模型 stealth/ox-alpha）用 `opencode export ses_fdb78f223ffeOl1e57eWRaJpYI` 成功
导出完整内容（prompt/回复/finish reason/token 计数）。

### 9.3 export 格式结构（比 Devin conversation.json 更丰富）

```json
{
  "info": { "id", "model", "tokens": {"input","output","reasoning","cache"} },
  "messages": [
    { "info": {"role", "tokens": {...}},
      "parts": [
        {"type": "step-start"},
        {"type": "reasoning", "text": "思考实文"},
        {"type": "text", "text": "正式回复"},
        {"type": "tool", ...},
        {"type": "step-finish", "reason": "stop|tool-calls|unknown",
         "tokens": {"input","output","reasoning","cache"}}
      ]}
  ]
}
```

关键点：`reasoning` part 含 thinking 实文（devin export 的 rc 等价物）；
逐消息 token 计数；`step-finish.reason` 是结构化收尾原因。

#### OpenCode 1.18.21 L1/L2实际shape（2026-08-27）

真实native ACP/export补充了旧示例没有冻结的三项合同：

- 控制器发送的完整task落在`messages[].info.role="user"`的`parts[].type="text"`正文中；它是L1原始
  context，不得因为不是system/developer role就判`missing`，但仍须保留role provenance；
- read调用使用`parts[].type="tool"`、`tool="read"`、`state.input.filePath`；结果位于
  `state.output`，以`<path>...`、`<type>file</type>`、`<content>...`包裹，实际可见源码行采用`N: `前缀；
- offset/limit读取只证明返回的exact visible ranges。Parser忽略wrapper行、按call ID与source逐行对账，
  未返回的尾行、gap/conflict/mismatch不得用metadata、path mention或模型EOF自述补成full。

`opencode export --sanitize`会脱敏prompt/tool内容，适合安全结构/计数对账，但不能替代L1/L2 exact compare；
后者使用0700目录内的0600 raw export或等价DB/wire。2026-08-27 a3直接证据：raw export 171 events、49
tool calls/45 results；shared旧reader的L1 missing与L2 unparsed均为false negative。修复必须先加入真实shape
fixture并跑完shared tests，再同步`CAP-TRAJ-MULTIHOST`/OpenCode Skill；fresh V5前不得晋升CURRENT conformance。

### 9.4 三层 trajectory 来源结论（OpenCode 管线）

| 层 | 来源 | 用途 |
|---|---|---|
| 1 | 自身通知捕获 jsonl（实时写） | **主来源**——实时、自主可控 |
| 2 | `opencode export <sessionID>` | **兜底首选**——进程崩溃后仍可从 SQLite 捞回完整轨迹（含 thinking） |
| 3 | 直读 opencode.db SQLite | 能做但耦合其 schema，脆弱，不作主路径 |

### 9.5 待验证未知项（WP-U2 实验靶）

1. **截断信号**：撞 output 上限时 `step-finish.reason` 是否出现显式值
   （如 max-tokens）？实测只见过 stop/tool-calls/unknown——这决定"协议原生
   截断检测"是否成立（主信号）还是必须靠结构启发式（兜底）
2. **落盘时机**：SQLite 是运行中增量写还是结束时批量写？——决定进程崩溃后
   export 能捞回多少

## 十、参考客户端代码

最小 ACP 客户端（Python，约 80 行）：

```python
import subprocess, json, select, time

def send(proc, msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()

def read_line(proc, timeout=10):
    r, _, _ = select.select([proc.stdout], [], [], timeout)
    if r:
        line = proc.stdout.readline()
        if line:
            return json.loads(line.decode())
    return None

proc = subprocess.Popen(
    ["opencode", "acp", "--cwd", "/tmp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
)

# initialize
send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": 1, "clientCapabilities": {}}})
resp = read_line(proc, 15)
print(f"init: {resp.get('result',{}).get('protocolVersion')}")

# session/new
send(proc, {"jsonrpc": "2.0", "id": 2, "method": "session/new",
            "params": {"cwd": "/tmp", "mcpServers": []}})
resp = read_line(proc, 10)
sid = resp["result"]["sessionId"]

# session/prompt
send(proc, {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
            "params": {"sessionId": sid,
                       "prompt": [{"type": "text", "text": "your prompt here"}]}})

# 收集通知（静默 30 秒 = 完成）
for _ in range(1000):
    resp = read_line(proc, 30)
    if not resp:
        break  # 静默 30 秒 = 完成
    if resp.get("id") == 3:
        print(f"PROMPT RESPONSE: {resp['result']}")
        break
    update = resp.get("params", {}).get("update", {})
    su = update.get("sessionUpdate", "")
    if su:
        # 处理各种通知...
        pass

proc.terminate()
```

## 十一、常见问题

### Q: session/prompt 一直不返回 response
**A**: 这是 OpenCode ACP 的已知行为。用通知流静默检测（30 秒无新通知 = 完成）或设定 max_runtime + cancel。

### Q: session/new 报 "missing field mcpServers"
**A**: v1 协议要求 `mcpServers` 字段，传空数组 `"mcpServers": []`。

### Q: 工具调用没有权限请求
**A**: OpenCode 按 `opencode.json` 的 `permission` 配置自动批准。配置 `"*": "allow"` 后所有工具调用自动批准。如需权限请求，配置 `"ask"`。

### Q: 收不到 agent_thought_chunk
**A**: 简单问题可能不触发 thinking。用需要推理的任务测试。OpenCode 的 thinking 内容通常比 Devin 更丰富（包含总结生成的 thinking）。

### Q: 如何指定模型
**A**: 在 `opencode.json` 的 `provider` 中配置模型，或在 TUI 中用 `/models` 选择。ACP 模式下模型由配置决定。

## 十二、参考文档

- OpenCode ACP 文档：https://opencode.ai/docs/acp/
- OpenCode ACP 源码：https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/
- OpenCode ACP 实现说明：https://github.com/TencentCloudBase/OpenVibeCoding/blob/main/docs/opencode-acp-integration-memo.md
- ACP 协议 v1 概览：https://agentclientprotocol.com/protocol/v1/overview
- ACP 协议 v1 Prompt Turn：https://agentclientprotocol.com/protocol/v1/prompt-turn
- ACP 协议 v1 Session Setup：https://agentclientprotocol.com/protocol/v1/session-setup
- ACP 协议 v1 Tool Calls：https://agentclientprotocol.com/protocol/v1/tool-calls
- Zed 集成 OpenCode ACP：https://opencode.ai/docs/acp/#zed
- JetBrains 集成 OpenCode ACP：https://opencode.ai/docs/acp/#jetbrains-ides
