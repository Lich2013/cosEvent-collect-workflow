## 1. BaseScraper 基类代码实现与加固

- [x] 1.1 修改 `src/tools/playwright_base.py`，从 `playwright.async_api` 导入 `TimeoutError as PlaywrightTimeoutError`，并加固 `scrape_flow_handler` 中的超时异常捕获，使其支持联合捕获 built-in `TimeoutError` 与 `PlaywrightTimeoutError`。
- [x] 1.2 在 `src/tools/playwright_base.py` 的 `get_browser_context` 中，在冷启动调用 `browser.new_context` 时，显示伪装配置 `user_agent` 为 `"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"`，并设置 `viewport` 为桌面视口 `{"width": 1280, "height": 800}`。

## 2. 单元测试与回归验证

- [x] 2.1 运行全量测试套件 `pytest tests/`，验证所有 70 项测试完美通过，确保捕获超时和指纹伪装对上游抓取/分析业务流程无任何副作用影响。
