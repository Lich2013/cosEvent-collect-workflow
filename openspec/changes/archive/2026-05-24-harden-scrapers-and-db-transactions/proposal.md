## Why

为解决系统在跨时区环境部署、数据库连接游标未彻底关闭、大模型共识仲裁 Token 冗余开销过大等潜在缺陷和性能隐患，必须对现有爬虫模块、数据库底层交互机制及裁判智能体传输负载进行一次全面的代码加固与资源优化。

## What Changes

- **微博转发原作者 None 容错**：在解析 `retweeted_status` 时，使用 Python `or` 逻辑强制兜底 `screen_name` 为 `"原作者"`，避免因用户注销/封禁导致 `@None` 的解析噪声干扰。
- **跨时区时间轴对齐**：强制全局采用东八区北京时间 (UTC+8) 获取系统日期，避免 CI 管道或云服务器以 UTC 时间运行引起时间轴分流的一天偏差。
- **B站动态发布时间戳补充及无文本空动态过滤**：提取拦截响应中 `pub_ts` 时间戳并格式化写入 `raw_posts.published_at`，提高 B 站数据的审计性；同时过滤无文本（纯视频/图片）动态以防止空值入库。
- **数据库连接与游标彻底释放**：全面重构 `DBService` 底层 SQL 操作，统一采用 `with conn:` 事务管理上下文和 `with conn.cursor() as cursor:` 自动关闭游标，防止并发下的 SQLite 连接泄漏与锁死。
- **共识裁判 Token 降维精简**：在将模型候选草稿送入裁判智能体前，精简其 JSON 结构（仅传入关键去重比对属性），大幅节省 API 费用并提升推理精度。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `content-scraping`: 微博/B站提取时间与空作者字段防御加固，时区对齐要求。
- `event-extraction`: 数据库连接多游标彻底闭合防护规范，以及仲裁裁判输入草稿字段的 Token 降维精简设计。

## Impact

- **修改的模块**：
  - [weibo_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/weibo_scraper.py)（转发原作者防护、时区对齐）
  - [bilibili_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/bilibili_scraper.py)（提取 `pub_ts` 填补时间）
  - [db_service.py](file:///Users/lich/work/cosEvent-workflow/src/services/db_service.py)（重构 `with conn.cursor() as cursor:` 及北京时间分流）
  - [event_agent.py](file:///Users/lich/work/cosEvent-workflow/src/agents/event_agent.py)（精简裁判 Prompt Payload）
- **数据库影响**：无表结构变动，大幅增强底层事务操作并发安全性。
- **测试影响**：[test_cosevent.py](file:///Users/lich/work/cosEvent-workflow/tests/test_cosevent.py) 中新增对应的北京时区对齐及 None 容错 Mock 单元测试。
