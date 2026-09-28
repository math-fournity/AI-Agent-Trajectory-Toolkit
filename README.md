# AI-Agent-Trajectory-Toolkit

跨宿主 AI Coding Agent **轨迹分析工具链**——同一套分层读取方法论在 Codex / OpenCode /
ZCode 三个宿主的 Skill 实现与协议文档，外加 Devin 的 ACP 协议文档与解析脚本。
本仓库是 [AI-Math-Competition-Problem-Solving-System](https://github.com/math-fournity/AI-Math-Competition-Problem-Solving-System)
（AI 数学竞赛题持续解题系统）的配套工具：其解题管线依赖对 agent 会话轨迹的分层审查
（observer 必须亲自 scan→tail→inspect 原始现场，见主仓库 `docs/architecture/layered-trajectory-reader.md`）。

> 本仓库是全局治理框架的**公开子集**：只含轨迹分析与 ACP 协议层；治理宪法、运营类
> Skill（email/X/账号注册等）与个人环境路由未收录。条目级取舍见 `CAPABILITY_INDEX.md`。

## 目录结构与三宿主形态

| 目录 | 宿主 | 形态 |
|---|---|---|
| `codex/` | Codex | **权威版** `repo-agent-session-trajectory` SKILL（146 行，框架发源地，版本锚见下） |
| `opencode/` | OpenCode | **实质 port**：`oc-trajectory`（SKILL+`oc_traj.py`，服务 thoughts.jsonl/thinking.md reasoning 流）+ `repo-agent-session-trajectory`（148 行，适配 OpenCode session 导出/SQLite） |
| `zcode/` | ZCode Desktop | **精简版** `repo-agent-session-trajectory`（64 行最小内核，配合 ZCode model-io 私有提取流程） |
| `protocols/` | 通用 | 四份协议/方法文档：Devin ACP、OpenCode ACP、ZCode 轨迹、Devin CLI 轨迹 |
| `scripts/` | 通用 | `zcode_traj.py`（ZCode model-io 分层分析）、`devin_traj.py`（Devin sessions.db）、`acp_activity_blocks.py`（raw ACP delta→activity blocks）、`validate_capability_index.py` |
| `docs/` | 通用 | 配套作业方法：`read`（三层认知加载）、`read-sync`（README 认知地图维护）、`make-plan`（行动计划）、`workflow`（开发工作流总纲） |
| `CAPABILITY_INDEX.md` | — | 跨宿主能力路由注册表（**公开裁剪版**，仅 trajectory/ACP 条目） |

**为什么不是三份独立框架**：Codex 版是权威内核；OpenCode/ZCode 是同一方法论的宿主适配
（SKILL 接口与提取路径不同，分层判定合同一致）。三宿主对照阅读本身就是 port 方法论的示范。

## 安装

| 宿主 | 安装方式 |
|---|---|
| Codex | 复制 `codex/repo-agent-session-trajectory.SKILL.md` → `~/.codex/skills/repo-agent-session-trajectory/SKILL.md` |
| OpenCode | 复制 `opencode/oc-trajectory.SKILL.md` + `oc_traj.py` → `~/.config/opencode/skills/oc-trajectory/`（同构 `repo-agent-session-trajectory`） |
| ZCode | 复制 `zcode/repo-agent-session-trajectory.SKILL.md` → `~/.zcode/skills/repo-agent-session-trajectory/SKILL.md` |
| 通用 | `scripts/` 独立可运行（Python 3.10+，无第三方依赖）；`protocols/`、`docs/` 按需加载 |

## 与主系统的关系

- 主系统 053 分层 trajectory 铁律（observer 必须亲自使用 backend reader 对完整原始现场
  执行 scan→tail→search/inspect）以本工具链为实现载体；
- 数据实例见主系统姊妹仓库 `AI-Math-Solving-Trajectories(-Archive)`（5 万+ 真实解题 run
  的对话录/轨迹/终端日志）；
- 从零复原完整解题环境见主仓库 `docs/RESTORE-GUIDE.md`。

## 版本锚

- 源框架：Codex 全局治理 `GOVERNANCE_VERSION 1.1.0`（2026-09-18 同步 pass；
  上次 Codex 全局同步源 3.23.1 @ 2026-09-18）
- 索引注册表版本：`1.2.0-candidate`（evidence refresh 2026-09-04；公开裁剪版 2026-09-28）
- 脱敏口径：原始用户目录名/卷路径已中性化（`/Users/user`、`/Volumes/data`）；
  原始完整版（含个人路由）由作者离线持有

## License

MIT（见 [LICENSE](LICENSE)）；不覆盖其指向的上游数据集许可（本仓库不含数据）。
