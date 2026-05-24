## Why

修复微博抓取链接由于 `bid` 缺失导致的 `None` 字段空值污染，并彻底规范和对齐数据库中所有时间相关字段（包括爬虫发布的 `published_at` 与底层数据库审计字段 `scraped_at` / `created_at` 等）的格式与时区（统一锁定为东八区北京时间与 `YYYY-MM-DD HH:MM:SS` 格式），确保系统的数据可读性、时序排序精确性与整洁一致性。

## What Changes

- **微博详情链接修复**：在 WeiboScraper 中废弃已失效的 `bid` 参数，优先从 API 响应中提取 `mblogid` 短码生成微博详情页链接，降级使用 `idstr` 或 `id` 进行拼装，彻底清除 `https://weibo.com/{uid}/None` 脏数据。
- **微博发布日期格式解析对齐**：使用标准库解析微博时间（如 `"Thu Jan 01 17:12:59 +0800 2026"`），强制转为东八区北京时区并标准化格式化为 `"YYYY-MM-DD HH:MM:SS"`，与系统其他时间字段在表现格式上完美对齐。
- **底层数据库时间时区锁死对齐**：废弃 SQLite 原生的 UTC 时间 `DEFAULT CURRENT_TIMESTAMP` 占位，所有表的审计列（如 `cosers.created_at`, `raw_posts.scraped_at`, `cosplay_events.created_at`）均在 Python 应用层插入/更新时，统一强行以东八区北京时区当前日期时间字符串的形式写入，实现数据库物理时间维度的 100% 对齐。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `content-scraping`: 微博 URL 正确拼接规范与发布时间格式化。
- `event-extraction`: 数据库各表审计列北京时区时间对齐与入库格式规范。

## Impact

- **修改的模块**：
  - `weibo_scraper.py`（修复 URL 与微博发布日期格式对齐）
  - `db_service.py`（在增量分析保存与 Coser 实体操作等底层写入中，显式传入统一的北京时间字符串以覆盖 SQLite 默认 UTC 占位）
  - `db_models.py`（升级表设计，确保新表或已存表时间相关列描述与实际数据对齐）
- **测试影响**：在 `test_cosevent.py` 中，断言 and 单元测试需增加对正确微博链接与北京时区全表时间的一致性验证。
