## MODIFIED Requirements

### Requirement: 候选人博文抓取与物理隔离存储
对于已获取平台 UID 且未完成核验的候选人（包含 `status = 'pending'` 与过期冷却状态为 `'undetermined'` 且 `is_verified = 0`），系统在执行验证任务时，必须且 SHALL 并发增量抓取其对应平台的博文文本，并将数据存储在隔离的原始博文表 `candidate_raw_posts` 中。
系统必须且 SHALL 执行**自适应抓取深度**：
1. 若候选人的 Bio（微博简介、认证或B站简介、认证）中命中了**二次元弱特征词**，则自适应抓取上限提升至 **10 条**（内存中切片过滤，防止日常信息挤占窗口）；
2. 其余无明显特征的普通候选人，抓取上限保持为 **3 条**。

#### Scenario: 成功爬取弱特征候选人博文且执行深抓取 10 条
- **WHEN** 执行候选人核验任务，候选人 `"小沂Alter"` 微博简介含有弱二次元词 "写真"，拥有微博 UID且尚未核验时
- **THEN** 系统发起抓取并将切片限制设定为 10 条，将抓取结果写入 `candidate_raw_posts`

#### Scenario: 普通候选人执行浅抓取 3 条
- **WHEN** 执行候选人核验任务，候选人 `"路人甲"` 无任何二次元特征，尚未核验时
- **THEN** 系统发起抓取并将限制设定为 3 条，写入 `candidate_raw_posts`

---

### Requirement: 博文纯文本 LLM 智能体分类核验
系统在抓取候选人近期博文文本后，必须且 SHALL 通过强弱关键词和 LLM 智能体完成分类评估。
系统必须且 SHALL 遵循以下判定及流转机制：
1. **强词优先匹配 (Strong Bio Match)**：若名字/简介命中了**二次元强特征词**（如 `cos`, `cosplay` 等），直接验证通过并将 `is_verified` 置为 `1`，无需执行博文爬取与 LLM 分析。
2. **弱词/无词 LLM 判定**：未命中强词（包括仅命中弱词或名字包含 cos 但 Bio 无强词）的候选人强制走 LLM 判定。
3. **软状态机过滤 (Undetermined)**：若 LLM 判定 `is_active_coser` 为 `False`：
   - 如果置信度评分 `confidence >= 0.8`，则直接判定不通过，将 `status` 标记为 `'ignored'`；
   - 如果置信度评分 `confidence < 0.8`（判定模糊/博文无证据），则判定为待定状态，将 `status` 标记为 `'undetermined'`，保留冷却，冷却期为 7 天。

#### Scenario: 强关键词命中直接验证通过并绕过 LLM
- **WHEN** 候选人 `"池咲misa"` 的 B站官方认证为 "知名Coser"（强词）时
- **THEN** 系统直接将 `is_verified` 设为 `1`，`verify_reason` 记为 "Bio 关键词匹配成功"，且不调用 LLM 及博文抓取

#### Scenario: LLM 核验失败且高置信度时标记为硬忽略
- **WHEN** 智能体判定候选人 `"用户123"` `is_active_coser` 为 `False` 且置信度为 `0.95` 时
- **THEN** 系统将该候选人 `status` 更新为 `'ignored'`，并物理清除其在 `candidate_raw_posts` 表中的所有临时博文

#### Scenario: LLM 判定模糊且低置信度时标记为待定软状态
- **WHEN** 智能体判定候选人 `"普通测试用户"` `is_active_coser` 为 `False` 且置信度仅为 `0.65` 时
- **THEN** 系统将该候选人 `status` 更新为 `'undetermined'`，物理清除其临时博文，开启 7 天冷却计数

---

### Requirement: 候选人数据库 is_verified 验证状态与热迁移
系统必须且 SHALL 在候选人表 `coser_candidates` 中完整支持 `is_verified` 验证字段与 `'undetermined'` 软状态（通过 CHECK 约束硬锁死在 `('pending', 'approved', 'ignored', 'undetermined')` 范围内）。在 CLI 启动时，系统必须且 SHALL 能够安全自动地对已存在的老版数据库进行影子表重构（DDL）热迁移，无损还原历史数据及字段。

#### Scenario: CLI 启动自动执行包含新状态约束的影子表热迁移升级
- **WHEN** 启动 CLI 命令行且检测到老数据库的 CHECK 约束不支持 `'undetermined'` 时
- **THEN** 系统通过自动执行影子表（Shadow Table）热重建事务，完成 `coser_candidates` 重建并迁移全量历史数据
