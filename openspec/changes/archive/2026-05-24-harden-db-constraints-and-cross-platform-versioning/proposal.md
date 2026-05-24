## Why

系统在落地微博后缀版本化与日程软状态机后，在整体架构设计、可追溯性及一致性安全防线上暴露了以下四大核心隐患：
1. **多平台编辑版本不对称**：B站和小红书爬虫无原生 `edit_count` 字段，当 Coser 修改了这两个平台的行程内容时，去重机制会因无法感知版本提升而直接忽略该条博文，导致 B站和小红书的行程更新静默丢失。
2. **物理层状态机约束缺失**：`cosplay_events.status` 未在 SQLite 数据库层面建立 `CHECK (status IN ('未开始', '已结束', '已取消'))` 约束。若外部直接写库或由于拼写错误（如 `'已取销'`）写入非法值，数据库会无条件放行，进而在后续导出中产生静默逻辑漏洞。
3. **时区与创建时间不一致**：数据库建表时将 `created_at` 声明为 `DEFAULT CURRENT_TIMESTAMP`（UTC 时间），但在应用层插入时强行写入北京时间 `now_str`，一旦外部系统调用或字段缺省，表内将混入 UTC 字符串导致排序与审计时间线完全错乱。
4. **DeepSeekTransport 传输层改写缺乏兜底**：在 HTTP 拦截传输层直接覆写请求体并重算字节数属于高风险操作。在高噪声 Prompt、Emoji 复杂字符或 Chunked 分块传输下，若有细微字节偏差极易引发协议异常崩溃。

## What Changes

- **通用内容对比合成版本号机制**：在 `db_service.py` 保存博文时，增加正文哈希/文本内容对比。一旦检测到 B站或小红书的博文正文发生了变化，应用层自动合成并递增 `edit_count = stored_edit_count + 1`，对其 `post_id` 追加 `#v{edit_count}` 后缀录入。这使用户能够复用已有的多版本快照存储与未来行程跨版本级联软注销功能，实现跨平台版本控制的完美对称。
- **SQLite 状态机值域 CHECK 约束加固**：在 `db_models.py` 初始化定义中，为 `cosplay_events.status` 强力追加 `CHECK (status IN ('未开始', '已结束', '已取消'))` 值域约束。
- **时间列规范化接管（锁死北京时间）**：从 SQLite 建表定义中移除所有 `DEFAULT CURRENT_TIMESTAMP` 约束。时间字段的写入与更新完全收归应用层 Python 控制，强行锁死东八区北京时间格式 `YYYY-MM-DD HH:MM:SS`，彻底杜绝混淆。
- **DeepSeekTransport 安全熔断兜底与 ASCII 转义**：
  - 在 json_schema 改写过程中使用 `try...except` 进行严密保护，一旦遭遇序列化或分块传输等异常，系统瞬间安全降级熔断，直接回退并发送原始请求，保证高并发与高噪声环境下的绝对不崩溃。
  - 使用 `ensure_ascii=True` 转义汉字与多字节 Emoji，保证 HTTP 报文体在网络层 100% 的纯 ASCII 传输安全性。

## Capabilities

### New Capabilities
<!-- 无新增 Capability -->

### Modified Capabilities
- `content-scraping`: 增加跨平台内容对比与合成版本号控制规范，以及博文表去除默认 UTC 约束的时间线整顿。
- `event-extraction`: 状态机增加 SQLite CHECK 约束与北京时间锁死，且 DeepSeek 适配层引入严密的安全熔断降级兜底与 ASCII 转义传输保障。

## Impact

- **受影响的数据库结构**：`src/models/db_models.py` (加固 cosplay_events 表 status CHECK 约束，去除 DEFAULT CURRENT_TIMESTAMP)
- **受影响的数据服务**：`src/services/db_service.py` (实现多平台博文正文对比、合成版本号自增与 `#v` 后缀生成，统一规范时间写入)
- **受影响的传输拦截层**：`src/tools/llm_bridge.py` (添加 DeepSeekTransport 的 try-except 容错熔断和 ensure_ascii=True 转义)
- **测试套件**：`tests/test_cosevent.py` (增加合成版本号感知、CHECK 约束注入拦截、以及传输层熔断测试用例)
