## Context

当前日常抓取阶段采用全量串行模式。由于 B 站的风控策略会在短时间内对高频的详情请求或检索进行安全校验拦截（如 `-352` 错误或连接超时），在同一执行周期内连续抓取 114 个 Coser 会迅速耗尽接口配额，导致后半段的 Coser 抓取全部失败。需要实现有状态的时间滑动窗口分批调度，每次任务执行时只挑选最久未被爬取的部分 Coser。

## Goals / Non-Goals

**Goals:**
- 在数据库中新增 `coser_scrape_state` 状态表，能够细粒度管理微博、B站、小红书每个 Coser 独立的抓取时间戳。
- 重构 Coser 捞取逻辑，支持通过指定平台从 `cosers` 联查状态表，获取 `last_scraped_at` 升序排列（`NULL` 优先）的活跃 Coser，并支持通过参数控制单次批次大小。
- 引入单步即时写入机制，确保任意一个 Coser 完成（或失败）后，立即向数据库提交更新该平台的时间戳，不丢失中途进度。
- 默认将本地 SQLite 连接升级为 WAL 模式，确保频繁的单步事务提交不发生数据库死锁。

**Non-Goals:**
- 不修改博文提炼（`analyze`）阶段大模型 Agent 核心处理逻辑。
- 不针对微博和小红书修改具体的页面拦截器逻辑（仅改造其上层的列表调度与时间戳更新）。

## Decisions

### 1. 字段设计：独立的状态记录表 `coser_scrape_state`
- **方案**：不直接修改 `cosers` 表结构去追加多列，而是创建关联状态表：
  ```sql
  CREATE TABLE IF NOT EXISTS coser_scrape_state (
      coser_id INTEGER NOT NULL,
      platform TEXT NOT NULL,
      last_scraped_at TEXT,
      PRIMARY KEY (coser_id, platform),
      FOREIGN KEY(coser_id) REFERENCES cosers(id) ON DELETE CASCADE
  );
  ```
- **平台缺失过滤**：针对部分 Coser 缺失微博或 B站 UID 的情况，直接在滑动窗口检索的 SQL 条件中按平台字段进行过滤（例如 B站只检索 `bilibili_uid IS NOT NULL AND bilibili_uid != '' AND bilibili_uid != '-'` 的行）。未绑定对应平台 UID 的 Coser 不会进入该平台的轮转调度中。
- **原因**：这使得核心的 `cosers` 表保持高内聚。如果将来扩展新的社交平台，不需要执行 `ALTER TABLE` 结构迁移，只需在状态表中写入一行新平台的记录即可，扩展性更好。


### 2. 更新时机：单人处理完毕立即提交 (Immediate Commit)
- **方案**：在 scraper 循环中：
  ```python
  for c in batch_cosers:
      try:
          await scrape_platform(c)
      finally:
          DBService.update_scrape_timestamp(c["id"], platform)
  ```
- **原因**：由于抓取总时间长，中途断网、强杀等崩溃极为常见。即时提交能够确保“前 10 个人爬完了，第 11 个人被强杀时，前 10 个人的进度在数据库中已经是更新完的状态”，下次运行时能精准接续，彻底避免重复拉取。

### 3. 写冲突预防：默认开启 SQLite WAL 模式
- **方案**：在 `get_db_connection()` 开启连接后立即执行：
  ```python
  conn.execute("PRAGMA journal_mode=WAL;")
  ```
- **原因**：即时提交会引入频繁的极短写事务。在 SQLite 默认的 DELETE 模式下，写事务会加排他锁，阻断其他读取或并发写入。开启 WAL（Write-Ahead Logging）后，读写操作可以完全并发进行，极大提高了小事务提交的效率，并有效避免了多线程/并发进程中的 `database is locked` 错误。

### 4. 异常防御：不论抓取成败皆更新时间戳
- **方案**：无论当前的 `fetch_weibo_posts` 或 `fetch_bilibili_posts` 执行是成功返回数据，还是抛出网络超时等异常，均要在 `finally` 分支中将该 Coser 的 `last_scraped_at` 更新为当前时间。
- **原因**：防止死号、异常账号（例如用户注销、改名导致 UID 失效）在失败时不更新时间戳，导致它们在下一次调度时依然霸占队列头部，造成队列死锁。

## Risks / Trade-offs

- **[Risk] 抓取失败被旋转到队尾导致漏抓**  
  *Mitigation*: 如果一个账号因为临时网络抖动抓取失败，时间戳被更新后会流转到最末端，确实会等到下一轮循环才会重试。考虑到定时任务的高频运行（例如每小时一轮，每轮30人，每天能跑数轮），单次抖动的滞后在业务上是可以接受的，这换取了队列不被“死号”永久堵死的鲁棒性。
