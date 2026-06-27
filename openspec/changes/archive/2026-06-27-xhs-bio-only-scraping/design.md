## Context

小红书（XHS）平台的风控较为严格，且笔记列表的 Ajax 数据结构时常发生变化。
同时，Coser 的近期动态多以个人简介（Bio/签名）作为首要发布渠道。
因此，我们需要将小红书爬行功能从“笔记 + 简介”混合模式变更为“仅抓取个人简介（Bio）”模式。

## Goals / Non-Goals

**Goals:**
- 将 `xhs_scraper.py` 中的 Playwright 拦截点从 `user_posted` 变更为 `user/otherinfo`，实现对简介信息的直接、稳定抓取。
- 移除常规笔记解析逻辑，使小红书爬虫仅提取 Bio 虚拟动态。
- 确保爬虫在提取到非空简介时能够成功组装 `bio_{uid}` 虚拟动态返回，并在简介为空时安全返回空列表。
- 保持与现有 `WorkflowOrchestrator` 以及数据库版本比对去重（`save_raw_posts`）的向下兼容性。

**Non-Goals:**
- 不对微博（Weibo）和 B站（Bilibili）的爬行策略做任何改动（它们仍需保留常规笔记与简介的同时抓取）。
- 不涉及数据库表结构的变更。

## Decisions

### 决策一：采用 `expect_response` 拦截 `api/sns/web/v1/user/otherinfo` 作为首要抓取通路
- **理由**：当 Playwright 浏览器访问 `https://www.xiaohongshu.com/user/profile/{uid}` 时，页面必定会加载该接口以渲染个人资料。相比于拦截 `user_posted`，直接等待并解析该接口能更早、更稳定地获取 Bio。
- **备选方案**：直接访问主页并完全依赖 DOM 定位 `.user-desc`（由于前端延迟和反爬虫检测，单纯依赖 DOM 的稳定性较低，且易受 UI 改版影响）。

### 决策二：完全移除笔记（Notes）的处理与提取代码，清空常规动态流
- **理由**：由于本变更的目标是仅抓取 Bio，无需再浪费网络等待时间和内存去处理 `notes` 数组。
- **替代方案**：在代码中保留笔记的拉取但通过配置项将其过滤（这会增加不必要的网络开销和复杂度）。

### 决策三：保留 DOM 选择器 `.user-desc` 作为降级兜底方案
- **理由**：当 Ajax 网络响应由于风控、网络抖动未被成功捕获时，通过 `try-except` 兜底检查渲染完毕的网页 DOM 元素，提取 `.user-desc` 文字，确保爬虫的自愈和高可用性。

## Risks / Trade-offs

- **[Risk] 小红书接口改版导致 `otherinfo` URL 路径变化**
  - *Mitigation*：在拦截匹配逻辑中采用宽松匹配（包含 `api/sns/web/v1/user/otherinfo` 即可），并保留 DOM 降级兜底器 `.user-desc`；一旦发生彻底改版，系统只输出 Warning，不会引发 CLI 进程崩溃中断。
  - 
- **[Risk] 小红书个人简介为空时无推文产生**
  - *Mitigation*：这是符合预期的。对于空 Bio，系统将返回空列表 `[]`，不进行任何数据库插入，但会调用 `DBService.update_scrape_timestamp` 更新最近爬取时间，避免造成调度卡死。
