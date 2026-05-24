## Context

本设计方案旨在处理微博博文发生二次编辑修改时的日程更新与数据固化。需要通过数据库无缝热升级、微博爬虫编辑版本提取、以及基于系统当前时间的“历史冷冻 + 未来增量合并对齐”数据库事务，实现对 Cosplay 活动日程的高鲁棒性追踪。

## Goals / Non-Goals

**Goals:**
- 对本地 SQLite 进行热升级，为 `raw_posts` 动态追加 `edit_count` 和 `published_at` 列。
- `WeiboScraper` 提取 mymblog 拦截中的微博 `edit_count` 和原始发表时间 `created_at` (转化为 `published_at`)。
- 当 `edit_count` 递增时，重置原始博文状态 `is_analyzed = 0` 以激活下游大模型重跑。
- 引入**“历史冷冻固化 + 未来增量对齐”**的活动日程物理合并事务，杜绝历史行程数据丢失，并精准同步未来改期与取消。

**Non-Goals:**
- 本次暂不动态发起 `editHistory` 接口的 HTTP 请求，日常运行完全通过 mymblog 监听 `edit_count` 的最新快照即可满足增量合并。
- 暂不处理 B 站或小红书的编辑版本控制（这些平台缺乏统一的原生编辑次数支持）。

## Decisions

### 决策 1：平滑数据库自动热升级 (Auto-Migration)
- **设计**：在 `db_models.py` 的 `init_db` 方法中，在建表逻辑之后执行防御性列检测。若发现 `raw_posts` 中不存在 `edit_count` 或 `published_at` 列，则在底层连接内自动执行 `ALTER TABLE raw_posts ADD COLUMN ...`。
- **理由**：这规避了需要用户手动输入数据库修改指令的复杂性和潜在的误操作，保障系统的开箱即用与完美的向下兼容性。

### 决策 2：系统时间为轴的数据增量对齐算法
在 `DBService.save_extracted_events_transactional` 中，增量合并采用以下时序对齐步骤：

1. **时间截断**：获取系统当前执行时间 `current_date` (格式 YYYY-MM-DD)。
2. **提取历史与未来**：
   - 找出数据库中原本关联此 `raw_post_id` 且 `event_date < current_date` 的所有**历史活动日程**（绝对保留）。
   - 找出数据库中关联此 `raw_post_id` 且 `event_date >= current_date` 的所有**未来活动日程**（作为增量合并目标）。
3. **分流新提取活动**：
   - 凡是新提取出且日期早于今天的活动：直接进行增量 `INSERT`（应对冷启动或漏抓的追溯情况）。
   - 凡是新提取出且日期大于等于今天的未来活动：
     - **更新 (Update)**：若其名称、日期和地点均在已存未来日程中存在，则 `UPDATE` 更新其描述、置信度和来源 URL。
     - **插入 (Insert)**：若为全新日程，则执行 `INSERT`。
4. **清理取消日程 (Outdated Delete)**：对于所有数据库中原本存在、但未在最新提炼未来列表中的日程（说明 Coser 已在微博中将其删改或取消），执行 `DELETE` 物理清理，达成与新博文的完美状态对齐。

```
                              [ 获取当前 YYYY-MM-DD ]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
         [ 历史日程 (旧日期) ]                            [ 未来日程 (新/今日期) ]
                 │                                               │
                 ▼                                               ▼
        【绝对冻结，只加不减】                            【与最新提取列表比对】
                 │                                               │
                 │                               ┌───────────────┴───────────────┐
                 │                               ▼                               ▼
                 │                          [ 存在对齐项 ]                 [ 消失在最新列表 ]
                 │                               │                               │
                 ▼                               ▼                               ▼
            [ INSERT ]                      [ UPDATE ]                       [ DELETE ]
```

## Risks / Trade-offs

- **[Risk] 服务器本地系统时间错误导致分流失效**
  - **Mitigation**：在 `event_agent.py` 运行时注入的系统时间是整个消解链的唯一源头。在 spec 中显式约定以运行环境的 `YYYY-MM-DD` 为绝对分流水准，并在单元测试中 Mock 该系统时间以验证分流界限的 100% 正确性。
