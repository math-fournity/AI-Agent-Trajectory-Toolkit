---
name: oc-trajectory
description: >
  opencode ACP session trajectory 数据的存储位置、JSONL schema、层次化分析方法。
  覆盖 thoughts.jsonl 实时流格式、截断指纹识别（32000 output / end_turn 无标记）、
  多轮接力场景下的前轮工作翻查流程。
  WHEN to use: 你是续传接力的第N轮解题实例，需要分析之前轮次ACP的thinking流时；
  需要提取/审计 opencode ACP session 的推理内容时；需要判断上一轮是否被输出上限
  截断、最后思考停在哪里时；主控要求你写"分析笔记"需要翻查trajectory原文时。
  WHEN NOT to use: ZCode桌面客户端的trajectory（用 zcode-trajectory skill）；
  Devin CLI 的trajectory（用 devin-cli-trajectory skill）。
---

# oc-trajectory skill · opencode ACP trajectory 层次化分析

> 兼容身份：本 Skill 继续服务 math-manify 的 `thoughts.jsonl`/`thinking.md` reasoning stream。完整
> OpenCode Session/export/parts/children/wire 与四 Host L1-L5 审计改用
> `repo-agent-session-trajectory` 和 `/Users/user/codex/tools/session_trajectory.py`；本 Skill 不能
> 冒充完整 Session Trajectory。

OpenCode 1.18.21历史export把controller task放在role=user text part；native read使用
`state.input.filePath`与`N: `visible-line output。完整L1/L2审计必须由上述shared Skill/tool读取0600 raw
export，并先解析`CAP-TRAJ-MULTIHOST`/`CAP-TRAJ-OPENCODE`；本兼容脚本不解析这些结构。若实际shape使
shared reader误判，必须在shared fixture/tests通过后回写Capability/产品Skill，不能只改本兼容入口。
当前Host是OpenCode 1.18.30；在current native export重验前不得把上述历史shape冒充当前运行证据。

## 数据源与位置（按可靠性排序）

1. **`thoughts.jsonl`【主源，最完整】**：ACP客户端实时逐chunk落盘的thinking流。
   每行一个JSON对象：`{"t": 秒, "mid": 消息id, "text": 文本碎片}`。chunks按序拼接
   即完整thinking。进程崩溃也不丢（实时flush）。各轮归档于
   `<项目>/poc_assets/poc_2.7.5/v2run/roundN/thoughts.jsonl` 或工作目录 `acp_out_rN/thoughts.jsonl`。
2. **`opencode_export.json`**：`opencode export <sessionId>` 的导出。【已知缺陷：
   大session下经subprocess管道捕获会在65536字节处截断损坏——不可依赖，仅作辅助】
3. **`thinking.md`**：已由主控从thoughts.jsonl拼接的纯文本（可直接read/grep）。

## 截断指纹（BUDGET_STARVED判定）

opencode撞单响应output上限时 **stopReason仍报`end_turn`，无显式length标记**。
可靠指纹 = 以下三条同时成立：
- prompt_response.result.usage.outputTokens 为整数值（如32000）
- 全程 0 个 message chunk、0 个 tool_call
- thinking流在句中戛然而止

此时该轮状态为 BUDGET_STARVED（预算耗尽），其thinking尾部就是**最新的未记录进展**。

## 分析工具：`scripts/oc_traj.py`

两层遍历设计（同zcode_traj.py范式）：先scan概览定位，再read精确下钻。

```bash
S=/Users/user/.config/opencode/skills/oc-trajectory/scripts/oc_traj.py

# 第一层：分段大纲——段号|行号范围|字符数|首句（转折词边界自动分段）
python3 $S scan <thoughts.jsonl|thinking.md>

# 看前一轮"最后的思考"（写分析笔记的第一步）
python3 $S tail <file> 6000        # 默认6000字符，可调

# 第二层：精确下钻
python3 $S read <file> <start> [chars]     # 从字符位start读N字符
python3 $S search <file> 'alpha.*ge.*3'    # 正则定位关键结论/转折
```

坐标系统一为**字符位置+行号**双坐标，与内置read工具的行号读取兼容。

## 典型工作流：接手前轮工作（写分析笔记）

1. 读前轮`工作笔记.md`——注意它只是索引：最后一次笔记更新之后、截断之前的
   进展只在thinking尾部。
2. `tail <前轮thinking> 8000`——看它最后的思考停在哪里、有哪些没进笔记的进展。
3. `search` 定位关键结论在thinking中的位置，`read` 下钻细节。
4. 整合写出你的`分析笔记.md`：前轮真实前沿 + 笔记遗漏的尾部进展 + 当前缺口。

## 与其他trajectory skill的区分

| 客户端 | 数据位置 | 工具 |
|---|---|---|
| **opencode ACP** | 项目内 `acp_out_rN/thoughts.jsonl` | 本skill |
| ZCode桌面 | `~/.zcode/cli/rollout/model-io-sess_*.jsonl` | zcode-trajectory skill |
| Devin CLI | `~/.local/share/devin/cli/transcripts/*.json` | devin-cli-trajectory skill |
