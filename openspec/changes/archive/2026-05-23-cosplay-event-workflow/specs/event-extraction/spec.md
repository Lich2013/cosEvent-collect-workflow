## ADDED Requirements

### Requirement: 官方原生 OpenAI Agents SDK 智能体定义与 Pydantic 约束
分析模块必须直接采用官方原生 `openai-agents` 库进行 Agent 的定义与执行。智能体 `event_agent` 必须声明 `output_type=FinalOutput`（通过 Pydantic 强校验），其中 `FinalOutput` 包含 `event_list: list[CosEvent]`。`CosEvent` 数据模型必须严格规定以下属性及类型：
- `event_name` (str): 漫展或活动名称
- `event_date` (str): 活动日期 (格式为 YYYY-MM-DD，如果未知则写'未知')
- `event_place` (str): 活动省份、城市及具体场馆地点
- `event_description` (str): Coser 出行规划或扮演角色的描述
- `confidence` (float): LLM 置信度分数 (0.0 到 1.0)
- `source_url` (str): 博文原始来源地址

#### Scenario: 智能体成功解析一段博文并输出结构化 Pydantic 实例
- **WHEN** 智能体接收到包含 "7月5日去上海世博展览馆参加CP30，第一天出芙宁娜，欢迎来签售" 的博文时
- **THEN** 智能体返回合法的 `FinalOutput` 对象，其中包含活动名称 "CP30"、活动时间 "2026-07-05"、活动地点 "上海世博展览馆" 的结构化记录

