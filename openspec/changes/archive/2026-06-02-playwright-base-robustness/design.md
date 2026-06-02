## Context

在当前的无头抓取流程中，`BaseScraper` 作为网页端数据抓取的会话管理器，提供了双模 Cookie 解析与损坏自愈能力。然而在运行期间存在两项稳定性与防爬检测缺陷：
1. **Playwright 异步超时无法精准捕获**：经测试，在当前 Python 运行环境（Python 3.14.5）中，`playwright.async_api.TimeoutError` 并非 Python 内置 `TimeoutError` 的子类。这导致在网页加载超时发生时，现有的 `except TimeoutError as te` 分支失效，异常直接滑落至兜底的 `except Exception` 块中，并在控制台输出冗长堆栈转储（`traceback.print_exc()`），污染日志。
2. **缺省浏览器指纹特异性易遭风控**：在调用 `browser.new_context()` 时，由于未配置 User-Agent，Playwright 会使用 Chromium 默认参数，导致发送的 User-Agent 包含明显的 `HeadlessChrome` 敏感字样。这使得防爬机制（如微博、B站的防火墙或小红书的滑块验证）能够对其进行低成本特征识别并触发硬封控拦截，引发 Cookie 频繁失效。

---

## Goals / Non-Goals

**Goals:**
- 在 `src/tools/playwright_base.py` 中精准捕获 Playwright 级和内置级两种超时异常，恢复优雅超时日志和静默降级处理，不向上抛出异常。
- 伪装浏览器指纹特征，抹除 `HeadlessChrome` 指纹标识，自适应提防社交平台防爬安全网拦截。
- 保留现存的 `state.json` 损坏自愈、冷启动及种子 Cookie 逻辑，确保向后兼容。

**Non-Goals:**
- 不涉及任何数据库物理表结构的变更。
- 不影响第一方 gRPC 爬行通道（gRPC 不依赖 Playwright 无头环境运行）。

---

## Decisions

### 1. 双重超时异常联合捕获机制
- **决策**：从 `playwright.async_api` 导入 `TimeoutError as PlaywrightTimeoutError`，并将异常捕获子句修改为：
  ```python
  except (TimeoutError, PlaywrightTimeoutError) as te:
  ```
- **考量**：这样设计能完美兼顾 Python 标准库底层网络套接字超时（Built-in `TimeoutError`）以及 Playwright 在 15s 页面等待阈值届满时抛出的异步元素等待超时（`PlaywrightTimeoutError`），从根本上收口两种超时，防止漏网之鱼污染控制台。

### 2. 拟真二次元桌面指纹伪装
- **决策**：在 `get_browser_context` 函数中冷启动调用 `browser.new_context` 时，显示填入：
  - **`user_agent`**: `"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"` (标准 macOS 平台 Chrome Desktop)
  - **`viewport`**: `{"width": 1280, "height": 800}` (桌面端常用长宽比视口)
- **考量**：
  - 精准覆盖掉 Chromium 缺省的 `Headless` 指纹，完美伪装成真实的 macOS 桌面用户。
  - 设定固定且真实的桌面端 `viewport`（`1280x800`），避免因视口过小或缺省而触发移动端重定向或排版畸变，保护页面抓取选择器（Selectors）在各种分辨率下的强一致性。

---

## Risks / Trade-offs

- **[Risk]** 硬编码的 User-Agent 可能会随时间变得陈旧。
  - **Mitigation**：选用的是泛用性极强的现代 Chrome 稳定版指纹，在未来数年内各大平台均会保持主流向后兼容性，且该参数非常集中，后续极易提取到 `settings` 配置中。
- **[Risk]** 精准捕获超时可能掩盖真实的网络灾难（如整机断网）。
  - **Mitigation**：超时发生时，系统会准确记录 `[Scraper Timeout ERROR]` 日志并录入 Langfuse / 本地结构化日志，保证了完全的生产可观测性与追踪审计。
