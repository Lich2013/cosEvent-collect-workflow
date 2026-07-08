## MODIFIED Requirements

### Requirement: Playwright 无头爬虫超时自愈与浏览器特征拟真
系统必须且 SHALL 对无头网页端抓取的底层会话生命周期进行加固防护，实现超时的精确自愈拦截、防爬风控特征伪装防御、业务级会话健康判定以及安全回写保护：
1. **超时精准捕获与自愈**：无头爬虫在加载网页 and 执行具体爬取动作时，必须且 SHALL 精准捕获 `playwright.async_api.TimeoutError` 以及内置 `TimeoutError` 异常。系统必须且 SHALL 对超时情况执行优雅静默降级处理，打印 `[Scraper Timeout ERROR]` 并记录为超时类型的日志且返回空结果列表，绝对不允许异常向上传播导致主定时进程崩溃。
2. **无头浏览器指纹特征防封控伪装与 WebDriver 特征抹除**：系统在以无头模式创建浏览器上下文（Browser Context）时，必须且 SHALL 显示配置伪装的桌面浏览器 User-Agent 字符串（去除了 `HeadlessChrome` 敏感无头特异字样），设置符合真实桌面设备的屏幕视口参数（`viewport`）。同时，在启动 Chromium 浏览器时必须且 SHALL 传入禁用 Blink features 的启动参数（包含 `--disable-blink-features=AutomationControlled`），在运行底层抹除 WebDriver 指纹，避免被社交平台安全风控防火墙（WAF）拦截识别。
3. **随机请求时间延迟抖动 (Sleep Jitter)**：在工作流编排调度层 `WorkflowOrchestrator` 循环抓取小红书等高敏感数据源的 Coser 时，为了模拟真实人机交互，相邻两个请求之间必须且 SHALL 执行 7.0 到 10.0 秒的随机休眠等待，彻底规避高频爬取行为。
4. **持久会话损坏自动熔断冷启动**：当读取本地会话缓存（`state.json`）遭遇文件为空或格式损坏抛出 JSON 解析异常时，系统必须且 SHALL 自动触发损坏文件清除，并优雅安全地降级回静态种子 Cookie 重新进行冷启动，保障爬虫持续的自愈力。
5. **用户刷新种子 Cookie 后优先冷启动**：当平台种子 Cookie 文件 `config/cookies/{platform}_cookies.json` 的修改时间晚于对应的运行态 `runtime/{platform}/state.json` 时，系统必须且 SHALL 视为用户已手动刷新可信凭证，旁路或清除旧 `state.json`，优先使用种子 Cookie 创建新的浏览器上下文，确保新凭证立即生效。
6. **微博业务级会话健康判定**：微博抓取必须且 SHALL 对 `mymblog` Ajax 响应体进行业务结构校验，不能仅以 HTTP 200 作为成功依据。若响应明确包含成功结构且 `data.list` 为列表，则视为健康响应（列表可为空）；若响应包含登录失效、权限异常、验证/风控、`data` 缺失或未知 schema，系统必须且 SHALL 将其标记为非健康会话，并记录不含 Cookie 值的结构摘要日志。
7. **微博会话自愈重试**：当微博使用 `state.json` 启动后检测到业务级会话失效时，系统必须且 SHALL 跳过当前上下文的 `storage_state` 和种子 Cookie 回写，删除或旁路旧 `runtime/weibo/state.json`，再使用 `config/cookies/weibo_cookies.json` 冷启动重试一次。若重试仍无法取得健康响应，系统必须且 SHALL 优雅返回空结果并记录需要人工刷新 Cookie 的警告，绝不允许无限重试。
8. **风控/限流 Session 隔离保护**：当爬虫检测到遭遇平台风控拦截（例如拦截接口失败且 DOM 也解析失败、抛出自定义限流异常、或微博业务响应被判定为验证/风控状态时），系统必须且 SHALL 停止最新的会话回写，绝对不允许调用 `context.storage_state` 覆写持久化会话，也不得覆写静态种子 Cookie 文件，以隔离受污染的 Session 并保护本地可信凭证。
9. **健康会话下的安全回写**：当 Playwright 网页抓取任务成功执行完毕且平台健康判定通过时，系统必须且 SHALL 回写本地 `state.json`。静态种子文件 `config/cookies/{platform}_cookies.json` 仅允许在健康判定通过且当前上下文包含平台关键 Cookie 时被覆盖；若健康状态未知、异常、风控或登录失效，系统必须且 SHALL 跳过种子 Cookie 回写并记录原因。回写时必须保留既有文件格式，且不得在日志中输出 Cookie 值。

