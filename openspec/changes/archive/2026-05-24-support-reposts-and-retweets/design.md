## Context

目前爬虫在抓取微博和 B 站数据时只抓取了博主本人的博文正文，而忽略了转发链条中的原博文/原动态。本方案设计在 `WeiboScraper` 和 `BilibiliScraper` 网络拦截 JSON 的源头，识别转发的标记字段，并使用优雅、易于 LLM 理解的对话格式合并，最终存入 `raw_posts.content` 字段中。

## Goals / Non-Goals

**Goals:**
- 支持微博 `retweeted_status` 字段的拦截解析，支持提取原博作者昵称及原博文本。
- 支持B站动态 `orig` 结构的拦截解析，支持提取原作者昵称及原动态文本。
- 将转发文本与 Coser 附言合并为约定的对话格式。
- 对字段缺失、空值及异常结构提供健壮的防御回退机制，确保爬虫不会因结构异常而崩溃。
- 新增单元测试 Mock 验证解析合并逻辑。

**Non-Goals:**
- 不修改 SQLite 数据库 schema，合并字符串直接写入 `content`。
- 不修改 LLM Agent 的 Prompt 模板，由 LLM 天然的语义理解能力消化拼接后的对话文本。
- 不处理小红书的转发逻辑（小红书目前不支持该形式的转发博文）。

## Decisions

### 决策 1：在爬虫解析阶段直接进行文本合并拼接
- **方案选择**：在 `WeiboScraper` 和 `BilibiliScraper` 拦截响应数据并拼装 `posts` 字典列表时，就将原博正文与附言合并。
- **对比替代方案**：在数据库新增 `is_repost`、`original_content` 等物理列。
- **理由**：若修改数据库结构，将引发迁移成本，并导致后续数据导出、LLM 分析接口等多处代码发生物理重构。而 LLM 具有高超的语境理解力，直接拼接为对话式文本不仅开发成本极低、完全向下兼容，且极其易于 LLM 解析出完整、正确的漫展出行计划，是最高效优雅的选择。

### 决策 2：数据字段提取规则与回退策略
- **微博提取键**：
  - 原作者：`item.get("retweeted_status", {}).get("user", {}).get("screen_name", "原作者")`（对 `user` 为 `None` 的情况做安全防护）
  - 原正文：`item.get("retweeted_status", {}).get("text_raw", "")`
- **B站提取键**：
  - 原作者：`orig.get("modules", {}).get("module_author", {}).get("name", "原作者")`
  - 原动态：`orig.get("modules", {}).get("module_dynamic", {}).get("desc", {}).get("text", "")`
- **理由**：以上是两平台最核心、无污染的原生正文数据字段。对于缺失的用户名默认为 `"原作者"`，缺失的正文默认为 `""`，最大化防崩溃。

## Risks / Trade-offs

- **[Risk] 平台接口变动导致键名变化**
  - **Mitigation**：在解析时全部采用带 try-except 的防御式字典取值，如果解析报错则自动跳过转发拼接，仅保留博主附言或安全回退，绝不导致 Scraper 抛出未捕获异常而崩溃。同时在 CI 中集成转发 Mock 单元测试。
