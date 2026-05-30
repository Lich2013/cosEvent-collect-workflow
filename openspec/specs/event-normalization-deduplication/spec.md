# event-normalization-deduplication Specification

## Purpose
TBD - created by archiving change fix-event-normalization-duplicates. Update Purpose after archive.
## Requirements
### Requirement: 智能城市提取与多级清洗
系统在提取原始漫展的参展地点时，必须且 SHALL 执行多级清洗以规范城市名称：
1. 系统必须剥离地名中任何省份前缀（如“浙江省”、“广东省”）。
2. 系统必须匹配主要展览地级市字典（如“上海”、“杭州”），一旦命中前缀或子串且类型一致，必须立即收拢并返回对应的标准城市名称。
3. 系统必须智能剥离尾部的“市”、“区”、“县”等行政单位后缀。
4. 如果上述提取手段皆未命中，系统必须且 SHALL 强制截取清洗后地点字符串的前两个汉字作为兜底城市（以防止四字伪城市产生）。

#### Scenario: 成功提取带有省份前缀和展馆的城市
- **WHEN** 输入参展地点为“浙江省杭州白马湖微电子博览中心”
- **THEN** 系统提取并清洗后的城市必须且 SHALL 为“杭州”

#### Scenario: 成功降级截取两字兜底城市
- **WHEN** 输入参展地点为“福州海峡国际会展中心”
- **THEN** 系统通过前两字截取逻辑，提取并清洗后的城市必须且 SHALL 为“福州”

### Requirement: 别名极速确权与时空窗口秒配
系统在为原始活动寻找或创建超级归一化节点时，必须且 SHALL 优先使用入口 O(1) 快速查询，并且匹配过程必须结合时间档期防坍塌校验：
1. 快速查询必须包括对标准名主键（`normalized_events.event_fingerprint`）以及别名映射表（`event_aliases`）的直接查询，跳过 SequenceMatcher 和 LLM 裁判。
2. 查询匹配时，必须且 SHALL 校验当前日程日期是否在既存超级节点的活动区间范围内（即：`start_date - 7 days` 至 `end_date + 7 days` 之间，未知日期默认通过），以防同名不同年份的活动发生错误坍塌。

#### Scenario: 别名命中且在时间窗口内成功秒配
- **WHEN** 输入活动为“上海BW”，日期为“2026-07-10”，库中已存在超级节点“Bilibili World 2026”（日期 2026-07-10 至 2026-07-12），且别名表已缓存“上海bw”指向该节点
- **THEN** 系统必须且 SHALL 极速判定通过，直接返回该超级节点 ID

#### Scenario: 别名命中但超出时间窗口拒绝秒配
- **WHEN** 输入活动为“上海BW”，日期为“2027-07-10”，超出库中既存节点的时间段窗口
- **THEN** 系统必须且 SHALL 拒绝本次秒配，并进入新一届活动实体的创建和融合裁判流程

### Requirement: 动态时空纠偏与级联融合处理
当输入的日程具备具体城市名称（非“未知”），且系统发现在“未知”城市下已存在完全同名的超级节点时，系统必须且 SHALL 执行自动时空纠偏：
1. 如果该具体城市下的对应超级节点已存在，系统必须且 SHALL 将当前日程级联关联至该既存的真实城市超级节点。
2. 如果该具体城市下的对应超级节点不存在，系统必须且 SHALL 物理升级该“未知”节点（更新其城市和 `event_fingerprint` 唯一键），使其“转正”成为该城市的正式超级节点。

#### Scenario: 跨未知城市节点纠偏并物理升级
- **WHEN** 系统处理“Bilibili World 2026”，城市为“上海”，发现库中只存在一个 Fingerprint 为“未知_bilibiliworld2026”的“未知”城市节点
- **THEN** 系统必须且 SHALL 动态将该节点城市更新为“上海”，Fingerprint 升级为“上海_bilibiliworld2026”，完成就地融合升级

