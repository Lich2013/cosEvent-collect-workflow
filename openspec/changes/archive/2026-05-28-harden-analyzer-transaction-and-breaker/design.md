## Context

当前系统的增量博文分析提炼模块使用单事务控制，其原子性边界过于宽泛，导致“活动提取约束校验失败”和“数据库唯一性冲突”等**结构性永久硬异常**在引发数据库 `ROLLBACK` 的同时，也将 `raw_posts.is_analyzed = 1` 的状态更新一同回滚为 `0`。这就导致此类存在格式缺陷的博文一直在增量队列中，在每次分析流程调度时重复请求 LLM 接口，造成严重的大模型 API 资费浪费。

此外，事务内部的读写隔离不合理，行程比对的 `SELECT` 位于 `BEGIN IMMEDIATE` 锁表隔离区外部，这在并发环境下极易带来脏读和并发锁超时，进而加剧这一循环回滚黑洞。

## Goals / Non-Goals

**Goals:**
- **三态增量去重**：支持 `is_analyzed` 三态逻辑（`0`: 未分析, `1`: 分析成功, `2`: 熔断挂起），捞取增量只匹配 `is_analyzed = 0`。
- **物理数据安全隔离**：在校验或数据库硬约束报错时，确保已处理的数据完全 `ROLLBACK`（零污染），同时熔断更新必须在物理上与大写锁事务完全隔离，杜绝 SQLite 排他锁死。
- **并发锁区重构**：将行程查询和比对动作完全包裹在 `BEGIN IMMEDIATE;` 锁表隔离区内部，消除并发时序真空。
- **爬虫编辑联动**：确保爬虫更新博文（`edit_count` 递增）时，同步重置 `is_analyzed` 状态为 `0`（包含原先为 `2` 的熔断状态，因为编辑后格式可能已修复）。

**Non-Goals:**
- 不重构微博与B站的爬虫核心解析引擎。
- 不更改 `cosplay_events` 等其他表的基本结构和归一化匹配算法。

## Decisions

### 决策 1：`is_analyzed` 采用三态状态机
- **选项 A**：引入独立的错误解析记录表，与 `raw_posts` 进行 LEFT JOIN 过滤已失败的 ID。
- **选项 B (采纳)**：直接将 `raw_posts.is_analyzed` 的状态升级为 `0`（未分析）、`1`（已分析并入库）、`2`（分析熔断豁免）。
- **理由**：选项 B 完全向下兼容现有的 `WHERE is_analyzed = 0` 增量捞取逻辑，不会带来任何多表联合查询的数据库查询开销，改动极其轻量、优雅且直观。

### 决策 2：熔断状态的跨模块双轨物理更新（安全避坑 SQLite 写锁死）
- **问题**：在 `save_extracted_events_transactional` 内部被 `with conn` 事务包裹，如果发生异常执行 `ROLLBACK` 时，在同一个 Exception 捕获器内部如果直接开启新连接去写 `is_analyzed = 2`，在 SQLite 锁未彻底释放完毕前极易发生物理死锁。
- **解决设计 (采纳)**：
  - `EventRepository.save_extracted_events_transactional` 内部仅负责原子行程入库。如果发生 `AssertionError`、`ValidationError` 或 `IntegrityError`，它执行事务 `ROLLBACK` 并**向上抛出特定的结构性异常**或通过返回值让外层知晓。
  - 外层控制器 `WorkflowOrchestrator.run_analyze` 在 `try-except` 中进行**精细化异常分流**：
    - 若捕获到 `AssertionError`、`ValidationError` 或 `IntegrityError`，判断为**结构性/永久性硬错误**。此时主事务已安全回滚，编排器独立调用 `DBService.mark_post_as_failed(raw_post_id)`，物理上隔离数据库连接上下文，以独立的短事务将状态置为 `2` 并持久化。
    - 若捕获到其他诸如大模型网络超时、连接报错等**暂时性异常**，则仅记录 WARNING 日志并跳过，保持状态为 `0`。

### 决策 3：行程比对与 `BEGIN IMMEDIATE;` 锁表动作的读写闭环封装
- **设计**：重构 `save_extracted_events_transactional` 方法：
  ```python
  with conn:
      cursor.execute("BEGIN IMMEDIATE;")  # ◄── 第一行强行升级写锁
      
      # 锁内执行 SELECT
      # 1. 查找 coser 及博文关联数据
      # 2. 查出当前已有活动列表
      
      # 锁内进行 Upsert 比对和写入 ...
      # 6. UPDATE raw_posts SET is_analyzed = 1 ...
  ```
- **理由**：使“查询旧活动行程 -> 比对合并 -> 物理修改”全生命周期在 SQLite 的排他写锁（Immediate Lock）保护中闭环，彻底切断并发下的时空真空，确保读写数据绝对一致。

## Risks / Trade-offs

- **[Risk]**：熔断标记为 `2` 的博文是否可能会被永久遗漏？
  - **[Mitigation]**：这属于不合规的数据。在 CLI 报表输出时，会在 Summary 中清晰呈现本轮新增的失败挂起（熔断）博文数。同时，如果在后续的抓取中该博文被 Coser **编辑更新**（例如 `edit_count` 增加），爬虫在做 Upsert 时不仅要把 `1` 置为 `0`，也**必须将 `is_analyzed = 2` 的博文状态重置为 `0`** 以重启大模型增量分析，从而允许格式修正后的重新提取。