#### Scenario: 超时与损坏发生时成功触发静默自愈降级且不崩溃
- **WHEN** 页面在设置的 15s 内加载超时或 `state.json` 发生损坏时，启动网页爬取任务
- **THEN** 系统顺利自动清除损坏的 `state.json` 缓存，并在加载超时异常发生时，精准捕获 `playwright.async_api.TimeoutError`，静默输出超时警告日志并优雅返回空列表，主 CLI 抓取进程保持完全正常执行

#### Scenario: 规避 WebDriver 特征检测并随机延时爬取
- **WHEN** 启动小红书多用户爬取任务，且浏览器以上下文配置加载时
- **THEN** 浏览器成功隐蔽 `navigator.webdriver` 自动化参数特征，并在抓取各个 Coser 主页之间执行了随机 7 到 10 秒的休眠延迟，避免触发限流

#### Scenario: 用户更新种子 Cookie 后自动旁路旧 state
- **WHEN** 用户更新 `config/cookies/weibo_cookies.json`，且旧 `runtime/weibo/state.json` 仍存在并且文件级检查未过期时，启动微博抓取任务
- **THEN** 系统 SHALL 基于种子 Cookie 文件更新较新的事实旁路旧 `state.json`，直接注入新的种子 Cookie 冷启动，并在健康抓取后生成新的 `runtime/weibo/state.json`

#### Scenario: 微博 state 业务级失效时使用种子 Cookie 自愈重试
- **WHEN** 微博 `state.json` 可读且 cookie 未显式过期，但 `mymblog` HTTP 200 响应缺失有效 `data.list` 或返回登录态异常结构时
- **THEN** 系统 SHALL 判定当前 state 业务级失效，跳过本轮会话和种子 Cookie 回写，删除或旁路旧 `state.json`，使用 `config/cookies/weibo_cookies.json` 冷启动重试一次

#### Scenario: 微博种子 Cookie 也失效时不污染兜底源
- **WHEN** 微博 state 业务级失效后使用种子 Cookie 重试，但重试响应仍为登录失效、验证/风控或未知异常结构
- **THEN** 系统 SHALL 优雅返回空结果并记录警告，同时不得覆写 `runtime/weibo/state.json` 和 `config/cookies/weibo_cookies.json`

#### Scenario: 遭遇风控限流时成功隔离 Session 缓存不污染本地
- **WHEN** 小红书爬虫抓取接口和页面 DOM 均超时失败抛出限流异常，或微博 Ajax 响应被判定为验证/风控状态时
- **THEN** 调度器捕获该异常或健康判定结果，跳过 `storage_state` 的保存回写和静态种子 Cookie 覆写，从而使持久化 `state.json` 与种子 Cookie 的有效会话不受拦截污染

#### Scenario: 抓取健康时自动同步回写更新静态种子 Cookie 文件
- **WHEN** 任意网页端爬虫抓取任务执行成功，且平台健康判定确认当前上下文为有效登录或有效访问状态时
- **THEN** 采集模块自动回写 `state.json`，并在关键 Cookie 存在的前提下提取当前有效 Cookie 状态覆写 `config/cookies/{platform}_cookies.json` 种子文件，使下次冷启动可直接采用最新可用凭证
