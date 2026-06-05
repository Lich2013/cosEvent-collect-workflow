## Why

目前系统的日常抓取阶段（`scrape` 命令）采用的是全量串行模式。每次启动任务时，都会一次性加载数据库中所有激活状态的 Coser（当前已达 114 人）并依次拉取他们的平台动态。

由于 B 站（以及其他社交平台）对 API 请求频率有着极高且严厉的安全风控，这种一次性连续查询 114 位用户动态的行为极易触发拦截（如超时、验证码拦截、-352 错误等）。根据观测，在特定窗口期内跑满 60 个左右的 Coser 就会被风控阻断。为了降低单次请求的饱和度并实现细粒度的平摊访问，必须引入**有状态时间滑动窗口分批调度（Stateful Sliding Window Batching）**机制，每次仅处理最久未更新的一部分 Coser，从而平滑地通过多轮定时任务轮询完整库。

## What Changes

- **新增平台专属爬取状态表 `coser_scrape_state`**：
  为避免不同平台（微博、B站、小红书）因为抓取周期、成功率或参数不对称导致调度干扰，新建一张状态表，联合主键为 `(coser_id, platform)`，记录各平台独立的最后爬取时间 `last_scraped_at`。
- **引入单人单次即时提交（Immediate Commit）机制**：
  由于爬取单人耗时较长（秒级），如果在批量任务中途进程被杀或因网络崩溃中断，若采用末端统一提交会导致已爬取的进度丢失，下次依然会重复爬取相同的人。因此，每抓取（或尝试抓取）完一位 Coser，系统必须**立即**在一个短事务中更新并 `COMMIT` 其对应的 `last_scraped_at`，最大限度保障已执行进度的落盘。
- **数据库开启 WAL 模式 (Write-Ahead Logging)**：
  由于采用了“单人单次即时提交”机制，频繁的微小事务会增加 SQLite 的磁盘 I/O 和文件锁争用。通过在数据库连接初始化时开启 `PRAGMA journal_mode=WAL;`，实现读写并发（写不阻读，读不放锁），大幅提升微事务的并发写入性能，彻底消除锁库隐患。
- **CLI scrape 增加批次限制与调度轮转**：
  - `main.py scrape` 增加 `--batch-size` 参数（默认 30），在抓取时优先选择满足平台 UID 且 `last_scraped_at` 最久未更新（或者为 `NULL`）的 Coser 执行抓取。
  - 支持强制单人更新（`--name`）旁路时间窗限制，但完成后仍同步更新时间戳。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `content-scraping`: 抓取工作流由全量同步升级为基于时间戳的滑动窗口分批调度，支持分平台时间戳管理、单人单写进度落盘、以及 SQLite WAL 读写并发，降低接口风控阻断率，提升分布式运行的稳定性。

## Impact

- **数据库层 (Database & Models)**：
  - `src/models/db_models.py`：在 `init_db()` 中创建 `coser_scrape_state` 表，并在 `get_db_connection()` 中默认追加 `PRAGMA journal_mode=WAL;`，支持自动热迁移。
  - `src/services/db/coser_repository.py`：新增支持平台过滤、基于 `last_scraped_at` 升序排列并限制 `LIMIT` 捞取 Coser 的查询函数；新增单条更新 `last_scraped_at` 的即时写入函数。
- **编排与逻辑层 (Orchestration & CLI)**：
  - `src/services/workflow_orchestrator.py`：改造 `run_scrape`，使其根据指定平台和 `batch_size` 过滤队列，并在遍历中单步完成数据保存和时间戳提交。
  - `src/main.py`：`scrape` 命令行增加 `--batch-size` 参数绑定。
