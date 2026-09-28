---
name: devin-cli-trajectory
description: >
  Devin CLI trajectory 数据的完整存储位置、格式、读取方法。
  Transcript（ATIF格式）、sessions.db（SQLite）、logs、summaries、--export参数。
  WHEN to use: 需要提取/解析/审计Devin CLI的session对话数据时。
  WHEN NOT to use: 一般编码任务、非Devin CLI相关的数据工作。
---

# devin-cli-trajectory skill

## 配套递归审计脚本（当前首选）

`/Users/user/skills-devin/scripts/devin_traj.py` 是本 Skill 的确定性多层读取器：只读打开
`sessions.db`，沿 `main_chain_id -> parent_node_id` 恢复 active chain，同时递归遍历完整 forest，避免
分支、重复 main chain 和 compaction 祖先被线性化。默认命令不打印 private content；raw export 只写
0700/0600 私有目录。

```bash
D=/Users/user/skills-devin/scripts/devin_traj.py
python3 "$D" sessions --limit 20
python3 "$D" summary SESSION_ID
python3 "$D" tree SESSION_ID
python3 "$D" audit-injection SESSION_ID /absolute/AGENTS.md --output /private/injection.json
python3 "$D" audit-reads SESSION_ID /absolute/expected-file --output /private/reads.json
python3 "$D" compare-recall /private/raw-context.txt /private/model-recall.txt
python3 "$D" export SESSION_ID /private/export-dir
```

离机审计不需要把bundle重新导入全局DB。Canonical export目录可直接交给共享reader：

```bash
T=/Users/user/codex/tools/session_trajectory.py
python3 "$T" tree --host devin --source /archive/session-db-full \
  --session SESSION_ID --recursive
python3 "$T" scan --host devin --source /archive/session-db-full \
  --session SESSION_ID --recursive
python3 "$T" context --host devin --source /archive/session-db-full \
  --session SESSION_ID --recursive --section system --output /private/system.txt
```

目录source必须含`session.json`以及`nodes.jsonl`/`active-main-chain.jsonl`。默认读取active chain，
`--recursive`读取full forest；locator保留原JSONL行号。此路径不得回退读取`~/.local/share/devin`，因此
可以用来证明D盘bundle离开原机器仍可审计。ACP未提交thinking仍需同Round pre-close raw补足，DB bundle
可读不等于它包含Host从未持久化的spin。Devin 3000.6.2实物中`chat_message.thinking`可能是字符串，也可能
是`{"thinking":"...","signature":"..."}`对象；共享reader提取正文但不打印signature。

共享四 Host 入口是 `/Users/user/codex/tools/session_trajectory.py`；本脚本承担 Devin-specific
forest/Cogs/private export 深入适配。Raw context injection、selected read、model recall、cognition
execution、final behavior 必须分别判定，模型复述不能替代前两层。

## 用途

Devin CLI 自动保存所有 session 的 trajectory 数据。本 skill 说明存储位置、格式结构、读取方法，供数据提取、审计、持久化设计使用。

## 存储位置总览

所有数据在 `~/.local/share/devin/cli/` 下：

```
~/.local/share/devin/cli/
├── transcripts/          # ATIF格式JSON，每个session一个文件
├── sessions.db           # SQLite，session元数据
├── sessions.db-wal       # SQLite WAL文件
├── summaries/            # 压缩历史（Markdown）
├── logs/                 # 运行日志
├── session_locks/        # session锁文件
├── trusted_workspaces.json
└── plugins/
```

## 1. Transcripts（ATIF格式JSON）

**位置**：`~/.local/share/devin/cli/transcripts/<session_name>.json`

**生成时机**：session 结束后写入（session 运行中不生成 transcript 文件）。

**ATIF格式结构**（schema_version: ATIF-v1.7）：

```json
{
  "schema_version": "ATIF-v1.7",
  "session_id": "<session_name>",
  "agent": {
    "name": "devin",
    "version": "3000.3.27",
    "model_name": "GLM-5.2",
    "tool_definitions": [],
    "extra": {
      "backend": "Windsurf",
      "permission_mode": "Normal"
    }
  },
  "steps": [
    {
      "step_id": 1,
      "timestamp": "...",
      "source": "system",    // system / user / agent
      "message": "...",       // 字符串或对象
      "extra": {
        "telemetry": {...},
        "generation_model": "glm-5-2"  // 仅agent steps
      }
    },
    ...
  ],
  "final_metrics": {
    "total_prompt_tokens": 39037,
    "total_completion_tokens": 10322,
    "total_cached_tokens": 20702,
    "total_steps": 9
  }
}
```

