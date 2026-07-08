## ADDED Requirements

### Requirement: LLM 暂时性失败不得触发结构性熔断
系统在增量分析博文时，必须且 SHALL 明确区分 LLM 暂时性失败与永久结构性失败。大模型 API 超时、供应商连接失败、所有并行 extractor 因接口故障失败、裁判模型接口抖动等不可证明为输入结构错误的异常，必须被归类为暂时性失败，并保持 `raw_posts.is_analyzed = 0` 以便下轮重试。只有 Pydantic 校验失败、应用层枚举断言失败、数据库完整性约束冲突等确定性结构错误，才能将 `raw_posts.is_analyzed` 标记为 `2`。

#### Scenario: 所有 extractor 临时失败后保留未分析状态
- **WHEN** 共识分析模式下所有并行 extractor 都因 API 超时或供应商错误失败
- **THEN** 系统记录错误审计并保持该博文 `raw_posts.is_analyzed = 0`

#### Scenario: 结构性入库校验失败后进入挂起状态
- **WHEN** LLM 返回的活动类型不在合法枚举内并在持久化前触发应用层断言
- **THEN** 系统回滚主事务并通过独立事务将该博文 `raw_posts.is_analyzed` 标记为 `2`

### Requirement: Agent System Prompt 模板化与统一时间注入
系统必须且 SHALL 将事件分析、预检分流、共识裁判、融合裁判、候选人核验等 Agent 的 System Instructions 统一放置在 `config/templates/` 目录中并通过 Jinja2 渲染。所有涉及时间判断的 Agent 模板必须注入统一的北京时间 `current_date`；事件分析类输入还必须包含博文 `published_at`，使相对日期推断与过期过滤具备一致时间基准。

#### Scenario: Triage Agent 使用模板化 System Prompt
- **WHEN** 系统创建 Triage Agent 对博文进行预检分流
- **THEN** 该 Agent 的 `instructions` 来自 `config/templates/` 中的模板渲染结果，并包含当前北京时间 `current_date`

#### Scenario: 候选人核验 Agent 使用模板化 System Prompt
- **WHEN** 系统创建候选人核验 Agent 分析候选人近期博文
- **THEN** 该 Agent 的 `instructions` 来自 `candidate_verify` 模板渲染结果，而非 Python 代码中的硬编码短句

### Requirement: 历史活动持久化硬兜底
系统在保存 LLM 提取结果前，必须且 SHALL 对标准日期格式 `YYYY-MM-DD` 的活动执行数据库层历史日期校验。若活动日期早于统一北京时间 `current_date`，系统不得将该活动以 `未开始` 状态写入 `cosplay_events`。默认行为必须为跳过该历史活动并记录审计日志；若未来引入审计保留模式，则保留记录也必须使用非未来语义状态，且不得进入未来日程流。

#### Scenario: LLM 返回历史活动时不写入未来日程
- **WHEN** 当前北京时间为 `2026-07-05`，LLM 返回活动日期为 `2026-07-01` 的活动
- **THEN** 系统跳过该活动，不向 `cosplay_events` 插入 `status = '未开始'` 的记录，并记录审计日志

#### Scenario: 未知日期活动仍按现有规则处理
- **WHEN** LLM 返回活动日期为 `未知` 且其他字段合法的活动
- **THEN** 系统继续按现有置信度、类型校验和融合规则处理该活动

### Requirement: 统一北京时间参考时钟
系统内所有与“今天”“当前日期”“冷冻窗口”“Prompt 当前日期”有关的逻辑必须且 SHALL 使用统一的北京时间参考时钟。该时钟必须可在测试中冻结或替换，以确保查询、导出、物化、Prompt 渲染和持久化判断在同一测试用例中使用相同日期。

#### Scenario: 分析、查询和模板渲染使用同一日期
- **WHEN** 测试将统一时钟冻结为 `2026-05-25`
- **THEN** 事件持久化、导出查询、物化冷冻窗口和 Agent 模板中的 `current_date` 均使用 `2026-05-25`
