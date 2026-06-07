## Why

当前 B 站来源的 Coser 候选人验证流程依赖于模糊的昵称搜索和可能被截断的搜索卡片简介，容易引入噪声，且无法对原博文中已结构化提及的用户进行直接 UID 解析与深度主页分析。通过从原始博文中提取用户并进行主页分析，可以极大提升 B 站候选人对齐的准确率与验证置信度。

## What Changes

- **B站博文提及直接解析**：从 B 站 gRPC 动态抓取的富文本节点（`TextNode.link`）中，直接提取提及用户的 UID 与昵称，无损创建带有 pre-bound `matched_bili_uid` 的候选人记录。
- **数据库 Schema 迁移**：在 `coser_candidates` 表中自动追加 `is_verified` 字段，以支持 pre-bound 候选人的延迟主页验证机制。
- **B站主页深度分析（Space Analysis）**：在验证阶段，针对有 B站 UID 的候选人，通过 Playwright 访问其个人空间 `space.bilibili.com/{uid}` 并拦截 `wbi/acc/info` 接口，提取完整、未截断的个人签名（bio）及官方认证信息进行二次元/Coser 关键词校验。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `coser-candidates`: 增强 B 站候选人的发现与提取机制，引入直接 UID 绑定、`is_verified` 验证状态以及主页深度分析校验。

## Impact

- 影响模块：`src/tools/bilibili_scraper.py`（新增 mention 节点解析）、`src/services/discovery_service.py`（优化验证流程、支持 pre-bound UID、接入 Space 解析验证）、`src/models/db_models.py`（数据库迁移升级）、`src/services/db/candidate_repository.py`（适配 `is_verified` 属性读写）。
