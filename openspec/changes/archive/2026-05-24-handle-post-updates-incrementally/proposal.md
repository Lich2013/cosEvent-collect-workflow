## Why

微博等社交平台允许 Coser 对已发布的博文进行编辑更新（例如在原有行程博文中追加新的排班表或修改出席日期）。目前系统的去重机制会无条件忽略已存在 `post_id` 的博文，导致这些重要的行程更新无法被捕获。

此外，直接清空旧活动重置分析会清除已发生的历史行程数据，破坏历史记录的完整性。因此，需要引入基于微博 `edit_count` 的修改监听机制，并实施“历史冷冻固化 + 未来行程增量对齐”的合并策略。

## What Changes

- **数据库字段升级**：向 `raw_posts` 表中新增 `edit_count` (INTEGER, 默认 0) 和 `published_at` (TEXT, 默认 NULL) 两个列，以便进行精确的版本控制和发表时间定位。
- **微博爬虫编辑监听**：解析拦截响应中的 `edit_count` 和原始发表时间 `created_at`，如果检测到抓取到的 `edit_count` 大于数据库中已存的数值，则对内容进行更新，重置 `is_analyzed = 0` 激活重跑。
- **历史固化与未来增量合并**：重构 `DBService.save_extracted_events_transactional` 事务写入逻辑：
  - 绝对保留博文关联的历史活动（`event_date` 小于当前系统日期的记录），保护已发生数据不丢失。
  - 对于未来的活动日程（`event_date` 大于等于当前系统日期的记录），与新提取出的列表执行增量合并（存在相同名称、日期和地点则更新描述，若新列表中消失则说明被取消/改期，执行安全清理）。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `content-scraping`: 抓取并存储 `edit_count` 和 `published_at` 字段，优化查重校验，触发编辑更新机制。
- `event-extraction`: 数据库活动写入流程重构，遵循“历史固化 + 未来对齐”的增量合并规范。

## Impact

- **修改的模块**：
  - [db_models.py](file:///Users/lich/work/cosEvent-workflow/src/models/db_models.py)（初始化及 Schema 定义）
  - [db_service.py](file:///Users/lich/work/cosEvent-workflow/src/services/db_service.py)（修改 `save_raw_posts` 和事务写入逻辑）
  - [weibo_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/weibo_scraper.py)（提取并传参 `edit_count` 和 `published_at`）
- **数据库影响**：需要对 SQLite 的 `raw_posts` 表追加 `edit_count` 和 `published_at` 列。
- **测试影响**：在 [test_cosevent.py](file:///Users/lich/work/cosEvent-workflow/tests/test_cosevent.py) 中新增增量合并与历史冷冻固化验证的回归测试。
