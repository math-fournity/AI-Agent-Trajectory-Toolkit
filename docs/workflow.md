# 开发工作流总纲

**日期**：2026-08-19
**性质**：全局开发工作流的完整定义。所有项目通用。

---

## §1 核心问题

**我们无法将整个项目的所有知识都放入AI的上下文。**

一个项目可能有数十个文档、上百个代码文件、数据库、数据资产。全部加载会撑爆上下文窗口，而且大部分内容和当前任务无关。

我们的解决方案是一套三层认知管理体系，让AI只加载必要认知去完成一个具体任务。

---

## §2 三层认知架构

**注意**：这里的"三层"是**认知管理的加载层次**（AGENTS.md → README.md → 看法文件 → 具体文档），和 §3.5 的**资产分层**（第0层函数 → 第1层文件 → 第2层看法文件 → 第3层默认看法）是不同的概念。前者是"AI怎么加载认知"，后者是"项目资产怎么分层寻址"。

```
第一层 AGENTS.md（铁律+最小索引，always-on）
  ↓ AI从铁律中知道行为约束，从索引中知道有哪些skill和文档
第二层 README.md（分类法索引，按需加载）
  ↓ AI判断"当前问题需要哪种视角"，加载对应的看法文件
第三层 看法文件（文档索引，按需加载）
  ↓ AI判断"需要加载哪些具体文档/代码"，加载它们
第三层 具体文档/代码/资产（实际内容，按需加载）
  ↓ AI带着必要认知工作
```

### 第一层：AGENTS.md

- **always-on**，每个session自动加载
- 只放硬约束、行为规范
- 不放文档详细描述、不放分类法详细描述、不放rule/skill索引（devin自动加载）
- 每个项目有自己的项目级 AGENTS.md，全局有 `~/.config/devin/AGENTS.md`

### 第二层：README.md

- AI接手时加载，判断"我当前的问题需要哪种分类法"
- 每个分类法一段描述：视角是什么、加载能得到什么、看法文件在哪里
- **不描述具体文档**——具体文档的描述在看法文件中

### 第三层：看法文件

- 每种分类法一个看法文件
- 说清楚：加载能得到什么、索引了哪些文件、那些文件分别讲什么
- AI加载看法文件后，再判断"需要加载哪些具体文档"

### 分类法

分类法 = 同一批知识的不同切片视角。就像数据库的视图——底层数据一样，按不同维度组织展示。

常见分类法（按项目实际情况识别，不强制套用）：
1. 系统认知（是什么）
2. 设计决策（为什么这样设计）
3. 需求（要满足什么）
4. 源码（怎么实现）
5. 工作流（怎么推进）
6. 运行操作（怎么运行）
7. 历史（怎么演变）

**分类法的性质**：
- 视图重叠是正常的——同一个文档可以被多个分类法索引
- 一个分类法必须能索引一批文档/代码/资产——只覆盖一个的不够独立成分类法
- 分类法可以新增——项目演进中可能出现新的视角

---

## §3 映射索引（view-index.csv）

看法文件和映射索引是同一事实的两个表达：
- 看法文件：人/AI可读的描述
- 映射索引：机器可查询的索引（CSV文件，git可逐行diff，保留完整变更历史）

两者必须保持一致。

### 存储格式

CSV文件（UTF-8，有header row），git可追踪，每次变更可逐行diff：

**view-index.csv**（看法文件↔文档映射）：
```
taxonomy,view_file,asset_path,asset_type,asset_title
历史,dev-docs/README.md,dev-docs/001-目录结构扁平化重组方案.md,document,目录结构扁平化重组方案
源码,src/README.md,monitoring/continuation_control.py,code,续传控制（Pipe 4控制命令）
...
```

**trace.csv**（全维度追溯，见§3.5）：
```
source_type,source_id,target_type,target_id,relation,note,commit_id
checkpoint,MON-A1,wp,WP-09,part-of,Monitor Pipe A类检查项1属于WP-09,
checkpoint,MON-A1,code,monitoring/analysis_control.py,implements,A类检查项1由analysis_control实现,
...
```

