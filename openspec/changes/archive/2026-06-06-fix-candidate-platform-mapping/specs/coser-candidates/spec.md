## ADDED Requirements

### Requirement: 候选人来源平台与引用记录
系统必须且 SHALL 在自动提取和更新 Coser 候选人（candidates）时，正确识别并记录原始博文的平台（platform，如 weibo, bilibili, xhs）与原始博文的网页 URL 引用（source_ref），避免硬编码或篡改来源信息。

#### Scenario: 微博博文自动提取注册候选人并保留来源平台
- **WHEN** 对一条微博博文内容提取 @ 提及的候选人并保存时
- **THEN** 数据库 `coser_candidates` 表中对应的新增候选人记录其 `platform` 字段为 `'weibo'`，且 `source_ref` 为该微博的 URL
