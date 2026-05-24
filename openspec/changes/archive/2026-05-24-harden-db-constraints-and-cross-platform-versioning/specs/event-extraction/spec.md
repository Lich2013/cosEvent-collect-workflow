## MODIFIED Requirements

### Requirement: 活动表结构定义与外键及状态机约束规范
系统必须在本地 SQLite 数据库中创建并维护提炼活动表 `cosplay_events`。该表必须严格按照以下 SQL 规范建立，以确保与原始博文的一对多物理外键关联，并在数据库物理层面及应用层集成状态机域值防御约束，同时包含用于直接导出 CSV 的 Coser 昵称和入库时间：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `raw_post_id` (INTEGER, NOT NULL, FOREIGN KEY REFERENCES `raw_posts`(`id`) ON DELETE CASCADE)
- `coser_name` (TEXT, NOT NULL) -- 冗余存储或缓存 Coser 昵称以便直接导出
- `event_name` (TEXT, NOT NULL)
- `event_date` (TEXT, NOT NULL)
- `event_place` (TEXT, NOT NULL)
- `event_description` (TEXT, NULL)
- `confidence` (REAL, DEFAULT 1.0)
- `source_url` (TEXT, NULL)
- `status` (TEXT, DEFAULT '未开始') -- 状态跟踪：'未开始' (有效), '已结束' (过期), '已取消' (软删除)
- `created_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)
- **数据库物理约束**：必须且 SHALL 声明值域检查规则 `CHECK (status IN ('未开始', '已结束', '已取消'))` 以保障核心资产数据状态一致性。

#### Coser 昵称数据流规则与时间强行锁死：
1. 智能体 Pydantic 输出对象 `CosEvent` 严禁且 SHALL NOT 包含 `coser_name` 字段，以防大模型产生幻觉或胡乱猜测。在将活动记录写入 SQLite `cosplay_events` 表时，数据库服务必须且 SHALL 根据原始博文的 `raw_posts.coser_id` 联查 `cosers.name`，并将此真实的昵称作为冗余字段注入到 `cosplay_events.coser_name` 进行存储。
2. 数据库中所有涉及 created_at, scraped_at 等时间列，在应用层或数据库默认值中统一规范为东八区北京时间格式 `YYYY-MM-DD HH:MM:SS`，杜绝 UTC 混淆隐患。

#### Scenario: 成功创建 cosplay_events 表并由系统自动注入 Coser 昵称与状态机约束
- **WHEN** 智能体提取成功，数据库服务执行入库查询 Coser 昵称，并向 `cosplay_events` 插入包含外键 `raw_post_id` 与状态 `status` 的记录时
- **THEN** 数据库操作成功，`cosplay_events.coser_name` 被正确填充为 "测试Coser"，状态默认被置为 "未开始"，物理 CHECK 约束生效并支持防拼写错误注入防御

### Requirement: 历史活动固化与未来日程增量软状态合并对齐
分析模块在将提炼后的活动列表存入 SQLite 数据库 `cosplay_events` 时，系统**必须且 SHALL** 遵循“历史行程冷冻保护 + 未来行程增量软取消对齐”的物理与业务约束，杜绝任何高危物理删除（DELETE），无损留存行程流转轨迹：
1. **历史日程定义与冷冻保护**：以系统执行分析时的当前参考日期（`YYYY-MM-DD`）为基准，凡是 `event_date` 早于当前日期的活动记录，一律被定义为“已发生的历史日程”。系统在任何增量重置分析过程中，**严禁且 SHALL NOT** 修改、覆盖或软/硬删除这些已办历史日程。
2. **跨版本级联软取消与未来日程增量对齐**：对于新版本的博文，在保存事务中，系统必须定位本博文既往全部历史版本的未办未来行程，并在同一个 SQL 事务中执行批量 `UPDATE`，将其 `status` 流转为 `'已取消'`（软删除）；同时，对于当前版本的未来日程执行增量对齐：
   - 如果新提取出的活动中，某项未来活动的名称、日期和具体场馆地点与数据库中已存的未来活动完全一致，系统执行 `UPDATE` 更新其描述、置信度和来源 URL，且保持其 `status` 为 `'未开始'`。
   - 如果新提取出的某项活动在数据库中不存在对应的 (name, date, place)，系统执行 `INSERT` 插入该项新日程，且状态被设定为 `'未开始'`。
   - 如果数据库中原本存有某项属于当前或未来的日程，但最新提取出的活动列表中已不包含此项日程（说明 Coser 在编辑博文时已将其改期或取消），系统**必须且 SHALL** 执行 `UPDATE cosplay_events SET status = '已取消' WHERE id = ?;` 进行软注销，绝对禁止进行物理 `DELETE`。

#### Scenario: 微博编辑更新时安全固化历史日程并级联软取消未来行程
- **WHEN** Coser 编辑了微博行程并重跑分析，重新提取出 3 个活动，其中包含 1 个已被判定为已发生历史日期（如 2026-01-10）的活动，和 2 个属于未来的活动，而数据库中原存有 1 个历史活动（2026-01-10）与 1 个被 Coser 替换取消的未来活动（2026-06-01）时
- **THEN** 数据库操作在同一个事务中原子级完成，原存的 2026-01-10 历史活动毫发无损且未被篡改，取消的 2026-06-01 未来日程在数据库中被安全标记为 `status = '已取消'`（绝无物理 DELETE 发生），最新的未来行程完成完美合并与入库，状态为 `'未开始'`

### Requirement: 多大模型供应商与端点动态注册
系统必须在 `config/settings.yaml` 中支持 `llm_providers` 配置块。配置块中允许注册多个独立的 LLM 供应商（如 `openai`、`deepseek`、`local_ollama` 等），且每个供应商必须包含：
- `base_url` (str): 该提供商的 OpenAI 兼容 API 端点
- `api_key` (str): 该提供商的 API 密钥（需支持类似 `${ENV_VAR}` 的环境变量占位符解析）
- `default_model` (str): 该提供商的默认模型名称

系统在初始化阶段必须加载这些供应商，并利用 `openai.AsyncOpenAI` 实例化为不同的客户端连接。系统必须实现自定义的 `ModelProvider`，使得 Agent 在执行 `Runner.run` 时，可以通过 `RunConfig(model_provider=...)` 动态分发路由到正确的端点、凭证和模型名。

同时，针对 **DeepSeek** 供应商，系统**必须且 SHALL** 在初始化客户端连接时集成自定义的 HTTP 拦截传输层（`DeepSeekTransport`），以拦截和拦截其发送的所有请求。如果请求头中为 application/json 且请求体含有 `"response_format": {"type": "json_schema"}`，拦截层**必须且 SHALL**：
1. 提取出 `json_schema` 定义并序列化为 JSON 字符串；
2. 找到请求消息列表中最后一条 `system`（或 `user`）角色的消息，将其 `content` 动态拼接追加结构化 Schema 约束提示词；
3. 将请求体中的 `response_format` 强制降级重写为 `"response_format": {"type": "json_object"}` (即 JSON Mode)，且使用 `ensure_ascii=True` 转义规避 Emoji 等多字节序列化偏差，确保传输层 100% 的纯 ASCII 属性安全；
4. **安全熔断机制**：降级与重写请求体的全生命周期必须且 SHALL 严密包裹在 `try...except` 容错控制块内。一旦拦截改写阶段捕获到任何序列化、类型转换或分块传输异常，系统必须且 SHALL 立即触发熔断机制，安全回退且无损发送原始客户端请求，防止网关层崩溃；
5. 重新计算并注入正确的 `Content-Length` 并发往 DeepSeek 官方 API，确保 Pydantic 强契约输出能够完美适配 DeepSeek 并防范 400 崩溃。

#### Scenario: 成功拦截并降级 DeepSeek 供应商且在异常时成功触发安全熔断
- **WHEN** 拦截层改写 DeepSeek 请求时发生任意 JSON 序列化异常
- **THEN** 拦截层自动捕获异常并熔断降级，原始完整请求照常安全发出，客户端正常获得返回数据而未发生崩溃
