## MODIFIED Requirements

### Requirement: 官方原生 OpenAI Agents SDK 智能体定义与 Pydantic 约束
分析模块必须直接采用官方原生 `openai-agents` 库进行 Agent 的定义与执行。系统必须支持通过 `ModelProvider` 机制动态切换底层 API 客户端及其参数。无论是单模型执行还是多模型共识裁决，最终输出结果的智能体必须声明 `output_type=FinalOutput`（通过 Pydantic 强校验），其中 `FinalOutput` 包含 `event_list: list[CosEvent]`。`CosEvent` 数据模型必须严格规定以下属性及类型：
- `event_name` (str): 漫展或活动名称
- `event_date` (str): 活动日期 (格式为 YYYY-MM-DD，如果未知则写'未知')
- `event_place` (str): 活动省份、城市及具体场馆地点
- `event_description` (str): Coser 出行规划或扮演角色的描述
- `confidence` (float): LLM 置信度分数 (0.0 到 1.0)
- `source_url` (str): 博文原始来源地址

系统在向大模型智能体提交博文分析请求时，**必须且 SHALL** 提取并显式注入博文发表日期时间（`published_at`）作为环境参考，以绝对保证相对日期描述（如“下周末”、“明天”、“这周末”）能够以博文发表时序为物理基准被高精度精准提取与对齐。

#### Scenario: 智能体成功解析一段博文并输出结构化 Pydantic 实例
- **WHEN** 智能体（或最终裁判智能体）接收到包含 "7月5日去上海世博展览馆参加CP30，第一天出芙宁娜，欢迎来签售" 的博文及候选数据时
- **THEN** 最终返回合法的 `FinalOutput` 对象，其中包含活动名称 "CP30"、活动时间 "2026-07-05"、活动地点 "上海世博展览馆" 的结构化记录

#### Scenario: 智能体结合博文发表日期精准解析相对日期描述
- **WHEN** 传入的博文发表日期时间 `published_at` 为 `"2026-05-15 17:00:00"` (周五)，博文正文包含“下周末23号见咯”，智能体执行分析提炼时
- **THEN** 智能体成功结合发表日期基准，精确计算并将“下周末23号”对齐还原为绝对日期 `"2026-05-23"`，生成合规的 CosEvent 对象并返回
