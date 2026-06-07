## ADDED Requirements

### Requirement: 候选人博文抓取与物理隔离存储
对于已获取平台 UID 且未完成核验的 pending 状态候选人（`status = 'pending' AND is_verified = 0`），系统在执行验证任务时，必须且 SHALL 增量抓取其对应平台的最新 3~5 条博文文本，并将数据安全地存储在独立的候选人物化原始博文表 `candidate_raw_posts` 中，绝不能写入正式追踪的 `raw_posts` 表中。

#### Scenario: 成功爬取候选人微博博文并物理隔离写入 candidate_raw_posts
- **WHEN** 执行候选人核验任务，候选人 `"小沂Alter"` 拥有微博 UID `"7188636063"` 且尚未被核验时
- **THEN** 系统爬取其最新 3 条微博正文，并将其写入 `candidate_raw_posts` 中，正式的 `raw_posts` 表保持无污染

### Requirement: 博文纯文本 LLM 智能体分类核验
系统在抓取候选人近期博文文本后，必须且 SHALL 构造并调用纯文本核验智能体 `CandidateVerifyAgent`。该智能体依据指定的 Pydantic 强契约结构化输出格式评估该博文列表。若判定结果为活跃 Coser，则将该候选人的验证状态更新为 `is_verified = 1`，并在 `verify_reason` 中记录判定的核心理由；若判定不通过，则将候选人的 `status` 直接标记为 `ignored`。

#### Scenario: 智能体通过博文判定候选人为 Coser 并记录原因
- **WHEN** 核验智能体读取到候选人 `"小沂Alter"` 的博文内容包含 "CP30第一天芙宁娜返图..." 时
- **THEN** 智能体判定 `is_active_coser` 为 `True`，将 `coser_candidates` 的 `is_verified` 更新为 `1`，且 `verify_reason` 写入 "最近博文中含有CP30返图"

#### Scenario: 智能体判定候选人为非 Coser 并标记为忽略
- **WHEN** 核验智能体读取到候选人 `"用户123"` 的博文仅包含日常琐事且无任何 Cosplay 活动迹象时
- **THEN** 智能体判定 `is_active_coser` 为 `False`，将 `coser_candidates` 的 `status` 更新为 `'ignored'`

### Requirement: 终端列表直观展示核验依据
系统在终端列出候选人列表时，必须且 SHALL 在渲染表格中完整展现核验判定结果和 LLM 理由字段 `verify_reason`，以供用户在决定是否手动批准晋升时进行高效率的主观参考。

#### Scenario: 终端以表格形式高亮展示通过核验的候选人及理由
- **WHEN** 运行终端命令 `python src/main.py coser list-candidates` 时
- **THEN** 表格中包含核验状态与理由列，高亮呈现已核验（`is_verified = 1`）的候选人记录，并清晰展示其 `verify_reason` 内容
