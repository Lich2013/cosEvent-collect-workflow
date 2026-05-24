## 1. 数据库热迁移与列追加

- [x] 1.1 修改 `src/models/db_models.py`，升级 `cosplay_events` 表定义支持 `status TEXT DEFAULT '未开始'`，并编写基于嗅探的安全 `ALTER TABLE` 在线自动热升级迁移逻辑

## 2. 微博爬虫版本控制与时间重锚重构

- [x] 2.1 修改 `src/tools/weibo_scraper.py` 中的微博解析封装体，在 `edit_count > 0` 时对 `post_id` 追加版本后缀 `#v{edit_count}`，并将其 `published_at` 重锚对齐为当前的北京抓取时间

## 3. 日程保存软状态机级联变更与导出适配

- [x] 3.1 修改 `src/services/db_service.py` 中的 `save_extracted_events_transactional` 事务，对于新版本写入，在事务中定位其既往全部版本的未办未来行程，将其 `status` 批量 `UPDATE` 为 `'已取消'`，固化保护历史日程不变
- [x] 3.2 修改 `src/services/db_service.py` 中的 `get_all_events` 行程导出 SQL 检索，追加 `status != '已取消'` 过滤以屏蔽废弃日程

## 4. 单元测试与系统验证

- [x] 4.1 在 `tests/test_cosevent.py` 中编写与升级完备的软状态机级联转移单元测试，并在本地虚拟环境下执行 `uv run pytest` 验证全部测试通过
