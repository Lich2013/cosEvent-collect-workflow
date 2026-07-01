## 1. 数据库升级与热迁移

- [x] 1.1 在 `src/models/db_models.py` 中更新 `cosers` 表的创建 SQL，添加 `last_scraped_at TEXT` 字段定义
- [x] 1.2 在 `src/models/db_models.py` 的 `init_db()` 函数中添加自动列检测逻辑，并在 `last_scraped_at` 缺失时执行 `ALTER TABLE cosers ADD COLUMN last_scraped_at TEXT;` 升级
- [x] 1.3 在 `src/models/db_models.py` 中添加历史数据迁移 SQL，将 `coser_scrape_state` 的最晚抓取时间迁移至 `cosers.last_scraped_at`

## 2. 数据访问层与调度算法重构

- [x] 2.1 重构 `src/services/db/coser_repository.py` 的 `list_active_cosers_by_schedule` 函数，直接对 `cosers` 表按 `last_scraped_at ASC` 排序并限制获取 Top 名额（支持 platform 可选过滤）
- [x] 2.2 重构 `src/services/db/coser_repository.py` 的 `update_scrape_timestamp` 函数，将更新操作改为直接对 `cosers` 表的 `last_scraped_at` 列进行 UPDATE 写入

## 3. 工作流编排器调度简化

- [x] 3.1 简化 `src/services/workflow_orchestrator.py` 的 `run_scrape` 逻辑，去除复杂的三路指针交错弹出归并循环，改为直接拉取全局最久未碰过的活跃 Coser 队列，并根据平台 uid 绑定情况安全分发到对应的 Weibo / Bilibili / Xhs 抓取列表中

## 4. 单元测试套件适配

- [x] 4.1 更新 `tests/test_sliding_window.py` 里的 `test_sliding_window_scheduling_and_rotation`、`test_scrape_failure_still_updates_timestamp` 等测试，将其对 `coser_scrape_state` 表的直接断言修改为对 `cosers` 表 `last_scraped_at` 字段的断言
- [x] 4.2 重构 `test_coser_scrape_state_cascade_delete` 并在 `test_round_robin_batch_limit` 测试中将断言修改为匹配全局统一排序下的分发逻辑
- [x] 4.3 更新 `tests/test_fine_grained_scrape.py` 中的 `mock_list_active_cosers_by_schedule` 桩函数，使其全面支持 `platform="all"` 参数，并运行所有测试套件确保 100% 通过
