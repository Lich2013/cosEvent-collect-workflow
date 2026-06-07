## Context

当前系统从微博博文内容中利用正则表达式提取提及（`@用户名`）来发现候选人。然而，提取出的用户名仅是微博昵称，而非微博 UID。在验证阶段（`sync-bili`），系统没有查询微博接口来解析该昵称的 UID，而是直接把带有微博专属后缀（如 `_ShiratoriK`）的原始昵称丢给 B 站进行搜索，造成 B 站检索失败，最终导致大量微博候选人被系统误忽略。

本设计旨在通过利用已登录的微博 Session，直接请求微博 AJAX 接口换取真实的微博 UID 和个人简介，实现双平台的自动对齐。

## Goals / Non-Goals

**Goals:**
- 提供将微博昵称解析为微博 UID 及个人简介（Bio）的能力。
- 在对齐验证（`verify_pending_candidates`）中，对微博来源的候选人，首先利用微博 API 解析其 UID 与简介。
- 在对齐验证中，对微博来源候选人的名字进行常见后缀清洗（如 `_ShiratoriK`, `_cos`, `_Coser` 等），再带入 B 站进行搜索匹配。
- 验证通过并被批准（Approve）入库时，自动向正式的 `cosers` 表中同时写入对齐后的 `weibo_uid` 和 `bilibili_uid`。

**Non-Goals:**
- 在没有可用微博 Session（Cookie）时强行要求进行人工滑块验证（此时静默跳过或降级）。
- 实现自动向微博用户发送私信等交互功能。

## Decisions

### 决策 1：在 `WeiboScraper` 中新增 `resolve_screen_name` 接口
- **方案**：在 `WeiboScraper` 中利用 Playwright 的 `scrape_flow_handler` 加载已登录的 `BrowserContext`，在新页面中执行 `fetch` 请求 `https://weibo.com/ajax/profile/info?screen_name={encoded_name}` 接口以获取结构化用户对象（包含 `idstr` 和 `description`）。
- **理由**：虽然可以直接使用 `requests` 库携带本地 Cookie 字符串请求该 AJAX 接口，但微博的 WAF 对 TLS 指纹、HTTP/2 支持、以及 Header 顺序要求非常严格，使用 `requests` 容易被识别并返回 HTTP 403/400。使用 Playwright 现有的无头浏览器请求，重用同个 Session，可完全规避该风控，安全性和稳定性最高。

### 决策 2：更新 `verify_pending_candidates` 中的对齐逻辑
- **方案**：
  1. 遍历待验证的候选人时，若 `platform == 'weibo'`，先调用 `WeiboScraper.resolve_screen_name` 解析其微博 UID 和 Bio。
  2. 若解析成功，将其微博 UID 暂存为待绑定的 `matched_weibo_uid`；同时，对该微博 Bio 进行二次元关键词检查。
  3. 执行 **名字后缀清洗（Suffix Pruning）**：利用正则清洗掉诸如 `_Coser`, `_cos`, `_ShiratoriK` 等带有下划线前缀的常见微博后缀，获取纯净昵称。
  4. 用清洗后的昵称在 B 站搜索 UP 主。若搜索到，通过 `BiliUidMatcher` 匹配出其 B 站 UID。
  5. 判定二次元属性：只要其在 B 站对齐成功，**或者**其微博 Bio 通过了二次元关键词过滤，即视为验证成功，调用 `DBService.add_candidate` 写入对齐的 `matched_bili_uid` 和 `matched_weibo_uid`。
- **理由**：通过先解析微博 UID，我们可以获得其微博 Bio，结合后缀清洗后去 B 站对齐，大幅提高了微博 Coser 的识别匹配率。即使 B 站没有账号，只要其微博 Bio 明确是 Coser，我们也可以正常验证通过，并在后续入库时保存其微博 UID。

### 决策 3：物理入库双向绑定
- **方案**：修改 `CandidateRepository.approve_candidate` 中向 `cosers` 插入/更新记录的逻辑，使其合并并写入来自候选人表中的 `matched_weibo_uid`。
- **理由**：这样能够确保在候选人被 Approve 时，其自动换取的 `weibo_uid` 和 `bilibili_uid` 被一并归档，使数据完整性得到闭环。

## Risks / Trade-offs

- **[Risk] 微博 API 请求频率受限**
  - *Mitigation*: 解析昵称仅在 `verify_pending_candidates` 运行时对 `pending` 状态且 platform 为 `weibo` 的新账号按限制数量（`--limit`）处理，请求间增加微小延迟，且仅当有新候选人时才运行，不会产生大批量高频扫描。
- **[Risk] 后缀清洗过度（如把正常昵称末尾的英文剪掉）**
  - *Mitigation*: 采用针对性的正则表达式，例如只匹配 `_` 开头且后跟 `cos`, `coser`, 或具体已知无效名字后缀（如 `ShiratoriK` 作为特例，或长度较短的下划线后缀如 `_cos` 等）。
