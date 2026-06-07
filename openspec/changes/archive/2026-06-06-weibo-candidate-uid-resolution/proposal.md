## Why

当前系统在自动发现候选人后，对微博来源（`platform='weibo'`）的候选人无法自动解析其微博 UID，也无法验证其微博个人简介中的二次元属性。由于微博昵称可能带有平台专属后缀（如 `_ShiratoriK` 等）导致在 B 站检索失败，这些候选人往往会被系统误忽略（`ignored`）。引入微博昵称自动解析与对齐能力可以实现双平台（Weibo & Bilibili）自动绑定和更准确的属性过滤。

## What Changes

- **自动对齐微博 UID**：在候选人验证阶段，针对微博来源（`weibo`）的候选人，系统将直接调用微博 AJAX 用户详情接口（`/ajax/profile/info?screen_name=xxx`），直接换取其真实的数字 `weibo_uid` 并绑定到 `matched_weibo_uid` 字段中。
- **自动对齐 B 站 UID**：在解析出微博 UID 及其个人简介后，系统会进行二次对齐以查找其 B 站账户（使用名字预处理后的干净关键词在 B 站检索并计算置信度匹配）。
- **优化属性过滤校验**：在属性过滤阶段，如果该微博候选人通过微博接口返回的 `description`（个人简介）中包含二次元/Coser关键字，或在 B 站对齐成功并通关，即可通过属性校验，极大降低微博 Coser 的遗漏率。

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `coser-candidates`: 增加对微博来源候选人的微博 UID 自动对齐和二次元属性过滤支持。
- `coser-management`: 增加从批准的候选人中自动导入微博和 B 站双平台 UID 绑定的支持。

## Impact

- 影响模块：`DiscoveryService` (`verify_pending_candidates`), `WeiboScraper` (新增昵称解析方法), `CandidateRepository` (批准入库对齐)。
- 接口与数据流：利用微博 `/ajax/profile/info?screen_name=` 接口进行静默请求（基于已有的微博 Seed Cookie 会话）。