**为什么用CSV而不是SQLite**：SQLite是二进制文件，git无法diff，失去版本管理。CSV是文本文件，git可以逐行diff，保留完整变更历史——不是只保留最后的表，而是过程中的表全部在git log中被追踪。

### 核心查询

```bash
# 文档/代码变更时，查哪些看法文件需要更新
python3 scripts/view_index.py query-by-asset <asset_path>

# 看法文件要更新时，查它索引了哪些文档
python3 scripts/view_index.py query-by-view <view_file>

# 总览
python3 scripts/view_index.py stats
python3 scripts/view_index.py list-views
```

---

## §3.5 全维度追溯体系（trace.csv）

view-index.csv 追踪的是"看法文件↔文档"的映射（认知管理用）。但项目中还有大量其他维度的引用关系需要追踪：需求↔代码、需求↔工作包、工作包↔方案、资产↔commit等。这些关系用 trace.csv 追踪。

### 为什么需要全维度追溯

项目演进中会产生大量互相引用的关系：
- 一个需求(checkpoint)被实现为某些代码，由某些文档规范定义，属于某个工作包
- 一个工作包涉及多个需求，动了某些代码，形成了某些文档，来自某个方案文档
- 任何代码/文档的变更都对应一个git commit id——可以看到diff，精确了解影响是什么

这些关系构成一个**有向图**。trace.csv 用一张通用关系表表达这个图。

### 资产分层

资产是分层的，不是扁平的。从底到顶：

```
第0层  原子单元
  → 代码中的函数、类定义
  → 文档中的一个叶子小节

第1层  文件
  → .py 文件、.md 文档、.sh 脚本

第2层  看法文件（views/ 下专门维护的索引）
  → views/src.md（源码视角的索引）
  → views/design.md（设计决策视角的索引）
  → 这些不是 repo 默认就有的，是专门为了某种视角维护出来的

第3层  默认看法（repo 结构自带的项目级分类法）
  → checklist/（需求分类法——repo 目录结构自带）
  → working-packages/（工作流分类法——repo 目录结构自带）
  → dev-docs/（历史分类法——repo 目录结构自带）
  → 这些是 repo 的"默认看法"，不是额外维护的索引，而是项目结构本身
```

追溯链可以跨层：需求(第3层) → 看法文件(第2层) → 代码文件(第1层) → 函数(第0层) → commit

### XPath-like 寻址方案

因为资产是分层的，source_id / target_id 必须是能在整个项目资产树中唯一定位的路径表达式（类似 XPath），不能只是文件路径或函数名——函数名可能重名。

| 层级 | 格式 | 示例 |
|---|---|---|
| 代码文件 | `<path>` | `monitoring/continuation_control.py` |
| 代码类 | `<path>::<Class>` | `monitoring/continuation_control.py::ContinuationControl` |
| 代码函数/方法 | `<path>::<Class>.<method>` 或 `<path>::<func>` | `monitoring/continuation_control.py::ContinuationControl.start` |
| 文档文件 | `<path>` | `docs/system/AnalysisSystemOps.md` |
| 文档章节 | `<path>#<section>` | `docs/system/AnalysisSystemOps.md#接手指南` |
| 文档子章节 | `<path>#<section>><subsection>` | `docs/system/AnalysisSystemOps.md#接手指南>环境检查` |
| 看法文件 | `<path>` | `views/src.md` |
| 看法文件章节 | `<path>#<section>` | `views/src.md#monitoring模块` |
| checkpoint | `<id>` 或 `<path>` | `MON-A1` 或 `checklist/MON-A1.md` |
| 工作包 | `<id>` 或 `<path>` | `WP-09` 或 `working-packages/WP-09.md` |
| commit | `<hash>` | `a4f3a61` |

分隔符：
- `::` 代码符号导航（文件→类/函数）
- `#` 文档章节导航（文件→章节）
- `>` 章节嵌套（章节→子章节）
- `.` 类内方法导航（Class.method）

层级判定规则（由路径中的分隔符决定）：
- 不含 `::` 或 `#` 的路径 = 文件级（第1层）
- 含 `::` 的路径 = 代码符号级（第0层）
- 含 `#` 的路径 = 文档章节级（第0层）
- 纯编号（如 `MON-A1`）= 第2层及以上

