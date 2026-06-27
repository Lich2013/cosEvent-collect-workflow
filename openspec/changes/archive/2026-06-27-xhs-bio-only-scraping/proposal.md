## Why

小红书（Xiaohongshu/XHS）平台的页面结构与反爬机制多变，抓取完整的笔记列表容易触发账号封控或遭遇 WAF 拦截。
同时，大多数 Coser 习惯将最新的漫展计划、一日店长等高价值行程信息直接写在个人简介（Bio/签名）中。
为了降低风控风险、提升抓取效率并聚焦高价值日程数据，我们需要调整小红书的爬取模式，使其仅抓取 Coser 的个人简介（Bio）文本并合成为一条特殊的虚拟推文，不再爬取其常规笔记内容。

## What Changes

- **小红书抓取策略调整**：修改小红书 Scraper 行为，移除对其常规笔记（Notes）的拦截与提取逻辑，改为仅拦截与爬取 Coser 个人简介（Bio）信息。
- **虚拟动态合成**：保持 `bio_{uid}` 格式合成虚拟推文，并在其非空时投递至数据库以参与增量分析，若简介为空则不进行合成。
- **向下兼容数据流**：抓取并保存后，返回的数据契约以及最终更新去重行为与微博/B站平台完全保持一致，不对分析器及展示层造成任何破坏。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 变更小红书平台的爬取行为约束，只抓取个人简介（Bio）合成为虚拟推文，移除常规笔记内容的爬取要求。

## Impact

- `src/tools/xhs_scraper.py`：网络请求拦截由 `api/sns/web/v1/user_posted` 切换为 `api/sns/web/v1/user/otherinfo`，剔除笔记解析循环。
- `tests/test_coser_bio_scraping.py`：更新对应的单元测试，使其验证仅拦截 otherinfo 与 DOM 兜底的逻辑。