**Step source 类型**：
- `system`：系统消息（AGENTS.md内容、available_skills、system_info等）
- `user`：用户输入
- `agent`：AI回复（含 generation_model 和 telemetry）

**读取transcript的Python代码**：

```python
import json

with open(f"~/.local/share/devin/cli/transcripts/{session_name}.json") as f:
    data = json.load(f)

# 获取所有user和agent的对话
for step in data["steps"]:
    if step["source"] in ("user", "agent"):
        print(f"[{step['source']}] {step['message'][:200]}")

# 获取token统计
metrics = data["final_metrics"]
print(f"Prompt tokens: {metrics['total_prompt_tokens']}")
print(f"Completion tokens: {metrics['total_completion_tokens']}")
```

## 2. sessions.db（SQLite）

**位置**：`~/.local/share/devin/cli/sessions.db`

**特点**：实时更新（session 运行中也有记录），是 session 元数据的权威来源。

**Schema**：

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,           -- session名称（如"typical-agenda"）
  working_directory TEXT NOT NULL,
  backend_type TEXT NOT NULL,
  model TEXT NOT NULL,
  agent_mode TEXT NOT NULL,
  created_at INTEGER NOT NULL,   -- Unix时间戳
  last_activity_at INTEGER NOT NULL,
  title TEXT,                    -- 首条用户消息（截断）
  main_chain_id INTEGER,
  shell_last_seen_index INTEGER DEFAULT 0,
  cogs_json TEXT,
  workspace_dirs TEXT,
  hidden INTEGER NOT NULL DEFAULT 0,
  metadata TEXT
);
```

**常用查询**：

```bash
# 列出最近10个session
sqlite3 ~/.local/share/devin/cli/sessions.db \
  "SELECT id, working_directory, model, created_at FROM sessions ORDER BY created_at DESC LIMIT 10;"

# 查找特定工作目录的session
sqlite3 ~/.local/share/devin/cli/sessions.db \
  "SELECT id, created_at, last_activity_at FROM sessions WHERE working_directory = '/Volumes/data/math-agent-glm5.2-1' ORDER BY created_at DESC;"

# 查找未隐藏的session
sqlite3 ~/.local/share/devin/cli/sessions.db \
  "SELECT id, model, title FROM sessions WHERE hidden = 0 ORDER BY last_activity_at DESC LIMIT 20;"
```

**关联 transcript**：sessions.db 的 `id` 字段 = transcript 文件名（不含 `.json`）。

## 3. --export 参数

**功能**：将对话导出到指定文件（ATIF格式），每轮对话后自动导出。

**用法**：

```bash
# 导出到指定路径
devin --export out.json -- fix tests

# 导出到默认路径
devin --export -- fix tests

# 交互式模式带export
devin --export /path/to/session.json
```

**与自动 transcript 的关系**：
- 自动 transcript：session 结束后写入 `~/.local/share/devin/cli/transcripts/`
- `--export`：每轮对话后写入指定路径（实时写入）
- 两者格式相同（ATIF），但 `--export` 可以在 session 运行中获取实时数据

**注意**：`--export` 的路径必须是绝对路径或相对于 cwd 的路径。如果路径不可写，export 静默失败（不报错但不生成文件）。

**/export 命令**：在交互式 session 中输入 `/export` 可查看 export 信息。

## 4. Summaries（压缩历史）

**位置**：`~/.local/share/devin/cli/summaries/history_<session_hash>.md`

**内容**：session 压缩时生成的 Markdown 格式历史摘要。

**用途**：跨压缩边界恢复认知。当 session 被 `/compact` 压缩后，压缩前的完整对话保存在这里。

## 5. Logs（运行日志）

**位置**：`~/.local/share/devin/cli/logs/devin_<timestamp>_<pid>.log`

**内容**：Rust 后端的运行日志（chisel），包含模型解析、session 管理、工具调用等详细信息。

**用途**：调试 devin cli 行为、排查 session 启动失败、追踪工具调用链。

## 6. Session Locks

**位置**：`~/.local/share/devin/cli/session_locks/<session_name>.lock`

**内容**：session 锁文件，包含 PID。session 运行时存在，结束后删除。

**用途**：防止同一 session 被多个 devin cli 实例同时打开。

## 数据保留策略建议

1. **Transcript 是不可复现数据**——AI 非确定性，同样的 prompt 不会产生同样的回复。必须保留。
2. **sessions.db 是元数据**——可以重建，但保留有助于追溯。
3. **Summaries 是压缩历史**——跨压缩边界恢复认知的关键，必须保留。
4. **Logs 可以定期清理**——体积大但价值低（除非调试）。
5. **备份时**：至少备份 `transcripts/` + `sessions.db` + `summaries/`。

## 在引导实验中使用

在 guided-math-solving 元组群中，Skill 5（guided-data-persist）需要：

1. **session 结束后**：从 `~/.local/share/devin/cli/transcripts/<session_name>.json` 读取完整 transcript
2. **session 运行中**：用 `--export` 或 pipe-pane 获取实时数据
3. **session 元数据**：从 sessions.db 查询 working_directory、model、created_at
4. **关联方式**：session_name = sessions.db.id = transcript 文件名（不含 .json）

```python
# 从sessions.db获取session_name
import sqlite3
conn = sqlite3.connect("~/.local/share/devin/cli/sessions.db")
cursor = conn.execute(
    "SELECT id FROM sessions WHERE working_directory = ? ORDER BY created_at DESC LIMIT 1",
    (work_dir,)
)
session_name = cursor.fetchone()[0]  # 如 "typical-agenda"

