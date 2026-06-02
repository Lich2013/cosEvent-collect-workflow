## Why

在当前的爬虫抓取逻辑中，`BaseScraper` 扮演着微博和B站网页端无头抓取的核心会话管理器。然而，在以下两个关键场景中存在稳定性和安全性隐患：
1. **Playwright 异步超时无法优雅捕获**：由于 `playwright.async_api.TimeoutError` 并非 Python 内置 `TimeoutError` 的子类，现有的 `except TimeoutError` 无法拦截页面超时异常，导致超时直接触发兜底的 Runtime Error，抛出冗长的堆栈轨迹，污染控制台日志。
2. **缺省无头指纹易被 WAF 封控**：Playwright 缺省的 Chrome 无头模式会发送包含 `HeadlessChrome` 敏感字样的 User-Agent 头，极易被各大社交平台（如微博、B站、小红书）的防爬风控机制（如防火墙、极验等）秒级识别并拦截，导致账号会话（Cookie）频繁失效。

现在引入此变更，旨在全面加固无头爬虫的抗封控与异常容错自愈能力。

## What Changes

- **修复 Playwright 超时捕获逻辑**：修改 `src/tools/playwright_base.py`，导入并精准捕获 `playwright.async_api.TimeoutError`，确保页面加载超时能被优雅静默跳过，记录正确的 `[Scraper Timeout ERROR]` 可观测日志，避免无谓的报错堆栈污染。
- **强化无头浏览器环境拟真防御**：在 `get_browser_context` 中创建 Context 时，显示配置真实的 macOS Desktop User-Agent 和标准的网页视口（Viewport）参数，彻底隐藏 `HeadlessChrome` 指纹，提高抓取阶段的抗封控防护等级。

## Capabilities

### New Capabilities

### Modified Capabilities
- `content-scraping`: 加固 Playwright 无头抓取基类的超时拦截自愈机制，并显示伪装浏览器 User-Agent 指纹以防封控拦截。

## Impact

- `src/tools/playwright_base.py`: 核心修改文件，加固浏览器上下文属性与异常捕获类型。
- `scraper_weibo` / `scraper_bilibili`: 所有基于 `BaseScraper` 运行的无头网页爬虫实例均会自适应继承此项加固安全属性。
