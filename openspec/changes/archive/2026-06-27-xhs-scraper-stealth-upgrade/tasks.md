## 1. 核心代码改造

- [x] 1.1 在 `src/tools/xhs_scraper.py` 中定义或引入自定义风控限流异常类 `XhsRateLimitError(Exception)`。
- [x] 1.2 修改 `src/tools/xhs_scraper.py`：当 API 拦截超时且 DOM 解析也失效时，明确抛出 `XhsRateLimitError` 异常，中断当前爬取流程以防污染会话。
- [x] 1.3 修改 `src/tools/playwright_base.py` 的 Chromium 启动参数，在 `args` 中添加 `"--disable-blink-features=AutomationControlled"` 以抹除自动化特征。
- [x] 1.4 修改 `src/tools/playwright_base.py` 中的通用流程处理器 `scrape_flow_handler`：在捕获 `XhsRateLimitError` 异常时，仅记录日志并不执行 `context.storage_state` 会话写入，以隔离受污染的 Session。
- [x] 1.5 修改 `src/services/workflow_orchestrator.py` 的 `run_scrape` 方法：在小红书 Coser 的抓取循环中，增加 `7.0` 到 `10.0` 秒的随机延迟抖动 (Sleep Jitter)。

## 2. 单元测试与回归校验

- [x] 2.1 修改 `tests/test_coser_bio_scraping.py` 单元测试，添加在遭遇风控异常（抛出 `XhsRateLimitError`）时，验证 context 确实没有调用过 `storage_state` 的用例。
- [x] 2.2 运行小红书 Bio 抓取相关单元测试，验证所有功能和自愈逻辑全部正常通过。
