## Context

目前系统使用 Playwright 无头模式抓取小红书 Coser 的个人主页，以获取 Bio 个人简介进行 AI 增量分析。由于没有对 WebDriver 自动化特征进行伪装，且在抓取多用户时无请求延迟，极易触发小红书 WAF 风控。一旦触发滑块验证，爬虫抓取逻辑虽然报错，但依然会在 `finally` 回写保存受污染的浏览器 Session，导致会话缓存文件 `state.json` 被永久污染，后续抓取彻底失效。

## Goals / Non-Goals

**Goals:**
- 抹除 Playwright / Chromium 的 WebDriver 自动化指纹。
- 在调度小红书爬取时引入随机延迟（7.0 ~ 10.0s），防止被网关识别为高频爬虫。
- 引入限流/风控时的 Session 隔离保护机制，防止滑块验证页面状态回写覆盖 `state.json`。

**Non-Goals:**
- 引入自动过滑块验证码等破解脚本或第三方付费服务（风控滑块仍由用户在 `headless=False` 模式下手动过，或通过隔离 Session 机制利用上一轮健康的 Cookie 自愈）。
- 更改小红书以外的其他数据源（Weibo、Bilibili）的抓取参数或逻辑。

## Decisions

### 决策一：WebDriver 自动化指纹特征抹除
- **方案选择**：在 `playwright_base.py` 启动 Chromium 浏览器时，通过 `args` 传入 `--disable-blink-features=AutomationControlled` 参数。
- **考量**：相较于引入第三方 `playwright-stealth` 库（可能存在 Python 3.14 兼容性问题或依赖冲突风险），直接配置 Blink 标志是最轻量、原生且完全兼容的做法。

### 决策二：会话缓存隔离与保护
- **方案选择**：在 `xhs_scraper.py` 中，如果接口解析失败且 DOM 选择器也获取不到 Bio（即判定爬取完全失败，属于疑似滑块阻断），抛出特定的 `XhsRateLimitError` 异常。在 `playwright_base.py` 的通用流程处理器 `scrape_flow_handler` 中捕获该特定异常时，仅记录日志并返回空列表，但**显式跳过 `storage_state` 的回写操作**。
- **考量**：这样可以物理避免污染本地 `state.json`，下一次运行依然可以使用上一轮保存的有效 Cookie，提升系统的自愈成功率。

### 决策三：随机延迟抖动 (Sleep Jitter) 位置
- **方案选择**：将随机延迟（`import random; await asyncio.sleep(random.uniform(7.0, 10.0))`）实现在 `WorkflowOrchestrator.run_scrape` 的循环分发小红书任务层。
- **考量**：在编排调度层实现控制能让调度行为更透明，也与微博/B站的同步频率控制解耦。

## Risks / Trade-offs

- **[Risk]** 小红书 WAF 不断升级，可能在未来除了 WebDriver 之外还会针对特定 IP 进行段级封锁。
  - **Mitigation**：用户可以结合代理 IP，或者在遇到频繁风控时，通过临时将 `headless` 切换为 `False` 并在弹出的窗口中手动拖动过一次滑块，系统便会自动将通关后的新 Session 存入 `state.json`，供无头模式后续运转。
- **[Risk]** 随机休眠延迟会导致爬取小红书的任务运行时间拉长。
  - **Trade-off**：牺牲了爬取的绝对效率以换取稳定性，在增量定时任务中该时间延迟是完全可以接受的。
