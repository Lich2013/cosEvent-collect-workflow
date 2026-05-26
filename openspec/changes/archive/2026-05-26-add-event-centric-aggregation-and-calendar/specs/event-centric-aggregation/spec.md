## ADDED Requirements

### Requirement: 智能时空聚类与归一化漫展节点生成
系统 SHALL 自动分析来自不同 Coser、不同平台的非结构化 `cosplay_events`。通过物理空间（同城）和时间窗口过滤，结合模糊字符串相似度，将表象不同但实体相同的活动合并，自动生成规范化的 `normalized_events` 超级节点。
1. **时空第一级粗筛**：两个事件必须在相同的“城市”内。它们的确切日期（格式 `YYYY-MM-DD`）之间的差值 SHALL 满足 $\le 3$ 天（或其中至少一方为 `"未知"`）以进入比对。
2. **启发式相似度双阈值合并**：
   - 设待合并名称为 A，库中既存名称为 B。计算 Python 原生 `difflib.SequenceMatcher(None, A, B).ratio()` 的得分 $R$。
   - 当 $R \ge 0.75$ 时，系统 SHALL 判定二者为同一活动，将其归入已存在的归一化节点，并使用较长且更规范的一个作为标准名称。
   - 当 $0.5 \le R < 0.75$ 时，系统 SHALL 触发轻量级裁判智能体（Judge Agent）进行单次归一化裁决。裁决结果（同义词别名）SHALL 被物理缓存于别名表中，后续同类合并直接命中缓存，旁路裁判智能体。
   - 当 $R < 0.5$ 时，系统 SHALL 判定其为独立的新漫展，生成全新的超级节点。
3. **时空区间包络融合**：超级漫展节点的 `start_date` 和 `end_date` SHALL 物理定义为所有已关联的具体日期（不含 `"未知"`）的最小值与最大值。

#### Scenario: 成功自动融合 CP30 的模糊名称与日期区间
- **WHEN** 数据库录入了 3 个同城（上海）日程：Coser A（5.2，Comicup30）、Coser B（5.3，CP30）、Coser C（未知，上海CP30）
- **THEN** 系统自动在 `normalized_events` 中创建一个标准名称为 "Comicup 30" 的超级漫展节点，其举办日期范围自动计算为 `2026-05-02 至 2026-05-03`，并且这三个日程的 `normalized_event_id` 均正确指向该超级节点

### Requirement: 漫展集结命令行看板 (By-Event Summary)
Click 命令行工具必须在 `cosevent summary` 子命令中提供 `--by-event` 选项。
1. **聚合展示层级**：当指定 `--by-event` 时，看板必须以归一化漫展（`normalized_events`）为最外层大节点，依次以时间轴升序输出各漫展及其城市、场馆、时间范围。
2. **Coser 信息自动物理装配**：在每个漫展节点下，系统 SHALL 联查数据库，提取出所有参展 Coser 昵称（去幻觉约束，严禁 LLM 输出，完全通过 `cosers` 表关联物理装配）、参展日期、扮演角色以及摊位号。

#### Scenario: 漫展集结看板按时间升序成功打印
- **WHEN** 用户执行 `cosevent summary --by-event` 且数据库包含 2 个超级漫展（CP30 和萤火虫）
- **THEN** 终端标准输出首先优雅显示最早举办的漫展，并以嵌套缩进的形式展示该漫展下已登记的所有 Coser 列表，列出她们具体的扮演角色和摊位，退出码为 0