### trace.csv 格式

```csv
source_type,source_id,target_type,target_id,relation,note,commit_id
checkpoint,MON-A1,wp,WP-09,part-of,Monitor Pipe A类检查项1属于WP-09,
checkpoint,MON-A1,code,monitoring/analysis_control.py,implements,A类检查项1由analysis_control实现,
code,src/config.py,commit,a4f3a61,changed-in,PROJECT_ROOT从子系统改为根目录,
...
```

字段说明：
- `source_type` / `target_type`：资产类型（checkpoint/wp/document/code/script/dev-doc/view-file/commit/data）
- `source_id` / `target_id`：资产标识（路径或编号）
- `relation`：关系类型（implements/specified-by/part-of/changes/produces/comes-from/changed-in/depends-on/verifies/indexed-by/traces-to）
- `note`：可选说明
- `commit_id`：如果关系涉及git commit

唯一约束：(source_type, source_id, target_type, target_id, relation)

### 资产类型

| 类型 | 层级 | 说明 | 标识方式 |
|---|---|---|---|
| checkpoint | 第3层 | 需求点（默认看法） | 编号 `MON-A1` 或路径 `checklist/MON-A1.md` |
| wp | 第3层 | 工作包（默认看法） | 编号 `WP-09` 或路径 `working-packages/WP-09.md` |
| dev-doc | 第3层 | 方案文档（默认看法） | 路径，如 `dev-docs/002-xxx.md` |
| view-file | 第2层 | 看法文件（专门维护的索引） | 路径，如 `views/src.md` |
| document | 第1层/第0层 | 文档 | 文件路径或 `path#章节` |
| code | 第1层/第0层 | 代码 | 文件路径或 `path::函数` |
| script | 第1层 | 脚本 | 路径，如 `scripts/monitor_check.sh` |
| data | 第1层 | 数据资产 | 路径 |
| commit | — | git commit | commit hash |

**注意**：code 和 document 类型可以跨第0层和第1层——由 id 中的分隔符决定（含 `::` 或 `#` = 第0层，否则 = 第1层）。

### 关系类型

| 关系 | 方向 | 说明 |
|---|---|---|
| implements | checkpoint→code/function | 需求实现为代码（可精确到函数） |
| specified-by | checkpoint→document/section | 需求由文档规范定义（可精确到章节） |
| part-of | checkpoint→wp | 需求属于工作包 |
| changes | wp/dev-doc→code/function | 工作包/方案改动代码（可精确到函数） |
| produces | wp/dev-doc→document | 工作包/方案产生文档 |
| creates | wp→checkpoint | 工作包创建需求点 |
| comes-from | wp→dev-doc | 工作包来自方案 |
| changed-in | 任意→commit | 资产在commit中被改动（任意层级） |
| depends-on | 任意→任意 | 依赖关系 |
| verifies | document→checkpoint | 文档验证需求 |
| indexed-by | document/code→view-file | 被看法文件索引 |
| traces-to | 任意→任意 | 通用追溯 |
| contains | 文件→函数/章节 | 包含关系（第1层→第0层） |
| organizes | 默认看法→看法文件 | 组织关系（第3层→第2层） |

### 核心查询

```bash
# 查某资产的所有关系（双向：作为source和作为target）
python3 scripts/trace.py query <type> <id>

# 查某资产的outgoing关系（它指向什么）
python3 scripts/trace.py query-out <type> <id>

# 查某资产的incoming关系（什么指向它）
python3 scripts/trace.py query-in <type> <id>

# 查某种关系类型的所有记录
python3 scripts/trace.py query-relation <relation>

# 查某文件下所有子资产（函数/章节）的关系——分层追溯用
python3 scripts/trace.py query-prefix <type> <id_prefix>
# 例：query-prefix code monitoring/analysis_control.py
#   → 返回该文件本身 + 其下所有 ::函数 的关系

# 从某资产出发，递归追溯关系链（BFS，最多5层）
python3 scripts/trace.py trace <type> <id>

# 显示某资产的层级深度和文件/符号分解
python3 scripts/trace.py level <type> <id>

# 添加/删除关系
python3 scripts/trace.py add <s_type> <s_id> <t_type> <t_id> <relation> [note] [commit_id]
python3 scripts/trace.py remove <s_type> <s_id> <t_type> <t_id> <relation>

# 统计/类型参考
python3 scripts/trace.py stats
python3 scripts/trace.py list-types
```

