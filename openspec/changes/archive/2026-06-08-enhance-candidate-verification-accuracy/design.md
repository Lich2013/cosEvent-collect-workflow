## Context

目前 Coser 自动发现系统的验证阶段主要采用 `Bio-First + 3条博文 LLM 过滤` 的逻辑。但是在生产环境中暴露了以下设计局限：
1. **关键词权值模糊**：Bio 匹配将强词与弱词混为一谈，导致普通博主因简介含有“工作/合作”被误判通过。
2. **抓取深度不足**：对高频微博的 Coser 只抓取 3 条博文，导致核验博文被日常琐事淹没而产生假阴性。
3. **软状态缺失**：核验判定失败便直接物理标记为 `'ignored'`，使得临时 API 抖动或内容缺失的候选人永久失去重试机会。

## Goals / Non-Goals

**Goals:**
- 将 `COSER_KEYWORDS` 重构为分级关键词（Strong / Weak），只有强词匹配直接验证通过，弱词仅作疑似标记并强制进入 LLM 核验。
- 支持自适应深度抓取：若命中弱词，抓取条数提升至 10 条（在内存中对单次 API/gRPC 响应进行 Slice，不增加额外网络开销）。
- 引入 `'undetermined'`（待定）状态及 7 天冷却过滤算法，实现容错重试。
- 实现 SQLite `coser_candidates` 的影子表迁移升级，确保 CHECK 约束支持 `'undetermined'` 状态。
- 采用优先级队列 SQL 排序，优先验证新录入的 `pending` 候选人，防止队列饥饿。

**Non-Goals:**
- 不涉及多模态（图片 CNN/VLM 目标检测）核验。
- 不修改微博/B站 Scraper 抓取引擎的底层通信和授权逻辑。

## Decisions

### 1. 关键词分级策略与配置化
在 `config/settings.yaml` 中新增 `coser_keywords` 段落，分为 `strong`（直接确权）和 `weak`（疑似，必须LLM核验）。名字中包含 `cos` 仅作为弱特征，不能直接确权。

### 2. 自适应抓取条数
通过对 [weibo_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/weibo_scraper.py) 和 [bilibili_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/bilibili_scraper.py) 的逻辑分析，两者的单次响应均返回 10-20 条动态。因此，将 limit 参数自适应提升至 10，只需要在 Python 内存中对结果集进行 `[:limit]` 切片，**完全不会增加额外的 HTTP 请求数和被反爬封锁的风险**。

### 3. SQLite 表 CHECK 约束影子表升级
由于 SQLite 不支持 `ALTER TABLE MODIFY CHECK`，在系统启动 `init_db()` 时，我们必须以“重命名旧表 -> 创建新约束表 -> 复制数据 -> 删除旧表”的影子表模式热升级。
```sql
ALTER TABLE coser_candidates RENAME TO coser_candidates_old;
CREATE TABLE coser_candidates (
    ...
    status TEXT DEFAULT 'pending',
    CHECK (status IN ('pending', 'approved', 'ignored', 'undetermined'))
);
INSERT INTO coser_candidates SELECT * FROM coser_candidates_old;
DROP TABLE coser_candidates_old;
```

### 4. 优先级调度 SQL 与冷却计算
- **查询过滤**：待核验候选人获取语句变更为：
  `WHERE (status = 'pending' AND is_verified = 0) OR (status = 'undetermined' AND is_verified = 0)`
- **冷却过滤**：若为 `undetermined` 状态，在 Python 内存中检查 `created_at` 距当前时间是否超过 7 天，未超过则跳过本轮核验。
- **排序防饥饿**：
  `ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, created_at DESC;`
  确保全新注册的 pending 候选人享有最高优先级。

## Risks / Trade-offs

- **[Risk] SQLite 表重建时发生死锁或崩溃**
  - **Mitigation**: 迁移步骤包在同一个数据库 SQL 事务中执行，若出错则 `ROLLBACK` 还原。同时，如果 `coser_candidates_old` 不存在则不进行重建，保证幂等性。
- **[Risk] 自适应抓取 10 条导致 LLM 输入 Context Token 增加，提高成本**
  - **Mitigation**: 10 条纯文本博文依然很短（通常小于 1000 Tokens，相当于 $0.0015），且仅对命中了弱特征词的疑似用户开启，整体成本非常低。
