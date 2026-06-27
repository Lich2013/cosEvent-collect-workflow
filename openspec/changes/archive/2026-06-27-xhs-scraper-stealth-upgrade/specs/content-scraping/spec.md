## MODIFIED Requirements

### Requirement: Playwright 无头爬虫超时自愈与浏览器特征拟真
系统必须且 SHALL 对无头网页端抓取的底层会话生命周期进行加固防护，实现超时的精确自愈拦截与防爬风控特征伪装防御：
1. **超时精准捕获与自愈**：无头爬虫在加载网页和执行具体爬取动作时，必须且 SHALL 精准捕获 `playwright.async_api.TimeoutError` 以及内置 `TimeoutError` 异常。系统必须且 SHALL 对超时情况执行优雅静默降级处理，打印 `[Scraper Timeout ERROR]` 并记录为超时类型的日志且返回空结果列表，绝对不允许异常向上传播导致主定时进程崩溃。
2. **无头浏览器指纹特征防封控伪装与 WebDriver 特征抹除**：系统在以无头模式创建浏览器上下文（Browser Context）时，必须且 SHALL 显示配置伪装的桌面浏览器 User-Agent 字符串（去除了 `HeadlessChrome` 敏感无头特异字样），设置符合真实桌面设备的屏幕视口参数（`viewport`）。同时，在启动 Chromium 浏览器时必须且 SHALL 传入禁用 Blink features 的启动参数（包含 `--disable-blink-features=AutomationControlled`），在运行底层抹除 WebDriver 指纹，避免被社交平台安全风控防火墙（WAF）拦截识别。
3. **随机请求时间延迟抖动 (Sleep Jitter)**：在工作流编排调度层 `WorkflowOrchestrator` 循环抓取小红书等高敏感数据源的 Coser 时，为了模拟真实人机交互，相邻两个请求之间必须且 SHALL 执行 7.0 到 10.0 秒的随机休眠等待，彻底规避高频爬取行为。
4. **持久会话损坏自动熔断冷启动**：当读取本地会话缓存（`state.json`）遭遇文件为空或格式损坏抛出 JSON 解析异常时，系统必须且 SHALL 自动触发损坏文件清除，并优雅安全地降级回静态种子 Cookie 重新进行冷启动，保障爬虫持续的自愈力。
5. **风控/限流 Session 隔离保护**：当爬虫检测到遭遇平台风控拦截（例如拦截接口失败且 DOM 也解析失败、或抛出自定义限流异常时），系统必须且 SHALL 停止最新的会话回写，绝对不允许调用 `context.storage_state` 覆写持久化会话，以隔离受污染的 Session 并保护本地 `state.json` 始终处于上一轮健康的登录状态中。

#### Scenario: 超时与损坏发生时成功触发静默自愈降级且不崩溃
- **WHEN** 页面在设置的 15s 内加载超时或 `state.json` 发生损坏时，启动网页爬取任务
- **THEN** 系统顺利自动清除损坏的 `state.json` 缓存，并在加载超时异常发生时，精准捕获 `playwright.async_api.TimeoutError`，静默输出超时警告日志并优雅返回空列表，主 CLI 抓取进程保持完全正常执行

#### Scenario: 规避 WebDriver 特征检测并随机延时爬取
- **WHEN** 启动小红书多用户爬取任务，且浏览器以上下文配置加载时
- **THEN** 浏览器成功隐蔽 `navigator.webdriver` 自动化参数特征，并在抓取各个 Coser 主页之间执行了随机 7 到 10 秒的休眠延迟，避免触发限流

#### Scenario: 遭遇风控限流时成功隔离 Session 缓存不污染本地
- **WHEN** 小红书爬虫抓取接口和页面 DOM 均超时失败抛出限流异常时
- **THEN** 调度器捕获该异常，跳过 `storage_state` 的保存回写，从而使持久化 `state.json` 的有效 Cookie 会话不受拦截污染