### 追溯链示例

从需求 MON-A1 出发的追溯链（跨层追溯，从第2层到第0层到commit）：
```
[checkpoint]MON-A1                                    ← 第2层（默认看法）
  --implements--> [code]monitoring/analysis_control.py::run_analysis  ← 第0层（函数）
    --changed-in--> [commit]a4f3a61                   ← commit
  --specified-by--> [document]docs/specs/p27_monitor_spec.md#A类检查项  ← 第0层（章节）
  --part-of--> [wp]WP-09                              ← 第2层（默认看法）
    --comes-from--> [dev-doc]dev-docs/002-xxx.md      ← 第3层（默认看法）
      --produces--> [document]checklist/README.md     ← 第1层（文件）
        --changed-in--> [commit]f1ca691               ← commit
```

这条链说明：需求MON-A1由analysis_control.py的run_analysis函数实现（精确到函数，不是整个文件），由p27_monitor_spec.md的A类检查项章节定义（精确到章节），属于WP-09，WP-09来自002方案，002方案产生了checklist/README.md，这个文件在commit f1ca691中被改动。

**分层追溯的价值**：
- 文件级追溯告诉你"这个需求和这个文件有关系"
- 函数级追溯告诉你"这个需求由这个文件的这个函数实现"——当文件有100个函数时，函数级追溯让你精确知道改哪个函数会影响这个需求
- 章节级追溯告诉你"这个需求由这个文档的这个章节定义"——当文档有50页时，章节级追溯让你精确知道改哪个章节会影响这个需求

### 和view-index.csv的关系

- **view-index.csv**：专门管理"看法文件↔文档"的映射，read-sync skill用它做认知管理
- **trace.csv**：全维度追溯，记录项目中所有资产之间的有向关系
- 两者各自操作独立的CSV文件，都是git可追踪的文本文件
- trace.csv中的 `indexed-by` 关系类型和view-index.csv的内容有语义重叠，但用途不同：view-index用于认知管理查询，trace用于全维度追溯

---

## §3.6 幂等关系（trace.csv ↔ repo）

### 定义

**trace.csv 与 repo 保持实时幂等关系**——给定任何一个 commit 时间点，trace.csv 的状态精确反映 repo 在那个时间点的所有元素和关系。

- trace.csv 不是"近似索引"，不是"事后补录"，而是 repo 状态的**精确镜像**
- "实时"意味着每次 repo 变更时同步更新 trace.csv，不是事后批量同步
- trace.csv 和 repo 在**同一个 git 仓库、同一个 commit** 中——在任何一个 commit 上 checkout，trace.csv 的内容精确反映那个 commit 的 repo 状态

### 维护方式

- **维护者**：AI（不是人）
- **维护场所**：工作包——工作包是 trace.csv 维护的最小单元
- **维护时机**：每次 repo 变更时同步更新 trace.csv，两者在同一个 commit 中
- **维护粒度**：各个层级——文件级、函数级、章节级。改了某个函数，trace.csv 中这个函数对应的记录也要同步更新

### AI 的双重责任

AI 在工作包中工作时，对 trace.csv 既是**消费者**又是**生产者**：

- **消费**：利用 trace.csv 了解"我应该了解的情况"——当前工作包涉及哪些资产，这些资产和哪些其他资产有关系，改了某个文件会影响哪些看法文件/需求/工作包
- **生产**：在工作包执行过程中，持续更新 trace.csv，记录自己造成的所有新关系和变更关系

维护的目的不仅是当前工作包，更是**未来的下一个工作包的 AI**——下一个 AI 接手时，trace.csv 是它了解 repo 的基础设施。

### 破坏后果

幂等关系被破坏 = trace.csv 中的记录和 repo 实际状态不一致 = AI 按 trace.csv 查询得到错误信息 = 认知体系失效 = 三层架构断裂

