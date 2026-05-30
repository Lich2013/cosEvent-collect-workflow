## Why

在 B站 最新迭代的搜索结果页面中，其 HTML DOM 结构（CSS 布局与 Class 样式）为了增强防爬与自适应呈现进行了大幅重构，引入了例如 `user-content`, `i_card_title`, `text_ellipsis` 等更扁平的类名和动态的 CSS Module 随机属性标签。

这导致原有的 DOM 解析器（高度依赖老旧的 `.up-item`, `.up-name`, `.fans` 等选择器）会由于定位失败而无法提取任何候选人数据，进而造成自动同步 UID 功能的严重漏配。我们需要重新设计一套具备**自适应、多层降级（Multi-selector Fallback Chain）与特征正则比对的 DOM 健壮解析方案**。

## What Changes

- **DOM 选择器多维 fallback 兼容链**：重构 `BilibiliScraper` 中的单条与批量搜索 DOM 解析流，支持新旧 B站 搜索页面元素并存的解析模式。
- **基于核心属性（Anchor URL）的 UP主与 UID 提取**：不再依赖脆弱的类名，通过在卡片容器内自适应过滤指向 `space.bilibili.com` 的 HTML `<a>` 标签精确拉取用户名与 `mid`。
- **基于文本特征正则匹配的粉丝数与签名提取**：针对将多维度指标浓缩至单个 `<p>` 段落的全新布局，采用高精度正则从 `title` 属性及 `inner_text` 中智能匹配粉丝数值（支持万级换算）并提取个人简介。

## Capabilities

### New Capabilities
<!-- 无新增能力，主要针对 UID 同步特性的健壮性补强 -->

### Modified Capabilities
- `bili-uid-sync`: 提升在反爬降级与 DOM 兜底解析场景下的特征匹配覆盖率和自适应抓取精度。

## Impact

- 采集引擎：`src/tools/bilibili_scraper.py` 中的单个查询 `search_bilibili_user` 和批量查询 `search_bilibili_users_batch` 的 DOM 解析分支。
- 单元测试：`tests/test_bili_uid_matcher.py` 或回归测试以保障整体稳定性。
