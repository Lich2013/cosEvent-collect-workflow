## ADDED Requirements

### Requirement: B 站博文提及直连 UID 提取
系统在通过 B 站 gRPC 或 API 抓取原始动态时，必须且 SHALL 从动态的富文本节点（如 TextNode 的 LinkNode 链接控制信息）中，直接提取提及用户的 UID 与名称，避免仅依赖文本正则匹配，并无损地将此对齐信息随同候选人记录一起持久化保存。

#### Scenario: B 站动态直接提取提及并包含 pre-bound UID
- **WHEN** 抓取一条包含 `@艾西Aiwest` 动态提及的 B 站博文时
- **THEN** 系统直接解析出其对应的 B 站 UID `"5687638611"`，并将该 UID 作为 `matched_bili_uid` 预存写入 `coser_candidates`，且其状态为未验证（`is_verified = 0`）

### Requirement: B 站空间主页拦截核验机制
系统必须且 SHALL 对所有具有 `matched_bili_uid` 且未通过核验（`is_verified = 0`）的 pending 状态候选人，在验证阶段通过 Playwright 访问其空间主页 `space.bilibili.com/{uid}` 并拦截 `wbi/acc/info` 响应，获取其完整且未截断的个人签名与官方认证，执行 ACG 关键词校验。

#### Scenario: 拦截空间主页接口获取签名并通过 Coser 核验
- **WHEN** 对 pre-bound UID 为 `"5687638611"` 的候选人执行验证时
- **THEN** 系统使用 Playwright 加载其主页并截获接口，提取出其完整的个人简介，若简介包含二次元关键词，则将其验证状态标记为已核验（`is_verified = 1`）

### Requirement: 候选人数据库 is_verified 验证状态与热迁移
系统必须在候选人表中支持 `is_verified` 字段，以支持 pre-bound 候选人的两阶段发现与核验。在 CLI 启动时，系统必须且 SHALL 能够安全自动地为已有数据库追加此字段，并不影响历史数据状态。

#### Scenario: CLI 启动自动执行 schema 迁移升级
- **WHEN** 初始化或启动 CLI 命令行工具时
- **THEN** 系统通过 schema 迁移，自动在 `coser_candidates` 表中追加 `is_verified` 列并默认置为 `0`，且无需人工干预
