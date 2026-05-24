## MODIFIED Requirements

### Requirement: 分析与状态更新的数据库事务原子性约束
系统必须确保增量分析的数据库完整性。每次执行单条博文的活动数据入库时，将解析出的多条 `cosplay_events` 活动记录插入数据库的操作，以及将对应 `raw_posts.id` 的 `is_analyzed` 更新为 `1` 的操作，**必须且 SHALL 统一在同一个数据库 SQL 事务中执行**。任何一步执行抛出异常，整个事务必须执行 ROLLBACK，以彻底避免局部写入失败引发的活动丢失或重复分析的灾难。为了避免与 Python 内置 `sqlite3` 的隐式自动事务管理冲突导致死锁或异常，系统**必须且 SHALL** 采用标准 Python 数据库连接上下文管理器 `with conn:` 自动且优雅地进行事务隔离、自动 Commit 与 Rollback 控制。系统**必须且 SHALL** 保证所有的 SQLite 游标（Cursor）操作包裹在 `with conn.cursor() as cursor:` 上下文管理器中，以确保资源使用完毕后被百分之百彻底安全释放，杜绝游标泄漏及 SQLite `database is locked` 死锁隐患。

#### Scenario: 数据库并发写游标安全闭合释放
- **WHEN** 增量保存活动执行完毕，游标上下文块退出时
- **THEN** 游标对象在数据库连接关闭前已被标准库自动执行 close() 释放，无连接残留

### Requirement: 多模型并行提取与裁判智能仲裁流水线
若快速预检确认可能包含漫展，系统**必须且 SHALL** 自动启动共识仲裁流水线：
1. **并行候选提取**：系统**必须且 SHALL** 以并发（异步并行）方式，调用 `analysis_pipeline.extractors` 中配置的多个大模型（如 OpenAI + DeepSeek），获取各自的活动候选列表。
2. **裁判仲裁与合并**：系统**必须且 SHALL** 通过 `analysis_pipeline.judge` 唤醒独立的裁判智能体（Judge Agent），该裁判使用高推理能力大模型（如 GPT-4o）。
3. 裁判智能体必须且 SHALL 接收：
   - 原始博文内容
   - **Token 降维精简候选数据**：提取模型给出的候选活动列表必须且 SHALL 在传输给裁判大模型前，过滤剥离所有冗余字段或多余键名，仅保留核心对比属性（`name`、`date`、`place`、`desc`、`conf`），以大幅节省 API 费用消耗并提升推理效率。
   - 当前系统参考时间 (格式为 YYYY-MM-DD)
4. 裁判智能体必须执行模糊合并（Fuzzy Merging）与去重：如果多方提取的活动日期相同且名称/地点相似，裁判必须将其融合成单一活动，合并时名称取最完整的，场馆地点取最具体详细的。
5. 最终裁判必须且 SHALL 强制输出通过 Pydantic `output_type=FinalOutput` 校验的数据。

#### Scenario: 降维精简提取数据成功输入裁判大模型
- **WHEN** 模型并行提取完成，准备组装裁判 Prompts 提示词时
- **THEN** 系统对 JSON 结构进行降维瘦身，去掉无效的冗余键值，终审输入 Prompt 大幅减负