# 读取transcript
import json
with open(f"~/.local/share/devin/cli/transcripts/{session_name}.json") as f:
    transcript = json.load(f)
```

---

# Harness 采集的 Trajectory 目录结构

> 2026-08-15 调查，基于 50 题采样（10 个批次各 5 题），共 23911 个 trajectory 目录。
> 完整 Schema 文档：`analysis-devin-failure-system/docs/solver-trajectory-schema.md`

## 与 devin cli 自身存储的区别

- **devin cli 自身存储**（上文 1-6 章）：`~/.local/share/devin/cli/` 下的 transcripts/sessions.db/summaries/logs
- **harness 采集的 trajectory 目录**（本章）：solver_harness / analysis 系统运行 devin cli 时，通过 --export + tmux pipe + sessions_db 等手段采集的完整 trajectory

两者格式相同（ATIF-v1.7），但 harness 采集的数据更丰富——除了 export 的 conversation.json，还有 tmux pipe 的 TUI 输出、session_info.json 元数据等。

**mitmproxy已废弃（2026-08-18）**——不再用于trajectory采集。`--export`的conversation.json已包含`reasoning_content`（完整thinking），不需要MITM截获。历史MITM数据（`<exp_id>/mitm/`目录）仍可查阅，但不再产生新数据。

## 目录结构

```
{trajectory_base}/{exp_id}/
├── session_info.json              # 元数据（100%存在）
├── exports/
│   └── conversation.json          # ATIF格式export（58%存在）
├── sessions_db/
│   └── trajectory.jsonl           # SQLite导出的trajectory（82%存在）
├── mitm/                           # MITM截获数据（38%存在，仅早期批次）
│   ├── thinking_live.jsonl        # 实时thinking chunks
│   ├── thinking_live.txt          # 实时thinking文本
│   ├── thinking_readable.txt      # 可读格式thinking
│   └── trajectory.jsonl           # MITM解码的完整trajectory
└── tmux/
    ├── tmux_pipe.log              # tmux pipe-pane输出（90%存在）
    ├── tmux.log                   # tmux日志（90%存在）
    └── thinking_capture.txt       # thinking截获（部分后期批次，常为空）