### 为什么需要幂等关系

AI 的上下文窗口有限（20万 token，连续工作不超过16万 token，超过被压缩导致记忆丧失）。不可能把整个 repo 的所有元素放入上下文。

trace.csv 是**外化的记忆**——本身很小（CSV 文本文件），可以快速加载和查询，但它索引了整个 repo 的所有元素关系。通过 trace.csv 的追溯链，AI 能精确知道"哪些元素和当前任务有关"，只加载这些元素，但认知效果等价于"全知"。

幂等关系是这一切的前提——只有 trace.csv 精确反映 repo 状态，AI 的追溯查询结果才是可信的。

---

## §4 三个核心skill

### read skill——按三层架构加载认知

用户调用 `read` 时（后面可能跟上提问内容），AI的工作流：

1. 检查README.md是否在上下文中
2. 不在则完整加载
3. **分析用户提问，判断需要哪种视角**——对照README.md的分类法索引
4. **加载对应的看法文件**
5. **从看法文件中找到需要加载的具体文档/代码**
6. **加载具体文档/代码/资产**——按需加载，可以回溯到README.md加载其他看法文件
7. 综合思考，回答/解决用户问题

关键约束：
- README.md是起点不是终点
- 看法文件是索引不是内容
- 按需加载不贪多
- 可以回溯

### read-sync skill——创建/维护认知地图

当repo的文档/代码体系发生变化时，用read-sync同步更新认知地图。

**分类法决策树**（遇到新文档/新知识时必须执行）：
```
新文档/新知识出现
  ↓
第1步：它讲什么？属于哪种视角？
  ↓
第2步：是否匹配某个现有分类法？
  ├─ 是 → 更新该分类法的看法文件
  └─ 否 → 第3步
  ↓
第3步：它是否代表一种新的视角？能索引一批文档/代码/资产？
  ├─ 是 → 新建分类法（README.md加一段+创建看法文件）
  └─ 否 → 归入最接近的现有分类法，更新其看法文件
```

**每次变更后必须同步映射索引**——改了看法文件就必须同步 `view-index.csv`，反之亦然。

**验证**：
- 三层架构检查
- 分类法覆盖性检查
- 文档覆盖性检查
- **映射索引一致性检查**——对每个看法文件核对CSV索引和实际描述是否一致
- 认知完整性检查

### make-plan skill——制作行动计划

**行动方案 = 一次完整的repo更新行为。**

系统演进逻辑：
```
行动方案 = 一次完整的repo更新行为
  → 更新文档和代码需要AI提前获得充分但不过载的认知
  → 为此利用/新建看法索引文件，确保AI能成功更新repo
  → 更新不只是更新数据，更要更新元数据
  → 对任何文档和代码的更新，都要查映射索引（view-index.csv / trace.csv）
  → 看哪些看法索引文件依赖了它，是否需要更新
  → 追溯粒度可分层：文件级（改了整个文件）或函数/章节级（只改了某个函数/章节）
```

行动方案必须包含四个层面：
1. **执行步骤**——要更新哪些文档和代码？怎么更新？精确到什么层级（文件级/函数级/章节级）？（数据更新）
2. **需求追踪与工作包**——为什么更新？对应哪个需求点？在整体进度中的位置？（过程管理）
3. **认知准备**——执行时AI需要什么认知？提前利用/新建看法索引文件（前置条件）
4. **元数据更新计划**——更新后哪些看法索引文件需要同步更新？对每个会改动的资产查映射索引（`query-by-asset` 查文件级，`query-prefix` 查子资产级）（后置条件）

**认知准备是前置条件**——执行前为AI准备好认知加载路径，不能执行到一半才发现没有合适的看法文件。

**元数据更新是后置条件**——执行完成后必须更新看法索引文件和映射索引（view-index.csv / trace.csv）。更新了数据但不更新元数据 = 下次AI按看法文件加载时得到过时信息 = 认知体系失效。

**分层追溯精度**：
- 改了整个文件 → `query-by-asset <文件路径>` 查哪些看法文件索引了它
- 只改了某个函数/章节 → `query-prefix <type> <文件路径>` 查该文件下所有子资产的关系，精确到函数/章节级