### Requirement: 活动表结构定义与外键及身份关联规范
系统必须在本地 SQLite 数据库中创建并维护提炼活动表 `cosplay_events`。该表必须严格按照以下 SQL 规范建立，以确保与原始博文的一对多物理外键关联，并包含用于直接导出 CSV 的 Coser 昵称和入库时间：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `raw_post_id` (INTEGER, NOT NULL, FOREIGN KEY REFERENCES `raw_posts`(`id`) ON DELETE CASCADE)
- `coser_name` (TEXT, NOT NULL) -- 冗余存储或缓存 Coser 昵称以便直接导出
- `event_name` (TEXT, NOT NULL)
- `event_date` (TEXT, NOT NULL)
- `event_place` (TEXT, NOT NULL)
- `event_description` (TEXT, NULL)
- `confidence` (REAL, DEFAULT 1.0)
- `source_url` (TEXT, NULL)
- `created_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)

#### Coser 昵称数据流规则：
智能体 Pydantic 输出对象 `CosEvent` 严禁且 SHALL NOT 包含 `coser_name` 字段，以防大模型产生幻觉或胡乱猜测。在将活动记录写入 SQLite `cosplay_events` 表时，数据库服务必须且 SHALL 根据原始博文的 `raw_posts.coser_id` 联查 `cosers.name`，并将此真实的昵称作为冗余字段注入到 `cosplay_events.coser_name` 进行存储。

#### Scenario: 成功创建 cosplay_events 表并由系统自动注入 Coser 昵称
- **WHEN** 智能体提取成功，数据库服务执行入库查询 Coser 昵称，并向 `cosplay_events` 插入包含外键 `raw_post_id` 的记录时
- **THEN** 数据库操作成功，`cosplay_events.coser_name` 被正确填充为 "测试Coser"，与原始博文的外键关联约束生效

### Requirement: 动态置信度过滤阈值配置机制
系统必须在分析和保存活动记录时，支持通过命令行配置选项 `--confidence-threshold` (FLOAT, 默认 0.0) 以及在 `settings.yaml` 中配置 `confidence_threshold` 选项。智能体所提炼出的活动中，只有 `confidence` 大于或等于该置信度阈值的记录才允许被存入数据库并包含在后续导出中。低于该阈值的提取结果必须被直接过滤或弃用。

#### Scenario: 成功过滤置信度低于指定阈值的提取活动
- **WHEN** 用户执行 `cosevent analyze --confidence-threshold 0.8` 且智能体返回置信度为 0.6 的 Cosplay 活动时
- **THEN** 该条活动在入库阶段被自动过滤弃用，未写入数据库 `cosplay_events` 中

### Requirement: 动态 Jinja2 Prompts 模板加载与系统时间注入
系统必须将智能体指令 (`instructions`) 抽离，放置在单独的文件 `config/templates/event_analysis.jinja2` 中进行管理。当运行分析任务时，系统必须使用 Jinja2 模板引擎动态渲染指令，并必须在渲染时传入**当前系统时间**作为变量（例如 `Current Date: 2026-05-23`），以使 LLM 能够准确过滤已发生的历史过期活动，仅抓取发生在当前时间之后的有效活动。

#### Scenario: 分析动态时精准过滤早于当前系统日期的过期活动
- **WHEN** 传入博文中包含 2025 年历史漫展信息且当前系统时间渲染为 "2026-05-23" 时
- **THEN** 智能体识别到该活动已经结束，最终输出的 `event_list` 中不包含此过期漫展

### Requirement: 智能体输出容错重试机制与降级
若 LLM 在执行过程中返回了非法格式、缺少必要字段或未通过 Pydantic 模型的数据类型验证，系统必须自动捕获该异常。系统不能直接崩溃中断，必须在记录 `WARNING` 日志后，自动将上一次调用产生的报错信息作为提示附加到下一轮对话中，重新发起大模型调用。重试次数上限必须设置为 3 次，若 3 次后仍失败，则应标记该博文分析失败并继续处理下一条。

#### Scenario: LLM 输出类型不匹配触发自动重试并最终修复格式
- **WHEN** LLM 首次返回的 `event_date` 格式不合规导致 Pydantic 校验抛出异常时
- **THEN** 系统自动捕获异常，并在控制台记录重试警告，附加报错反馈自动重新发起 LLM 调用，并在重试轮次中成功生成合规的格式化活动

### Requirement: 异步增量式分析与状态对齐
分析模块必须在物理上与爬虫解耦，通过独立的 `cosevent analyze` 命令运行，仅从本地 SQLite 数据库中提取满足 `is_analyzed = 0` 条件的博文记录进行增量分析。一旦某条博文被成功分析（无论提取出多少个活动，或者判断为无活动）后，系统必须同步在 `raw_posts` 表中更新其对应的 `is_analyzed` 状态字段为 `1`。已标记为 `1` 的记录在后续分析中必须被自动跳过，实现彻底的增量运行。

#### Scenario: 再次启动分析命令时仅处理未分析过的增量博文
- **WHEN** 数据库中包含 10 条博文记录，其中 7 条 `is_analyzed = 1`，3 条 `is_analyzed = 0`，用户执行分析提取命令时
- **THEN** System 查询并交给 LLM 分析的博文只有这 3 条未分析的增量记录，完成后其在数据库中的状态更新为 `is_analyzed = 1`

### Requirement: 分析与状态更新的数据库事务原子性约束
系统必须确保增量分析的数据库完整性。每次执行单条博文的活动数据入库时，将解析出的多条 `cosplay_events` 活动记录插入数据库的操作，以及将对应 `raw_posts.id` 的 `is_analyzed` 更新为 `1` 的操作，**必须且 SHALL 统一在同一个数据库 SQL 事务中执行**。任何一步执行抛出异常，整个事务必须执行 ROLLBACK，以彻底避免局部写入失败引发的活动丢失或重复分析的灾难。

#### Scenario: 多活动插入中途失败触发完整事务回滚
- **WHEN** 智能体对某条博文提炼出 3 个活动，前 2 个写入成功，第 3 个由于数据库死锁或长度约束插入失败，导致抛出异常时
- **THEN** 数据库事务执行回滚，`cosplay_events` 中未写入关于该博文的任何活动记录，且对应的 `raw_posts` 中 `is_analyzed` 状态值依旧为 0