```

## 文件存在率（50题采样）

| 文件 | 存在率 | 平均大小 |
|---|---|---|
| session_info.json | 100% | 1,095 B |
| exports/conversation.json | 58% | 154,795 B |
| sessions_db/trajectory.jsonl | 82% | 50,280 B |
| mitm/thinking_live.jsonl | 38% | 1,450,713 B |
| mitm/thinking_live.txt | 38% | 347,372 B |
| mitm/thinking_readable.txt | 38% | 30,168 B |
| mitm/trajectory.jsonl | 36% | 140,617 B |
| tmux/tmux_pipe.log | 90% | 741,975 B |
| tmux/tmux.log | 90% | 742,471 B |

**MITM 按批次分布**：早期批次（dpb-20260812-021956 到 041914）有 MITM，后期批次（063817 起）没有。session_info.json 的 `mitm_enabled` 字段为 True/False 各 50%。

## session_info.json Schema

```json
{
  "exp_id": "string — 实验ID",
  "model": "string — 如'glm-5-2'",
  "prompt": "string — 给AI的初始prompt",
  "problem_file": "string — 题目文件路径",
  "solver_dir": "string — 解题AI工作目录",
  "trajectory_dir": "string — trajectory目录",
  "tmux_session": "string — tmux session名",
  "mitm_port": "int — MITM端口",
  "mitm_enabled": "bool — 是否启用MITM",
  "devin_session_id": "string — Devin CLI session ID",
  "start_timestamp": "string — ISO格式",
  "status": "string — 如'stopped'",
  "interactive": "bool",
  "updated_at": "string — ISO格式"
}
```

## exports/conversation.json Schema

ATIF-v1.7 格式，与 devin cli 自身 transcript 相同，但 harness 采集的版本**多了 observation 字段**（tool_results）。

### 顶层结构

```json
{
  "schema_version": "ATIF-v1.7",
  "session_id": "string",
  "agent": {
    "name": "devin",
    "version": "3000.4.16",
    "model_name": "GLM-5.2 High",
    "tool_definitions": "list[29]",
    "extra": {"backend": "...", "permission_mode": "..."}
  },
  "steps": "list[Step]",
  "final_metrics": {
    "total_prompt_tokens": "int",
    "total_completion_tokens": "int",
    "total_cached_tokens": "int",
    "total_steps": "int"
  }
}
```

### agent step 完整结构（关键）

```json
{
  "step_id": "int",
  "timestamp": "string",
  "source": "agent",
  "message": "string — TUI输出",
  "model_name": "string — 如'glm-5-2'",
  "reasoning_content": "string — thinking内容（78%的agent step有）",
  "tool_calls": "list[ToolCall] — 工具调用（67%有）",
  "observation": {                    // ← tool_results的存储位置
    "results": [
      {
        "source_call_id": "string — 对应tool_call_id",
        "content": "string — 工具返回结果"
      }
    ]
  },
  "metrics": {
    "prompt_tokens": "int",
    "completion_tokens": "int",
    "cached_tokens": "int"
  },
  "extra": {
    "generation_model": "string",
    "telemetry": {"source": "assistant", "operation": "inference"}
  }
}
```

### ToolCall 结构

```json
{
  "tool_call_id": "string — 如'chatcmpl-tool-xxx'",
  "function_name": "string — exec/read/write/edit/get_output",
  "arguments": {
    "command": "string — 命令内容（exec）",
    "file_path": "string — 文件路径（read/write/edit）",
    "content": "string — 文件内容（write）",
    "shell_id": "string — shell ID（get_output）",
    "timeout": "int — 超时（get_output）"
  }
}
```

### 关键统计（89个agent step采样）

- **reasoning_content**：78%有，长度0-78128 chars，avg=11170
- **tool_calls**：67%有，每个agent step最多1个tool_call
- **observation**：67%有（有tool_call时才有），每个observation有1个result
- **observation.results[].content**：长度42-1542 chars，avg=417
- **function_name分布**：exec(32) > read(11) > write(10) > edit(4) > get_output(3)
- **steps数**：8-48，avg=10
- **agent_steps数**：1-43，avg=3（大部分题1轮thinking spin，少数多达43轮）

### ⚠️ 关键：observation 字段是 tool_results 的存储位置

**conversation.json 把 tool_results 放在 agent step 的 observation 字段中**，不在单独的 tool step 中。这与 sessions_db/trajectory.jsonl 不同。

## sessions_db/trajectory.jsonl Schema

SQLite 导出的 trajectory，82%存在。每行一个 JSON 对象。

```json
{
  "type": "step",
  "node_id": "int",
  "parent_node_id": "int",
  "role": "user/assistant/tool",
  "content": "string — 消息内容",
  "thinking": "string — thinking内容（assistant有）",
  "tool_calls": "list — 工具调用",
  "created_at": "int — Unix时间戳"
}
```

### (type, role) 分布

| (type, role) | 说明 |
|---|---|
| (step, user) | 用户输入 |
| (step, assistant) | AI回复（含thinking） |
| **(step, tool)** | **工具返回结果**——content字段是tool_result |

### ⚠️ 关键：tool 行是 tool_results 的替代来源

**sessions_db/trajectory.jsonl 把 tool_results 放在单独的 tool 行中**（role="tool"），content 字段是工具返回结果（105-1341 chars）。这与 conversation.json 的 observation 字段不同。

## mitm/ 文件 Schema

### thinking_live.jsonl（38%存在，流式thinking chunks）

每行一个JSON对象，有**3种type**：

**type=thinking_chunk**（流式thinking片段，占绝大多数）：
```json
{
  "timestamp": "string — ISO格式",
  "counter": "int — API调用计数器",
  "chunk_index": "int — chunk序号",
  "type": "thinking_chunk",
  "content": "string — thinking文本片段"
}
```

**type=tool_call_chunk**（工具调用片段）：
```json
{
  "timestamp": "string", "counter": "int", "type": "tool_call_chunk",
  "tool_call_id": "string", "name": "string — 工具名",
  "args_chunk": "string — 参数片段", "is_start": "bool"
}
```

**type=stream_complete**（一轮thinking完成时的汇总）：
```json
{
  "timestamp": "string", "counter": "int", "type": "stream_complete",
  "exp_id": "string", "thinking_full": "string — 完整thinking",
  "thinking_total_length": "int", "thinking_chunks": "int",
  "envelopes": "int", "elapsed_seconds": "float", "tool_calls": "list"
}
```

type分布（50题采样）：thinking_chunk=209859, tool_call_chunk=2841, stream_complete=36。

### thinking_readable.txt（38%存在，可读格式）

纯文本，含轮次标记：
```
============================================================
[02:22:50] === Thinking Round 1128 START ===
============================================================
Let me read the problem file.

