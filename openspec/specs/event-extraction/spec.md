## MODIFIED Requirements

### Requirement: 官方原生 OpenAI Agents SDK 智能体定义与 Pydantic 约束
分析模块必须直接采用官方原生 `openai-agents` 库进行 Agent 的定义与执行。系统必须支持通过 `ModelProvider` 机制动态切换底层 API 客户端及其参数。无论是单模型执行还是多模型共识裁决，最终输出结果的智能体必须声明 `output_type=FinalOutput`（通过 Pydantic 强校验），其中 `FinalOutput` 包含 `event_list: list[CosEvent]`。`CosEvent` 数据模型必须严格规定以下属性及类型：
- `event_name` (str): 漫展或活动名称
- `event_date` (str): 活动日期 (格式为 YYYY-MM-DD，如果未知则写'未知')
- `event_place` (str): 活动省份、城市及具体场馆地点
- `event_description` (str): Coser 出行规划或扮演角色的描述
- `confidence` (float): LLM 置信度分数 (0.0 到 1.0)
- `source_url` (str): 博文原始来源地址

系统在向大模型智能体提交博文分析请求时，**必须且 SHALL** 提取并显式注入博文发表日期时间（`published_at`）作为环境参考，以绝对保证相对日期描述（如“下周末”、“明天”、“这周末”）能够以博文发表时序为物理基准被高精度精准提取与对齐。注入的 `published_at` 必须且 SHALL 严格遵循“三层防御式时间对齐机制”，以杜绝因置顶微博历史编辑时间错位导致的绝对日期误判。系统提示词模板中必须且 SHALL 包含针对“陈年置顶微博历史编辑”的 Few-shot 坏例（Bad Case）约束指导，显式指导大模型强制以博文发布时间（`published_at`）为绝对年份基准推算，并根据系统参考时间（`current_date`）实施过期过滤。

#### Scenario: 智能体成功解析一段博文并输出结构化 Pydantic 实例
- **WHEN** 智能体（或最终裁判智能体）接收到包含 "7月5日去上海世博展览馆参加CP30，第一天出芙宁娜，欢迎来签售" 的博文及候选数据时
- **THEN** 最终返回合法的 `FinalOutput` 对象，其中包含活动名称 "CP30"、活动时间 "2026-07-05"、活动地点 "上海世博展览馆" 的结构化记录

#### Scenario: 智能体结合博文发表日期精准解析相对日期描述
- **WHEN** 传入的博文发表日期时间 `published_at` 为 `"2026-05-15 17:00:00"` (周五)，博文正文包含“下周末23号见咯”，智能体执行分析提炼时
- **THEN** 智能体成功结合发表日期基准，精确计算并将“下周末23号”对齐还原为绝对日期 `"2026-05-23"`，生成合规的 CosEvent 对象并返回


## ADDED Requirements

### Requirement: 增量式分析的三态状态机与结构性失败熔断规约
为了彻底避免因结构性/永久性校验失败导致的无限 LLM 重试黑洞，系统在进行增量博文分析时，必须将原先的布尔态更新标记硬化为三态状态机：
1. `raw_posts.is_analyzed` 状态值定义：
   - `0`: 未分析（默认值）。系统在捞取待分析博文时，**必须且 SHALL** 仅提取 `is_analyzed = 0` 的记录。
   - `1`: 分析并成功入库（含分析后确认无漫展计划的空列表情况）。
   - `2`: 分析挂起/结构性异常豁免。
2. 异常分流机制：
   - **暂时性异常 (Transient Failure)**：若分析过程中发生大模型 API 调用超时、接口抖动或数据库并发锁定等网络或物理瞬时异常，系统**必须且 SHALL** 保持该博文 `is_analyzed = 0`，以允许下轮调度重试。
   - **永久性/结构性异常 (Permanent Failure)**：若发生 Pydantic 数据验证错误 (`ValidationError`)、数据格式校验硬断言失败 (`AssertionError`) 或数据库唯一约束冲突 (`IntegrityError`) 等结构性硬异常，系统**必须且 SHALL** 执行主事务回滚（确保无污染），随后**必须且 SHALL** 开启一个独立轻量级事务将 `raw_posts.is_analyzed` 变更为 `2`，安全隔离异常数据，打破死循环。

#### Scenario: 智能体分析博文数据不合规触发熔断豁免
- **WHEN** 大模型对某条博文提炼成功，但在入库时由于 `validate_status` 校验失败抛出 `AssertionError` 时
- **THEN** 主活动数据插入事务自动 ROLLBACK，系统优雅记录错误审计，并开启一个独立的数据库小事务，将该博文的 `raw_posts.is_analyzed` 强制变更为 `2`

#### Scenario: 博文分析过程中发生暂时性网络异常不触发熔断
- **WHEN** 在分析一条博文时，因 API 接口超时或网络不可用抛出 `Exception` 时
- **THEN** 系统捕获异常后记录日志并跳过当前博文，该博文的 `raw_posts.is_analyzed` 保持为 `0` 状态，以便下轮重新运行分析

### Requirement: 读写强事务锁包覆规约
为了彻底杜绝高并发环境下因为读写“时空真空期”引发的脏读、数据主键冲突及死锁问题，系统在执行 `save_extracted_events_transactional` 事务写入时，**必须且 SHALL** 严格保证在进入事务隔离区后，立即升级写锁。
具体要求：
1. 在进入 `with conn:` 上下文后，**必须且 SHALL** 第一时间通过游标执行 `BEGIN IMMEDIATE;` 升级为强写锁，锁定所需物理资源。
2. 所有的 Coser 属性查询、历史行程比对的 `SELECT` 逻辑，**必须且 SHALL** 放入 `BEGIN IMMEDIATE;` 写锁的内部执行，彻底闭环读写全生命周期。
3. 任何一步异常均由 sqlite3 标准连接上下文管理器管理回滚。

#### Scenario: 强锁并发下成功比对并合并未来行程
- **WHEN** 并行执行多条提取结果保存，事务进入 `with conn` 隔离区时
- **THEN** 系统立即执行 `BEGIN IMMEDIATE;` 锁表，确保任何并发写被阻塞。此时在锁内执行 `SELECT` 获取最实时的行程状态，完成安全的 Upsert 合并
