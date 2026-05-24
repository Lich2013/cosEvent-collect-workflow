## MODIFIED Requirements

### Requirement: 官方原生 OpenAI Agents SDK 智能体定义与 Pydantic 约束
分析模块必须直接采用官方原生 `openai-agents` 库进行 Agent 的定义与执行。系统必须支持通过 `ModelProvider` 机制动态切换底层 API 客户端及其参数。无论是单模型执行还是多模型共识裁决，最终输出结果的智能体必须声明 `output_type=FinalOutput`（通过 Pydantic 强校验），其中 `FinalOutput` 包含 `event_list: list[CosEvent]`。`CosEvent` 数据模型必须严格规定以下属性及类型：
- `event_name` (str): 漫展或活动名称
- `event_date` (str): 活动日期 (格式为 YYYY-MM-DD，如果未知则写'未知')
- `event_place` (str): 活动省份、城市及具体场馆地点
- `event_description` (str): Coser 出行规划或扮演角色的描述
- `confidence` (float): LLM 置信度分数 (0.0 到 1.0)
- `source_url` (str): 博文原始来源地址

#### Scenario: 智能体成功解析一段博文并输出结构化 Pydantic 实例
- **WHEN** 智能体（或最终裁判智能体）接收到包含 "7月5日去上海世博展览馆参加CP30，第一天出芙宁娜，欢迎来签售" 的博文及候选数据时
- **THEN** 最终返回合法的 `FinalOutput` 对象，其中包含活动名称 "CP30"、活动时间 "2026-07-05"、活动地点 "上海世博展览馆" 的结构化记录

---

## ADDED Requirements

### Requirement: 多大模型供应商与端点动态注册
系统必须在 `config/settings.yaml` 中支持 `llm_providers` 配置块。配置块中允许注册多个独立的 LLM 供应商（如 `openai`、`deepseek`、`local_ollama` 等），且每个供应商必须包含：
- `base_url` (str): 该提供商的 OpenAI 兼容 API 端点
- `api_key` (str): 该提供商的 API 密钥（需支持类似 `${ENV_VAR}` 的环境变量占位符解析）
- `default_model` (str): 该提供商的默认模型名称

系统在初始化阶段必须加载这些供应商，并利用 `openai.AsyncOpenAI` 实例化为不同的客户端连接。系统必须实现自定义的 `ModelProvider`，使得 Agent 在执行 `Runner.run` 时，可以通过 `RunConfig(model_provider=...)` 动态分发路由到正确的端点、凭证和模型名。

#### Scenario: 动态分发路由到指定的大模型端点
- **WHEN** 智能体在 `settings.yaml` 中配置了 DeepSeek 端点并使用模型名 "deepseek/deepseek-chat" 执行提取时
- **THEN** 智能体框架使用配置 of DeepSeek 密钥和 Base URL 发送异步 HTTP 请求，成功获取结果

### Requirement: 快速预检分流过滤机制 (Triage Filter)
在共识（Consensus）分析模式下，为了控制 Token 费用和优化系统性能，系统必须引入基于 Pydantic 强契约输出的快速预检（Triage）过滤。
1. 系统必须声明轻量级 Pydantic 结构 `TriageOutput`，包含：
   - `has_event` (bool): 标识博文中是否包含任何未来的 Cosplay 活动规划
   - `candidate_events` (list[str]): 简要的活动候选名称列表
2. Triage 智能体在实例化时，必须声明 `output_type=TriageOutput`，利用官方 SDK 自动捕获校验异常并执行最多 3 次纠错重试，禁止采用纯文本弱解析。
3. 若首轮预检返回的 `has_event` 为 `False` 或候选活动列表为空，系统必须且 SHALL **立即终止分析流**，跳过后续所有提取模型与裁判大模型的调用。
4. 只有当首轮快速预检返回的 `has_event` 为 `True` 且包含候选活动时，系统才被允许唤醒后续的多模型并行提取与仲裁流程。

#### Scenario: 预检发现日常碎碎念博文并通过 Pydantic 规整结果终止后续 LLM 链路
- **WHEN** 增量博文内容为 "今天晚饭吃了黄焖鸡，真香！" 且首轮预检返回的 TriageOutput.has_event 校验为 False 时
- **THEN** 提取流水线立即终止，未调用其他提取器及裁判模型，外部处理单元正确捕获空列表并将该博文 `is_analyzed` 状态原子的更新为 1

### Requirement: 多模型并行提取与裁判智能仲裁流水线
若快速预检确认可能包含漫展，系统必须自动启动共识仲裁流水线：
1. **并行候选提取**：系统必须以并发（异步并行）方式，调用 `analysis_pipeline.extractors` 中配置的多个大模型（如 OpenAI + DeepSeek），获取各自的活动候选列表。
2. **裁判仲裁与合并**：系统必须通过 `analysis_pipeline.judge` 唤醒独立的裁判智能体（Judge Agent），该裁判使用高推理能力大模型（如 GPT-4o）。
3. 裁判智能体必须接收：
   - 原始博文内容
   - 提取模型 A 给出的候选活动列表
   - 提取模型 B 给出的候选活动列表
   - 当前系统参考时间 (格式为 YYYY-MM-DD)
4. 裁判智能体必须执行模糊合并（Fuzzy Merging）与去重：如果多方提取的活动日期相同且名称/地点相似，裁判必须将其融合成单一活动，合并时名称取最完整的，场馆地点取最具体详细的。
5. 最终裁判必须且 SHALL 强制输出通过 Pydantic `output_type=FinalOutput` 校验的数据。

#### Scenario: 裁判智能体对多个模型的提取结果进行模糊合并去重
- **WHEN** 模型 A 提供候选 "CP30 芙宁娜"，模型 B 提供候选 "CP30 动漫展 芙宁娜 上海国家会展中心"，由裁判进行对比审判时
- **THEN** 裁判在 FinalOutput 中仅输出一条合并后的最佳记录，活动名称为 "CP30 动漫展"，活动地点为 "上海国家会展中心"

### Requirement: 大模型接口单侧故障的优雅降级与裁判旁路 (Judge Bypass)
多模型共识分析流水线必须具备极高的容错性与成本自适应控制。在执行并行提取时：
1. 如果由于网络或接口限流等原因导致其中一个 LLM 提取器抛出异常，系统必须且 SHALL 自动捕获该单侧异常并记录黄色 `WARNING` 日志，绝对不允许整个 CLI 任务崩溃。
2. 如果至少有一个提取器运行成功，系统必须降级为“单侧信任模式”。在此模式下，系统必须**直接旁路（跳过）裁判智能体**以避免产生不必要的二次 API 费用开销，直接将成功一方的草稿提炼数据作为最终活动列表返回。
3. 如果所有提取模型全部发生异常，系统必须抛出错误触发原子性事务回滚，标记本条博文提取失败并记录审计日志，随后优雅跳过以继续处理下一条增量博文。

#### Scenario: 并行提取单侧故障自动旁路裁判大模型
- **WHEN** 并行提取中 DeepSeek 超时报错但 OpenAI 成功返回，系统启动降级处理时
- **THEN** 控制台记录降级警告，系统跳过 Judge 裁决大模型，直接返回 OpenAI 的活动列表并成功入库