--- [Tool Call: read] [02:22:50] ---

============================================================
[02:22:50] === Thinking Round 1128 END ===
  thinking: 29 chars, 7 chunks
  tool_calls: 1
  elapsed: 0.1s
============================================================
```

**特点**：有轮次标记 + tool_call记录，**但没有tool_call返回结果**。

### trajectory.jsonl（36%存在，MITM解码的完整trajectory）

```json
{
  "source_file": "string — 原始bin文件名",
  "session_id": "string — UUID",
  "matched_exp": "string — 匹配的exp_id",
  "decoded_at": "float",
  "total_messages": "int",
  "content_thinking": "string — 完整thinking内容",
  "content_chunks_count": "int",
  "tool_calls": "dict — key是tool_call_id，value是工具调用详情（非list）"
}
```

行数：3-33，avg=16。每行对应一个完整API响应。tool_calls是dict而非list——key是tool_call_id。

## 数据源对比与选择建议

| 数据源 | 完整性 | 存在率 | thinking | tool_calls | tool_results | 轮次标记 |
|---|---|---|---|---|---|---|
| conversation.json | ★★★★★ | 58% | ✅ reasoning_content | ✅ tool_calls | ✅ observation | ❌ |
| sessions_db/trajectory.jsonl | ★★★★ | 82% | ✅ thinking | ✅ tool_calls | ✅ tool行content | ❌ |
| mitm/thinking_readable.txt | ★★★ | 仅早期批次 | ✅ | ✅ 标记 | ❌ | ✅ |
| mitm/thinking_live.jsonl | ★★ | 仅早期批次 | ✅ chunks | ❌ | ❌ | ❌ |
| mitm/trajectory.jsonl | ★★★ | 仅早期批次 | ✅ content_thinking | ✅ | ❌ | ❌ |
| tmux/tmux_pipe.log | ★★ | 90% | ❌ TUI输出 | ❌ | ❌ | ❌ |

### ⚠️ MITM状态：批量解题不启用MITM

**batch_problem_runner.py 第931行硬编码传`--no-mitm`**——批量解题时MITM被关闭。

- **早期批次**（dpb-20260812-021956 到 041914）：手动单题运行或早期batch runner未硬编码`--no-mitm`，MITM数据存在
- **后期批次**（dpb-20260812-063817 起）：batch runner硬编码`--no-mitm`，**MITM数据不存在**
- **当前和未来的解题数据**：MITM不会存在，thinking数据只能从conversation.json和sessions_db/trajectory.jsonl获取

solver_harness.py本身支持MITM（`--no-mitm`参数，默认启用），但batch_problem_runner.py在批量运行时强制关闭。

### 推荐数据源优先级（提取thinking+tool_results）

1. **sessions_db/trajectory.jsonl** — 82%存在（thinking + tool_calls + tool行content），**当前和未来数据的主要来源**
2. **exports/conversation.json** — 58%存在（reasoning_content + tool_calls + observation），最完整但存在率低
3. **mitm/thinking_readable.txt** — 仅早期批次存在（有轮次标记但无tool_results），历史数据兜底
4. **tmux/tmux_pipe.log** — 90%存在（只有TUI输出无thinking），最后兜底

### 提取完整thinking+tool_results的代码模板

```python
import json
from pathlib import Path

