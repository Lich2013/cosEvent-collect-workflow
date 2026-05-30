## Context

在 B站 `sync-bili` 的爬虫模块中，遇到反爬或者某些情况下 Ajax 接口（`search/type`）在 2.5s 内未能被拦截时，我们会优雅滑入 Playwright 的 DOM 兜底解析。

由于 B站 最近调整了页面 DOM 元素及其 CSS Class 的组织方式，引入了扁平化的 CSS 样式（去除了原先专用的 `.up-name`, `.fans`, `.desc`），并混合了大量的动态 CSS Module 随机哈希标记。这导致旧的 DOM 解析逻辑失效，无法成功匹配到候选 UP 主元数据。我们需要重新设计高健壮性的自适应解析器。

## Goals / Non-Goals

**Goals:**
- **自适应多层 Fallback 选择器**：同时支持老版 B站 DOM 结构（兼容现有测试和老页面）和最新版扁平化 DOM 结构。
- **高健壮的文本特征分析与正则提取**：弃用脆弱的具体类名，改用包含特定锚点属性和文本关键字（如 `"粉丝"`, `"视频"`, `"space.bilibili.com"`, `"title"` 属性）的检索。
- **完整提取指标**：精确提炼出 UP主昵称、UID/mid、粉丝数（支持万位算术换算）和个人简介签名（usign）。

**Non-Goals:**
- 不修改 `BiliUidMatcher` 的启发式打分机制。
- 不增加额外的大模型（LLM）API 调用开销。

## Decisions

### 决策 1：卡片容器自适应定位
- **方案 A**：直接读取包含 `.up-item`, `.user-item`, `.user-content`, `.up-card-content` 等所有可能类名的并集。
- **方案 B (采纳)**：使用更通用的 CSS Selector（如 `.up-item, .user-item, [class*="user-item"], [class*="user-content"]`），并在查询后额外校验是否含有指向 `space.bilibili.com` 的超链接。
- **理由**：方案 B 极具鲁棒性，即使类名被随机化（如 `data-v-` 前缀混淆），由于用户主页超链接是跳转的物理硬契约，只要包含主页超链接即可被捕获。

### 决策 2：昵称与 UID 绑定提取
- **决策**：直接提取包含 `space.bilibili.com` 文本的 `<a>` 标签。
  - 链接的 `inner_text` 为昵称。
  - 链接的 `href` 属性匹配 `/space.bilibili.com/(\d+)/` 正则或进行 split 切片提取得到 UID/mid。
- **理由**：直接抛弃依赖 `.up-name` 类名，只要锚点链接正确，即可一次性以 100% 准确度定位昵称与 UID。

### 决策 3：粉丝量与个人简介多重降级正则比对
- **决策**：在卡片内寻找包含 `"粉丝"` 字样的元素。
  - 提取其 `title` 属性（防止过长被 CSS 阶段截断）或 `inner_text` 文本。
  - 使用正则匹配：`re.search(r"([\d\.]+)(万)?\s*粉丝", text)`
  - 提取签名（usign）：在新版中，简介常置于 `<span>` 内，或者位于段落的后半段。我们将优先读取内层 `<span>` 的文本；如果没有，则使用正则切除 `"视频"` 字段后的文本作为备用签名。

## Risks / Trade-offs

- **[Risk]** B站完全采用随机生成混淆的 Class。
  - **[Mitigation]** 我们的解析逻辑完全退回到对标签属性（如 `href`，`title`）和标签文本特征（如 `"粉丝"`, `"视频"`, `" space.bilibili.com"`）的感知，不强依赖于特定类名，能抵抗高强度的 Class 随机混淆。