### 工作包自包含设计

方案最终会被拆解成一个个小工作包。**工作包是自包含的**——每个工作包包含执行它的 AI 所需的全部认知信息，不需要"额外去项目里找"。

**自包含的实现方式**：工作包 README.md 中列出：
1. **需要的 View（看法文件）**——AI 按看法文件去加载相关文档
2. **甚至直接列出需要加载的具体文档和代码**——省去 AI 自己判断的步骤

**拆解粒度为什么重要**：
- 粒度太粗 → 单个工作包需要加载的元素太多，超出上下文限制（20万 token，连续工作不超16万）
- 粒度太细 → 工作包数量太多，管理成本高
- **拆解过程严重依赖 trace.csv**——通过追溯链精确判断"这个工作包需要哪些元素"，从而确定合适的粒度

**方案"完备"的定义**：方案制定时，通过 trace.csv 追溯链，AI 能精确知道"哪些元素和当前方案有关"，只加载这些元素，但认知效果等价于"整个 repo 的所有元素都放入了上下文"——这在现实上不可能（上下文受限），但通过 trace.csv 的幂等追溯可以实现等价效果。

**工作包中的 AI 工作规范**：
- **全程密集 git 提交**——每完成一个逻辑单元就提交，不是"做完了再提交"
- **提交前必须维护 trace.csv**——每个 commit 之前，trace.csv 必须先被更新到反映当前 repo 状态。commit 中同时包含 repo 变更和 trace.csv 变更
- **各层级维护**——不只是文件级，还包括函数级、章节级。改了某个函数，trace.csv 中这个函数对应的记录也要同步更新
- **幂等关系是铁律**——每个 commit 时间点上，trace.csv = repo 状态的精确镜像

---

## §5 完整开发工作流

一次完整的开发工作循环：

### 阶段1：接手——加载认知

```
用户提问 / 新session接手
  ↓
调用 read skill
  ↓
加载README.md（分类法索引）
  ↓
分析提问，判断需要哪种视角
  ↓
加载看法文件
  ↓
从看法文件中找到具体文档/代码
  ↓
加载具体文档/代码
  ↓
带着必要认知准备回答/工作
```

### 阶段2：计划——制定行动方案

```
用户要求做某件事
  ↓
调用 make-plan skill
  ↓
步骤1：制定执行步骤（要更新哪些文档和代码，精确到什么层级）
  ↓
步骤2：更新需求追踪（checklist）——在checklist中建立checkpoint
  ↓
步骤3：建立方案文档（dev-docs）——利用trace.csv追溯链实现"完备"方案
  ↓
步骤4：拆解工作包——利用trace.csv追溯每个工作包涉及的元素，确定自包含的README.md
  ↓
步骤5：认知准备——列出每个步骤需要的视角，检查/创建/补充看法文件，同步映射索引（view-index.csv）
  ↓
步骤6：元数据更新计划——对每个会改动的资产查query-by-asset/query-prefix，列出需要同步的看法文件
  ↓
步骤7：整合行动计划
  ↓
步骤8：落盘并commit（trace.csv同步记录checkpoint/dev-doc/wp元素）
```

**方案"完备"的含义**：通过 trace.csv 追溯链，AI 精确知道"哪些元素和当前方案有关"，只加载这些元素，但认知效果等价于"整个 repo 的所有元素都放入了上下文"。

**工作包自包含**：每个工作包 README.md 列出执行 AI 需要的 View（看法文件）和具体文档/代码，拆解过程严重依赖 trace.csv 的追溯支持。

### 阶段3：执行——更新repo

```
加载工作包README.md → 按View加载看法文件 → 加载具体文档/代码
  ↓
按行动方案的执行步骤工作
  ↓
每步执行时，按认知准备中列出的视角加载看法文件和具体文档
  ↓
更新文档和代码（数据更新）
  ↓
AI双重责任：
  消费——利用trace.csv了解当前步骤涉及哪些元素，改了什么会影响什么
  生产——持续更新trace.csv，记录自己造成的新关系和变更关系
  ↓
全程密集git提交——每完成一个逻辑单元就提交
  ↓
每次提交前维护trace.csv各层级幂等关系（文件级/函数级/章节级）
  ↓
commit同时包含repo变更和trace.csv变更
  ↓
每步完成后验证
```

