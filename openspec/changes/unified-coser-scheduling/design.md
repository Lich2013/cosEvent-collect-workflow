## Context

当前系统在进行二次元 Coser 博文抓取调度时，各平台（微博、B站、小红书）通过 `coser_scrape_state` 表相互独立地记录上一次的抓取时间，并各自选出最久未碰过的 Top 30，最后进行交错轮询合并。
这种设计存在一个致命漏洞：当 Coser 在不同平台的时间戳不一致时（例如微博刚抓过，而B站很久没抓），本轮调度选中该 Coser 后只会去抓 B站，微博由于“不够久”而被跳过。抓取完成后她的 B站 时间戳被更新，导致此后很难在同一批次中同时触发这两个平台的抓取，从而漏掉了该 Coser 微博后续更新的品书内容。

## Goals / Non-Goals

**Goals:**
- 实现统一的以 Coser 维度进行滑动窗口排队调度的逻辑（碰了就算）。
- 保证一旦 Coser 被调度选中，其所有已配置的平台（Weibo、Bilibili、Xhs）在同一轮中都会被爬取。
- 简化数据库表结构，在 `cosers` 表上直接记录全局的 `last_scraped_at` 字段，并在数据库初始化时完成热升级与历史时间戳迁移。
- 简化工作流编排器（Orchestrator）中的待爬取候选队列合并算法。

**Non-Goals:**
- 不改变具体平台 Scraper（微博、B站、小红书）底层的网络爬取与解析实现。
- 不影响大模型对已入库博文进行事件提取与分析的后处理（Analyze Phase）阶段。

## Decisions

### 决策 1：弃用 `coser_scrape_state` 表，改为在 `cosers` 表中直接增加 `last_scraped_at` 字段
- **理由**：以前的多平台细粒度时间戳管理带来了复杂性，并导致了漏抓 Bug。改成每人一个全局时间戳最符合“碰了就算”的直觉，也能极大地简化 SQL 查询，避免复杂的 `LEFT JOIN coser_scrape_state s ON c.id = s.coser_id AND s.platform = ?`。
- **代替方案**：保留 `coser_scrape_state` 表，但把 `platform` 设为 `all` 或移除 `platform` 复合主键。
  - *为什么不选替代方案*：这会增加多余的表和级联删除逻辑维护，不如在 `cosers` 表直接增加一个 nullable 字段来的干净。

### 决策 2：废除 `run_scrape` 中复杂的三路指针多轮交错轮询合并算法
- **理由**：在过去的机制下，为了防止各平台累加引起过度抓取，系统使用了一个非常晦涩的 `while len(selected_unique_ids) < batch_limit:` 循环来交错弹出各个平台的最久未爬取队列。重构为“以人取 Top 30”后，只需要一次性获取 Top 30，然后对每个人检测其配置了哪些平台，并将其推入对应的微博/B站/小红书爬取列表中即可。
- **对比**：
  - *重构前*：
    ```python
    weibo_candidates = DBService.list_active_cosers_by_schedule("weibo", batch_limit)
    bili_candidates = DBService.list_active_cosers_by_schedule("bilibili", batch_limit)
    xhs_candidates = DBService.list_active_cosers_by_schedule("xhs", batch_limit)
    # 通过 while 循环和指针做复杂的交错去重合并
    ```
  - *重构后*：
    ```python
    target_cosers = DBService.list_active_cosers_by_schedule(platform, batch_limit)
    for c in target_cosers:
        if c["weibo_uid"]: target_weibo_cosers.append(c)
        if c["bilibili_uid"]: target_bili_cosers.append(c)
        if c["xhs_uid"]: target_xhs_cosers.append(c)
    ```

### 决策 3：在 `init_db()` 中自动检测并追加 `last_scraped_at` 列，并执行历史数据迁移
- **理由**：为防止更新系统后，旧库中的活跃 Coser 全局时间戳全部为 `NULL` 从而引发瞬间爬取风暴，需要在追加 `last_scraped_at` 字段时自动执行一次 SQL 迁移，把 `coser_scrape_state` 里每个 Coser 最晚的那条记录更新过去。

## Risks / Trade-offs

- **[Risk] 爬取中途崩溃导致未处理平台被推迟**
  - *描述*：因为是“碰了就算”，如果跑完微博，进程被操作系统强制终止，此时全局 `last_scraped_at` 已经被微博的 `finally` 块更新了，下一次运行时这批 Coser 会排在后面，这轮他们的 B站 / 小红书是否会漏掉？
  - *缓解*：该风险极低，因为整个 run_scrape 的生命周期一般是完整的短作业。如果确实发生突然断电或被 kill 等物理中断，由于爬虫本身带有断点去重和幂等能力，重新爬取并不会造成数据丢失或错误。同时，通常的爬虫报错（如网络抖动抛错）都会被 catch 住并进入 `finally` 块，从而正常完成后续平台的遍历。