def get_thinking_text(exp_id, traj_base):
    """从trajectory目录提取完整thinking+tool_calls+tool_results"""
    traj_dir = Path(traj_base) / exp_id

    # 优先级1: sessions_db/trajectory.jsonl（82%存在，含tool_results）
    path = traj_dir / "sessions_db" / "trajectory.jsonl"
    if path.exists():
        parts = []
        round_num = 0
        seen_thinking = set()
        with open(str(path)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                role = obj.get("role", "")
                thinking = obj.get("thinking", "")
                content = obj.get("content", "")
                tool_calls = obj.get("tool_calls", [])

                if role == "assistant":
                    if isinstance(thinking, str) and thinking.strip():
                        if thinking not in seen_thinking:
                            seen_thinking.add(thinking)
                            round_num += 1
                            parts.append(f"\n[Thinking Round {round_num}]\n{thinking}")
                    if isinstance(content, str) and content.strip():
                        parts.append(f"\n[Agent Output]: {content}")
                    for tc in (tool_calls or []):
                        name = tc.get("name", "?")
                        args = str(tc.get("arguments", ""))[:500]
                        parts.append(f"\n--- [Tool Call: {name}] ---\n  args: {args}")

                elif role == "tool":
                    if isinstance(content, str) and content.strip():
                        parts.append(f"\n--- [Tool Result] ---\n{content[:2000]}")

        if parts:
            return "\n".join(parts)

    # 优先级2: exports/conversation.json（58%存在，observation字段含tool_results）
    path = traj_dir / "exports" / "conversation.json"
    if path.exists():
        conv = json.loads(path.read_text())
        parts = []
        round_num = 0
        for step in conv.get("steps", []):
            if step.get("source") != "agent":
                continue
            rc = step.get("reasoning_content", "")
            msg = step.get("message", "")
            tc = step.get("tool_calls", [])
            obs = step.get("observation", {})

            if isinstance(rc, str) and rc.strip():
                round_num += 1
                parts.append(f"\n[Thinking Round {round_num}]\n{rc}")
            if isinstance(msg, str) and msg.strip():
                parts.append(f"\n[Agent Output]: {msg}")
            for call in (tc or []):
                name = call.get("function_name", "?")
                args = str(call.get("arguments", ""))[:500]
                parts.append(f"\n--- [Tool Call: {name}] ---\n  args: {args}")
            # observation是tool_results
            results = obs.get("results", []) if isinstance(obs, dict) else []
            for r in results:
                c = r.get("content", "")
                if c:
                    parts.append(f"\n--- [Tool Result] ---\n{c[:2000]}")

        if parts:
            return "\n".join(parts)

    # 优先级3: mitm/thinking_readable.txt（38%存在，有轮次标记但无tool_results）
    path = traj_dir / "mitm" / "thinking_readable.txt"
    if path.exists() and path.stat().st_size > 100:
        return path.read_text(encoding="utf-8", errors="replace")

    # 优先级4: tmux/tmux_pipe.log（90%存在，只有TUI输出）
    path = traj_dir / "tmux" / "tmux_pipe.log"
    if path.exists() and path.stat().st_size > 100:
        return path.read_text(encoding="utf-8", errors="replace")

    return None
```

## 常见陷阱

1. **MITM thinking_readable.txt 没有 tool_results**——只有 tool_call 记录（`--- [Tool Call: read] ---`），没有工具返回内容。如果需要 tool_results，必须用 conversation.json 的 observation 字段或 sessions_db/trajectory.jsonl 的 tool 行。
2. **conversation.json 的 tool_results 在 observation 字段中**——不在单独的 tool step 中，在 agent step 的 `observation.results[].content` 中。
3. **42%的题没有 conversation.json**——这些题只有 sessions_db/trajectory.jsonl 或 tmux 文件。
4. **reasoning_content 不是所有 agent step 都有**（78%）——有些 agent step 只有 tool_call 没有 thinking（如执行命令后的等待步骤）。
5. **MITM 文件只有早期批次存在**——后期批次（dpb-20260812-063817 起）没有 MITM，因为 mitm_enabled=False。
