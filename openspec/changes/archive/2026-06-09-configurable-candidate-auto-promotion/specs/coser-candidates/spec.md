## MODIFIED Requirements

### Requirement: 博文纯文本 LLM 智能体分类核验
系统在抓取候选人近期博文文本后，必须且 SHALL 通过强弱关键词和 LLM 智能体完成分类评估。
系统必须且 SHALL 遵循以下判定及流转机制：
1. **强词优先匹配 (Strong Bio Match)**：若名字/简介命中了**二次元强特征词**（如 `cos`, `cosplay` 等），直接验证通过并将 `is_verified` 置为 `1`，无需执行博文爬取与 LLM 分析。
2. **弱词/无词 LLM 判定**：未命中强词（包括仅命中弱词或名字包含 cos 但 Bio 无强词）的候选人强制走 LLM 判定。
3. **软状态机过滤 (Undetermined)**：若 LLM 判定 `is_active_coser` 为 `False`：
   - 如果置信度评分 `confidence >= 0.8`，则直接判定不通过，将 `status` 标记为 `'ignored'`；
   - 如果置信度评分 `confidence < 0.8`（判定模糊/博文无证据），则判定为待定状态，将 `status` 标记为 `'undetermined'`，保留冷却，冷却期为 7 天。
4. **验证通过自动审批与流转控制**：当候选人验证通过（强词匹配通过或 LLM 判定为 Coser）时：
   - 若配置项 `auto_approve_candidates` 为 `true`，系统必须且 SHALL 自动调用审批逻辑，将候选人状态设为 `'approved'`，导入到 `cosers` 正式追踪表中，并物理清理隔离博文。
   - 若配置项 `auto_approve_candidates` 为 `false`，系统必须且 SHALL 仅将候选人的 `is_verified` 设为 `1` 并记录 `verify_reason`，保留其状态为 `'pending'` 且不导入 `cosers` 正式追踪表，且保留其隔离博文。

#### Scenario: 强关键词命中直接验证通过并绕过 LLM
- **WHEN** 候选人 `"池咲misa"` 的 B站官方认证为 "知名Coser"（强词）时
- **THEN** 系统直接将 `is_verified` 设为 `1`，`verify_reason` 记为 "Bio 关键词匹配成功"，且不调用 LLM 及博文抓取

#### Scenario: LLM 核验失败且高置信度时标记为硬忽略
- **WHEN** 智能体判定候选人 `"用户123"` `is_active_coser` 为 `False` 且置信度为 `0.95` 时
- **THEN** 系统将该候选人 `status` 更新为 `'ignored'`，并物理清除其在 `candidate_raw_posts` 表中的所有临时博文

#### Scenario: LLM 判定模糊且低置信度时标记为待定软状态
- **WHEN** 智能体判定候选人 `"普通测试用户"` `is_active_coser` 为 `False` 且置信度仅为 `0.65` 时
- **THEN** 系统将该候选人 `status` 更新为 `'undetermined'`，物理清除其临时博文，开启 7 天冷却计数

#### Scenario: 开启自动审批时验证通过候选人自动导入正式库
- **WHEN** 配置项 `auto_approve_candidates` 为 `true`，且候选人核验判定为 Coser 通过时
- **THEN** 该候选人 `is_verified` 设为 `1`，`status` 变为 `'approved'`，并成功导入正式 `cosers` 追踪表，其临时博文被物理清理

#### Scenario: 关闭自动审批时验证通过候选人保持 pending 状态
- **WHEN** 配置项 `auto_approve_candidates` 为 `false`，且候选人核验判定为 Coser 通过时
- **THEN** 该候选人 `is_verified` 设为 `1`，`status` 保持为 `'pending'`，且未被导入 `cosers` 表，且其临时博文未被清理
