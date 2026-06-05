## 1. 数据库底层与 WAL 模式支持

- [x] 1.1 修改 `src/models/db_models.py` 中的 `get_db_connection()` 函数，在建立连接后立即执行 `PRAGMA journal_mode=WAL;`。
- [x] 1.2 修改 `src/models/db_models.py` 中的 `init_db()`，添加创建 `coser_scrape_state` 表的 SQL 定义，并确保其支持 `IF NOT EXISTS`。
- [x] 1.3 在 `init_db()` 的升级迁移逻辑中，自动创建该表以兼容旧库的就地热升级。

## 2. 数据仓库层（Repository）接口实现

- [x] 2.1 在 `src/services/db/coser_repository.py` 中新增 `list_active_cosers_by_schedule(platform: str, limit: int) -> list[dict]`，通过 `LEFT JOIN coser_scrape_state` 并按照 `last_scraped_at ASC`（`NULL` 优先）对 Coser 进行检索。
- [x] 2.2 在 `src/services/db/coser_repository.py` 中新增 `update_scrape_timestamp(coser_id: int, platform: str) -> bool`，即时更新对应平台的时间戳（采用 `INSERT OR REPLACE` 逻辑以支持首次写入）。

## 3. 工作流与 CLI 接口改造

- [x] 3.1 改造 `src/services/workflow_orchestrator.py` 中的 `run_scrape`：
  - 支持传入 `batch_size`（覆盖默认的全量检索）。
  - 若未指定具体的 `coser_name`，则针对所选的平台分别调用 `list_active_cosers_by_schedule` 获取需要抓取的 batch。
  - 在遍历处理每个 Coser 的具体平台时，无论成功或失败均在 `finally` 块中立即调用 `update_scrape_timestamp` 进行状态回写，确保微事务即时提交。
- [x] 3.2 改造 `src/main.py` 中的 `scrape` 命令，支持 `--batch-size` 参数（类型为 int，默认 30），并传递给底层编排器。

## 4. 自动化测试与校验

- [x] 4.1 在 `tests/test_cosevent.py` 或独立的测试文件中，新增针对滑动窗口的单元测试：
  - 测试从未爬取到已爬取的排序与轮转变化。
  - 测试异常抛出后，时间戳是否能够照常更新落盘。
  - 测试 `coser_scrape_state` 的级联物理删除（`ON DELETE CASCADE`）。
- [x] 4.2 运行项目的所有测试用例，确保修改不破坏已有流程，且全部绿灯通过。
