## Why

目前 Coser 自动提取与验证流程（Coser Candidates Verification）存在两类关键缺陷：首先是“假阳性”高，弱二次元词汇（如“博主、工作、合作、主页”）在 Bio-First 阶段被直接判定为通过核验，导致非 Coser 的普通账户流入正式名单；其次是“假阴性”高，当活跃 Coser 的微博或 B 站近期日常博文（无二次元内容）较多时，关键的 Cosplay 角色或排班博文（例如 2026-06-01 日的博文）易被最新 3 条的抓取限制挤出，导致被 LLM 错误忽略。

为了降低人工二次筛选成本，亟需引入分级关键词、自适应抓取深度与软状态冷却重试机制，大幅提升发现系统的召回率与判定精准度。

## What Changes

- **强弱关键词分级机制 (STRONG/WEAK Keywords)**：将二次元 Bio 词库划分为强词（直接确权，效率高）与弱词（仅作疑似标记，强制爬取博文并送交 LLM）。名字中包含 `cos` 仅作为弱特征处理，不直接确权，杜绝僵尸/营销号绕过核验。
- **自适应深度抓取 (Adaptive Crawl Depth)**：当候选人仅命中弱词特征时，自动将博文抓取条数限制从 3 条升级为 10 条（在内存中进行单次 API 请求结果切片以控制性能），尽可能覆盖历史正片与排班信息；未命中特征的普通账号维持 3 条抓取上限。
- **状态机引入“待定”软状态 (Undetermined Cooldown & Retry)**：在 `coser_candidates.status` 约束中新增 `'undetermined'` 状态。当 LLM 核验判定为 False 但置信度较低（例如 `confidence < 0.8`）时，更新候选人状态为 `'undetermined'` 并开始 7天冷却计数，冷却结束后自动恢复 pending 并重试，而非直接硬忽略。
- **核验优先级队列排序 (Priority Queue)**：优化调度 SQL，优先处理全新、从未核验过的候选人，剩余额度再轮询处理已过期的待定候选人，防止队列饥饿。
- **数据库结构热迁移 (CHECK Constraint Migration)**：在系统启动时，自动重构 `coser_candidates` 表，将 CHECK 约束升级为包含 `'undetermined'`，对历史数据无损。

## Capabilities

### New Capabilities

*(无新增独立功能领域)*

### Modified Capabilities

- `coser-candidates`: 修改候选人两阶段核验的判定规则、数据库表状态值域和自适应调度算法，细化强弱词及冷却重试行为。

## Impact

- 影响主要集中在 `src/models/db_models.py` (数据库表重构与迁移)
- `src/services/db/candidate_repository.py` (新增适配 'undetermined' 状态操作)
- `src/services/discovery_service.py` (核心验证流程流转、关键词分级和自适应抓取深度逻辑)
- `config/settings.yaml` (新增强弱关键词配置)
