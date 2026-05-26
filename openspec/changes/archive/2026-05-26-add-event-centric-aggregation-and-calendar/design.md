## Context

当前系统能够全自动爬取多平台 Coser 博文并提取出结构化的 `cosplay_events` 日程。然而，现有的数据流只关注了“Coser 个人在什么时候去哪里”，无法提供“某个大漫展有谁会去”以及“什么时间段在哪些城市有漫展”的**超级节点聚合情报**。

本设计旨在引入归一化的漫展实体概念，利用启发式时空融合聚类算法将分散的单体日程并联起来，构建以“漫展活动（Event-centric）”为超级核心的数据血缘网络。

## Goals / Non-Goals

**Goals:**
- **物理表演进**：新增 `normalized_events` 表，保存归一化后的标准漫展名、城市和融合后的举办时间范围。在 `cosplay_events` 表中物理外键关联 `normalized_event_id`。
- **时空区间融合算法**：实现零重度外部依赖的聚类算法，使用 Python 原生 `difflib.SequenceMatcher` 过滤同城相近时间窗口的模糊漫展名称，计算相似度。
- **降维降本判定决策**：设计启发式双阈值过滤机制（$\ge 0.75$ 直接合并，$< 0.5$ 独立建站，临界区引入 LLM 裁判做二次确权），最大化节省 API 费用。
- **展现看板落地**：提供 `cosevent summary --by-event` 漫展集结看板与 `cosevent calendar` 全国展讯日历命令。
- **智能格式导出**：升级 `export` 服务，支持 Markdown 精美表格格式输出纯展讯日程。

**Non-Goals:**
- 不涉及主动爬行漫展官方购票平台或官网（完全通过 Coser 排班反向推导）。
- 不引入复杂的 PyTorch、TensorFlow 等向量检索框架。
- 不提供前端 Web Calendar UI，仅提供 CLI 和 Markdown 文件输出。

## Decisions

### Decision 1: 漫展超级节点时空指纹 (Event Fingerprint)
为了在 SQLite 快速进行唯一性索引和对齐，设计归一化漫展指纹机制：
- **物理指纹格式**：`fingerprint = LOWER(city) + "_" + LOWER(slugify(standard_name))`
- **判定规则**：如果两个漫展同城，且名称高度相似，系统会判断它们的日期区间。如果时间重叠或相差在 $\le 3$ 天内（或一方为未知），则融合为同个超级指纹节点；若时间差过大（如相差一月以上），则判定为不同届的独立指纹（如 `shanghai_cp29` 与 `shanghai_cp30`）。

### Decision 2: 启发式聚类双阈值与 LLM 裁判旁路机制 (Bypass Cascade)
为了兼顾高精准度与超低 Token 消耗，我们绝不让 LLM 对每一条日程都进行漫展聚合判定，而是使用启发式降级判定链：
1. **第一道防线：空间同城 + 时间滑动窗口**。非同城或时间差过大的，直接判定为独立 Event。
2. **第二道防线：基于 `difflib.SequenceMatcher` 的相似度比对**：
   - 设待合并漫展为 $A$，指纹库中同城既存漫展为 $B$。
   - 计算相似度 $R = \text{SequenceMatcher}(None, A, B).\text{ratio}()$。
   - **分支 1 ($R \ge 0.75$)**：判定为同一活动（如 "Comicup30" 和 "Comicup 30"），直接归一化并融合。
   - **分支 2 ($0.5 \le R < 0.75$)**：进入存疑区（如 "CP30" 与 "魔都同人祭"），调用轻量级裁判智能体（Judge Agent）判定。判定后将别名结果写入 `event_aliases` 物理缓存表，防止下一次再调用 LLM。
   - **分支 3 ($R < 0.5$)**：判定为全新独立活动，生成全新 `normalized_events` 条目。
3. **金牌裁判旁路**：如果同城缓存中没有相似度落在中间段的条目，系统**自动旁路裁判智能体**，实现 100% 零 API 额外消耗。

### Decision 3: 时空区间动态融合 (Outer Bounding Bounding Box)
由于各 Coser 日程发帖碎片化，超级 Event 节点的 `start_date` 与 `end_date` 应当是所有已关联日程中**确切日期的最大外包络区间**：
- 在保存日程写入事务中，获取该 `normalized_event_id` 下所有明确包含 `YYYY-MM-DD` 格式的 `event_date`。
- 计算极值：`start_date = MIN(event_date)`，`end_date = MAX(event_date)`。
- 对 `"未知"` 日期进行冷冻保留，不参与区间计算，但保持关联，以保证看板展现完整度。

---

## Risks / Trade-offs

### Risk 1: 日期描述极度模糊（如 Coser 只写了“五月端午假期”）
- **Description**: AI 提取出来的日期若无绝对年份和具体日期，直接参与极值计算会导致超级漫展节点日期区间失真。
- **Mitigation**: 
  - 只有格式为标准的 `YYYY-MM-DD` 日期才会被提取出来并参与 `start_date` 和 `end_date` 的计算。
  - 对于模糊的日期，以关联的形式展示在 Coser 详情中（如“参展日期：未知/5月端午”），不污染超级节点的标准举办范围。

### Risk 2: 数据库级事务写入碰撞与级联删除/软注销
- **Description**: 在多模型并行分析和写入时，如果有两条数据在极短时间内竞争写入同一个 `normalized_events` 并执行融合，会导致数据不一致。
- **Mitigation**: 
  - 所有漫展超级节点的判定、新增与级联更新，必须物理包裹在 `save_extracted_events_transactional` 同一个原生的 SQLite 数据库事务中。
  - 在写入时执行 `IMMEDIATE` 锁，从物理层面解决并发写碰撞。
