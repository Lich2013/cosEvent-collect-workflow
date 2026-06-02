## Why

有些 Coser 会将未来的漫展计划、一日店长排班等高价值日程信息直接写在社交平台的个人简介（Bio/签名/个人介绍）中，并在行程结束后手动编辑更新。目前系统仅抓取正文动态，导致这些关键日程信息被遗漏，因此需要将个人简介（Bio）作为一种特殊的虚拟推文进行抓取与版本化管理，从而闭环这部分高价值数据源。

## What Changes

- **个人简介抓取支持**：在微博、B站、小红书的 Playwright Scraper 及 gRPC Scraper 中，在执行常规动态抓取的同时，自动提取对应 Coser 在该平台上的个人简介（Bio）文本。
- **虚拟动态合成**：将抓取到的 Bio 文本，合成为以 `bio_{uid}` 为 `post_id` 的虚拟动态记录，并以当前抓取时间（北京时间）作为其发布时间。
- **自适应版本控制与增量分析**：将合成的虚拟动态投递至数据库存储层，天然复用既有的内容变动比对版本管理机制（如 `bio_{uid}#v1`, `bio_{uid}#v2`）。如果 Bio 内容发生改变，则物理增加新版本行，重置分析标记并触发 AI Agent 的增量提炼流程。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 新增对 Coser 个人简介（Bio/签名）的提取支持，并以 `bio_{uid}` 的规范合成虚拟推文，使之天然兼容既有的物理版本控制与增量提取链路。

## Impact

- **Scrapers 采集端** (`src/tools/`):
  - `weibo_scraper.py`：在 Playwright 打开个人主页时，获取用户个人介绍。
  - `bilibili_scraper.py`：在 gRPC `DynSpace` 响应中读取 `signature` 字段（降级 Playwright 下在主页提取 `.h-sign` DOM 文本）。
  - `xhs_scraper.py`：在 Playwright 主页提取用户个人介绍。
- **存储与事务层** (`src/services/db/coser_repository.py`):
  - 确保以 `bio_{uid}` 格式合成的动态可顺畅执行 `save_raw_posts` 中的自适应版本控制与去重保存。
