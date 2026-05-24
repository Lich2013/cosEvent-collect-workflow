## 1. 数据库升级与爬虫编辑版本监听

- [x] 1.1 修改 `src/models/db_models.py` 的 `init_db` 方法，实现对 `raw_posts` 表的防静默自动追加 `edit_count` 和 `published_at` 列的自动热升级逻辑
- [x] 1.2 修改 `src/tools/weibo_scraper.py` 中的 `fetch_weibo_posts` 解析逻辑，提取并传参最新 `edit_count` 和 `created_at` (发表时间) 属性
- [x] 1.3 修改 `src/services/db_service.py` 中的 `save_raw_posts`，在发现 `(platform, post_id)` 已存在时，如果最新 `edit_count` 更大，则进行正文更新并重置 `is_analyzed = 0` 以激活下游重跑

## 2. 历史固化与未来行程增量对齐事务实现

- [x] 2.1 修改 `src/services/db_service.py` 中的 `save_extracted_events_transactional` 方法，获取系统当前日期作为判定基准
- [x] 2.2 在写入事务中对提取出的活动与已存活动进行时间轴分流：对于历史日程（`event_date` 小于系统今天）执行绝对的冻结保护；对于未来日程执行增量合并（Upsert）和状态对齐清理（DELETE 从最新列表中消失的未来日程）

## 3. 单元测试与回归验证

- [x] 3.1 在 `tests/test_cosevent.py` 中编写 `test_repost_incremental_update` 单元测试，通过 Mock 微博多次编辑与系统参考时间，验证历史行程固化、未来行程 Upsert、取消日程物理删除的正确性
- [x] 3.2 运行 `uv run pytest` 回归测试，确保全部 14 个测试用例 100% 成功通过

