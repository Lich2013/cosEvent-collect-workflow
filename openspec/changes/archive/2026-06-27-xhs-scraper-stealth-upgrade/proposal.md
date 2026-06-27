## Why

当前小红书（XHS）数据源的防爬与反风控（如 WAF、滑块验证）极其严格。目前本系统的小红书爬虫在连续请求多个 Coser 账号时没有请求延迟，容易暴露 WebDriver 自动化特征，且一旦遭遇风控重定向到验证码页面，会将受污染的被拦截状态无条件覆写到 `state.json` 会话缓存中，导致后续爬取陷入持续风控的死循环。

为了提高小红书数据抓取的稳定性和隐蔽性，亟需对小红书爬虫进行防检测防风控升级。

## What Changes

- **反爬特征抹除**：在启动 Playwright 浏览器时，通过传入特定启动参数抹除 `navigator.webdriver` 等自动化测试指纹特征。
- **引入随机休眠延迟**：在 `WorkflowOrchestrator` 的小红书爬取遍历循环中，引入 7 到 10 秒的随机延迟，模拟真实人机交互，避免高频请求触发频控。
- **会话状态风控隔离**：当小红书爬虫拦截 `otherinfo` 失败且 DOM 解析也无法获取 Bio（检测到疑似被限流重定向至滑块验证页）时，隔离受污染的 Session，跳过 `storage_state` 回写，确保 `state.json` 保持最后一次的健康状态。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 增加小红书内容爬取防检测与反爬防风控安全机制，包括自动化特征抹除、随机请求延迟抖动以及遭遇风控时的会话缓存隔离保护。

## Impact

- 影响 `src/tools/playwright_base.py`：修改启动参数及会话状态保存逻辑。
- 影响 `src/tools/xhs_scraper.py`：在捕获风控/解析失败时抛出特定异常，以防状态回写。
- 影响 `src/services/workflow_orchestrator.py`：在循环抓取小红书 Coser 时引入随机 `sleep`。
