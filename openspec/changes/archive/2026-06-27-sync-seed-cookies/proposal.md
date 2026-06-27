## Why

目前爬虫在爬取成功时，只会动态将包含最新会话状态的 Cookies 写入运行期缓存 `runtime/{platform}/state.json` 中，而不会将它们同步更新到配置种子文件 `config/cookies/{platform}_cookies.json`。
这导致当运行期缓存被删除、损坏或由于风控被隔离降级时，系统退回到种子文件后，加载的依然是很久以前拷贝的过期 Cookie，降低了系统的鲁棒性与自愈恢复率。

为了保证种子文件的时效性，亟需实现“运行期新 Cookie 自动同步回写至种子文件”的功能。

## What Changes

- **种子 Cookie 同步回写**：在 `BaseScraper.scrape_flow_handler` 成功执行并保存 `storage_state` 之后，将最新的浏览器 Cookie 提取并序列化为单行 raw cookie 字符串格式（或者保存为标准 Playwright JSON 格式），回写并覆盖 `config/cookies/{platform}_cookies.json`。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 增加采集会话回写自更新能力，支持自动将抓取成功时更新的 Cookie 状态同步写入静态配置文件种子中。

## Impact

- 影响 `src/tools/playwright_base.py`：在 `scrape_flow_handler` 成功执行完 `context.storage_state()` 后，增加提取并更新 `self.seed_file` 文件的逻辑。