**幂等关系是铁律**：每个 commit 时间点上，trace.csv = repo 状态的精确镜像。提交前不维护 trace.csv = 幂等关系破坏 = 下一个工作包的 AI 得到错误信息。

### 阶段4：元数据更新——同步认知地图

```
执行完成
  ↓
按元数据更新清单，对每个被改动的资产：
  ↓
  文件级改动：query-by-asset <被改动的文件> → 查哪些看法文件依赖了它
  函数/章节级改动：query-prefix <type> <文件路径> → 查该文件下所有子资产的关系
  ↓
  更新看法文件中对应条目的描述（讲什么/覆盖问题场景/依赖关系）
  ↓
  同步映射索引（view-index.csv / trace.csv add/remove）
  ↓
commit元数据更新
```

**不更新元数据 = 认知体系失效 = 下次AI按看法文件加载时得到过时信息**

**分层精度**：
- 改了整个文件 → 文件级追溯（`query-by-asset`）
- 只改了某个函数/章节 → 函数/章节级追溯（`query-prefix`），精确到 `path::function` 或 `path#section`

### 阶段5：验证——确认认知地图完整

```
调用 read-sync skill 的验证流程
  ↓
三层架构检查
  ↓
分类法覆盖性检查
  ↓
文档覆盖性检查
  ↓
映射索引一致性检查
  ↓
认知完整性检查
  ↓
commit
```

---

## §6 Skill 极简化设计

所有 skill 一律采用"一句话触发器 + 独立内容文档"模式：

- **SKILL.md**（`~/.config/devin/skills/<name>/SKILL.md`）——只有一句话：`完整加载 /Users/user/skills-devin/<文件名>，结合用户的要求和上下文中的信息，完成该文档中的要求。`
- **完整内容文档**（`/Users/user/skills-devin/<文件名>`）——真正的 skill 内容

**为什么**：
1. SKILL.md 极简——只有 frontmatter + 一句话，不挤占空间
2. 真正内容按需加载——和三层架构思想一致
3. devin 自动发现——available_skills 列表通过 description 展示用途，不需要在 AGENTS.md 维护索引

---

## §7 Git 管理协议

### 三个全局 git 仓库

| 仓库 | 位置 | 内容 |
|---|---|---|
| 全局配置 | `~/.config/`（devin/子目录） | AGENTS.md、skills/触发器、config.json、rules/ |
| 全局rules | `~/.devin/` | rules/、argv.json |
| skill完整内容 | `/Users/user/skills-devin/` | 所有skill的完整内容文档 |

### Git Clean 铁律

**全局配置Git提交铁律**（§15）：
- 任何对 `~/.config/devin/` 或 `~/.devin/` 的修改，必须立即git提交
- 不允许"改完不提交"或"批量攒着一起提交"

**skills-devin目录Git Clean铁律**（§16）：
- 更新 `/Users/user/skills-devin/` 中的文件前必须 git clean
- 更新后也必须 git clean
- 操作流程：更新前 `git status --short` 确认 clean → 更新 → `git add <具体路径>` + `git commit` → 更新后 `git status --short` 确认 clean

### 通用Git纪律

- **改文件前**：检查目标文件/目录是否处于 git clean 状态 → 记录 baseline → 明确 intended_delta
- **改文件后**：完成一个逻辑工作单元立即 commit → 核验 `after - before == intended_delta` → 回到 git clean
- **禁止** `git add -A`、`git add .`、`git add -u`。只 add 具体路径
- **任何 `git push` 都必须获得用户当轮明确授权**

---

## §8 项目级结构

一个采用本工作流的项目，目录结构：

