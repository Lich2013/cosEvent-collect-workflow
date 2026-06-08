## 1. 数据库热迁移与配置升级

- [x] 1.1 在 `config/settings.yaml` 中配置强词和弱词，将 `coser_keywords` 段落重构为分级关键词，并使名字包含 `cos` 仅作为弱特征。
- [x] 1.2 在 `src/models/db_models.py` 中，使用 SQLite 影子表迁移技术重写 `coser_candidates` 表，使 CHECK 约束支持 `'undetermined'` 状态。


- [x] 1.3 在 `src/services/db/candidate_repository.py` 中，适配 `'undetermined'` 状态，实现待定状态的处理逻辑及在拒绝、硬忽略和批准时的临时博文数据物理清理。


## 2. 强弱特征过滤与自适应深度抓取

- [x] 2.1 修改 `src/services/discovery_service.py` 导入分级关键词配置，并在验证流程中区分强词和弱词。
- [x] 2.2 实现强词直接确权判定，绕过博文爬取与 LLM 分析；实现弱特征与无特征的分类判定逻辑。
- [x] 2.3 在 `verify_pending_candidates` 中实现自适应深度抓取：若命中弱特征，博文抓取 limit 参数设为 10；普通候选人设为 3，且抓取过程在内存中完成结果切片。

## 3. LLM 软状态冷却与优先级调度

- [x] 3.1 在候选人核验判定中，若 LLM 判定为 False 且置信度 `confidence < 0.8`，将状态设置为 `'undetermined'` 并记录冷却开始时间；若置信度 `confidence >= 0.8`，设置为 `'ignored'`。
- [x] 3.2 优化待核验候选人捞取 SQL 语句，查询条件支持 `pending` 和已过期的 `undetermined`（当前时间已超过 7 天冷却期）。
- [x] 3.3 实现排序防饥饿逻辑：在 SQL 中增加 `ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, created_at DESC;` 以优先核验新录入的 pending 候选人。

## 4. 测试与验证

- [x] 4.1 编写并运行影子表结构热迁移测试，核验 `coser_candidates` 的 CHECK 约束是否包含 `'undetermined'` 并且历史数据无损。
- [x] 4.2 编写候选人强匹配测试，验证命中强词的候选人直接验证通过且不发起博文爬取。
- [x] 4.3 编写自适应抓取深度与软状态机测试，验证命中弱词时的 10 条抓取限制与普通博主的 3 条抓取限制，以及低置信度下的 `'undetermined'` 状态记录和 7 天冷却过滤。
- [x] 4.4 编写优先级防饥饿测试，验证捞取待核验候选人时的排序和冷却截止期的正确判定。
