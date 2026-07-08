## ADDED Requirements

### Requirement: 候选人抓取不可确认时不得硬忽略
系统在候选人核验阶段必须且 SHALL 区分“确认无博文证据”和“抓取不可确认”。当平台抓取发生异常、返回结果无法判断是否为真实空列表、或上游 scraper 以空数组表达超时/风控降级时，系统不得将候选人直接标记为 `ignored`。此类候选人必须保留 `pending` 以便下轮重试，或在可证明信息不足但非高置信非 Coser 时转入 `undetermined` 冷却状态。

#### Scenario: 候选人博文抓取超时后保留 pending
- **WHEN** 候选人未命中强特征词，系统抓取其近期博文时遇到超时或风控导致结果不可确认
- **THEN** 系统记录 warning，并保持候选人 `status = 'pending'` 且 `is_verified = 0`

#### Scenario: LLM 低置信否定后进入 undetermined
- **WHEN** 候选人博文成功抓取并传入核验 Agent，Agent 返回 `is_active_coser = false` 且 `confidence < 0.8`
- **THEN** 系统将候选人标记为 `undetermined`，清理临时博文并启动 7 天冷却

### Requirement: 重新发现候选人不得覆盖已核验结果
系统在重复发现同名候选人并合并候选记录时，必须且 SHALL 保留已有的高价值核验状态。若既存候选人为 `pending` 或 `undetermined` 且 `is_verified = 1`，后续无核验结果的普通提及扫描不得将 `is_verified` 覆盖为 `0`，也不得清空已有 `verify_reason`。只有新的核验流程明确产出更完整的 UID、分数或理由时，才允许进行非破坏性合并更新。

#### Scenario: 已核验候选人被再次提及时保留核验状态
- **WHEN** 候选人 `A` 已经 `is_verified = 1` 且记录了 `verify_reason`，后续博文再次 @ 提及该名称但未提供新的核验证据
- **THEN** 系统更新来源引用或 UID 时保留 `is_verified = 1` 和原有 `verify_reason`

#### Scenario: 新 UID 信息合并时不破坏核验结果
- **WHEN** 已核验候选人后续被发现携带新的 `matched_bili_uid`
- **THEN** 系统合并新的 UID 字段，同时保留既有核验状态和理由

### Requirement: 候选人核验 Prompt 必须作为 System Instructions 执行
候选人 LLM 核验必须且 SHALL 使用模板化 System Instructions 承载判定规则、排除规则、输出契约和当前日期。候选人姓名与近期博文可以作为用户输入传递，但不得把主要核验规则仅放在用户输入中，以免规则优先级低于系统指令。

#### Scenario: 候选人核验规则进入 system prompt
- **WHEN** 系统调用候选人核验 Agent
- **THEN** 活跃 Coser 行为模式、排除规则、输出契约和 `current_date` 均位于渲染后的 Agent `instructions` 中