```
<project>/
  AGENTS.md                    ← 项目级铁律+最小索引（always-on）
  README.md                    ← 分类法索引（认知管理第二层）
  src/                         ← 代码（第1层资产）
  monitoring/                  ← 监控代码（第1层资产）
  scripts/                     ← 脚本（含view_index.py, trace.py）
  docs/                        ← 文档（按子目录分类，第1层资产）
  views/                       ← 看法文件目录（第2层资产，专门维护的索引）
    src.md                     ← 源码视角的看法文件
    design.md                  ← 设计决策视角的看法文件
    ...
  checklist/                   ← 需求点清单（第3层，默认看法：需求分类法）
    README.md                  ← 需求分类法的看法文件
  working-packages/            ← 工作包管理（第3层，默认看法：工作流分类法）
    README.md                  ← 工作流分类法的看法文件
  dev-docs/                    ← 变更历史与方案记录（第3层，默认看法：历史分类法）
  view-index.csv               ← 看法文件↔文档映射索引（git可追踪）
  trace.csv                    ← 全维度追溯索引（git可追踪，XPath-like分层寻址）
```

**看法文件的两个层级**：
- **第2层看法文件**（`views/` 下）：专门为了某种视角维护出来的索引，不是 repo 默认就有的。如 `views/src.md`（源码视角）、`views/design.md`（设计决策视角）
- **第3层默认看法**（`checklist/`、`working-packages/`、`dev-docs/`）：repo 结构自带的项目级分类法，不是额外维护的索引，而是项目结构本身

**默认看法的看法文件**放在对应的知识目录下：
- `checklist/README.md` — 需求分类法
- `working-packages/README.md` — 工作流分类法
- `dev-docs/README.md` — 历史分类法

**第2层看法文件**放在 `views/` 下：
- `views/src.md` — 源码视角
- `views/design.md` — 设计决策视角
- `views/runtime.md` — 运行操作视角
- （按项目实际情况识别和创建）

---

## §9 设计原则总结

1. **三层架构**——AGENTS.md（铁律）→ README.md（分类法索引）→ 看法文件（文档索引）→ 具体文档/代码。各层各司其职，不越层
2. **只加载必要认知**——三层架构的意义是让AI只加载必要认知去完成具体任务，不贪多
3. **分类法是视图不是分区**——同一个文档可以被多个分类法索引，视图重叠正常
4. **映射索引双向跟踪**——看法文件和 view-index.csv 是同一事实的两个表达，必须一致。CSV是git可追踪的文本文件，保留完整变更历史
5. **全维度追溯+分层寻址**——trace.csv 记录项目中所有资产之间的有向关系（需求↔代码、需求↔工作包、工作包↔方案、资产↔commit），构成追溯网络。资产是分层的（第0层函数/章节→第1层文件→第2层看法文件→第3层默认看法），用 XPath-like 路径表达式唯一定位（`path::function`、`path#section`），解决函数重名问题。查任何资产都能跨层追溯到它的来龙去脉，包括git commit id可以看到diff精确了解影响
6. **幂等关系铁律**——trace.csv 和 repo 保持实时幂等关系，给定任何 commit 时间点，trace.csv 精确反映 repo 状态。两者在同一个 commit 中同步演进。破坏幂等 = AI 得到错误信息 = 认知体系失效
7. **AI双重责任**——AI 在工作包中工作时，对 trace.csv 既是消费者（利用它了解情况）又是生产者（维护它记录变更）。维护的目的不仅是当前工作包，更是下一个工作包的 AI
8. **工作包自包含**——每个工作包 README.md 列出执行 AI 需要的 View（看法文件）和具体文档/代码。拆解粒度依赖 trace.csv 追溯支持。方案"完备"= 通过追溯链实现等价于"全知"的认知
9. **行动方案=完整的repo更新行为**——执行步骤+需求追踪+认知准备+元数据更新，四位一体
10. **认知准备是前置条件**——执行前为AI准备好认知加载路径
11. **元数据更新是后置条件**——执行后更新看法文件和映射索引（view-index.csv / trace.csv），否则认知体系失效
12. **提交前维护trace.csv**——全程密集 git 提交，每次提交前必须维护 trace.csv 各层级幂等关系。commit 同时包含 repo 变更和 trace.csv 变更
13. **Skill极简化**——一句话触发器+独立内容文档，解决skill发现机制不可靠问题
14. **Git Clean是可信状态**——三个全局仓库+项目仓库，所有变更必须落盘commit
