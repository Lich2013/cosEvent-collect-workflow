## ADDED Requirements

### Requirement: 小红书业务级会话健康分类与安全回写
系统必须且 SHALL 对小红书 Bio-only 抓取中的 `otherinfo` Ajax 响应和页面状态进行业务级健康分类，不能仅以 HTTP 200、DOM 是否存在或返回列表是否为空作为成功依据。分类结果必须至少包含：
- `healthy`：用户资料结构有效且 Bio 非空；
- `empty_bio`：用户资料结构有效但 Bio 为空；
- `auth_invalid`：登录态失效、Cookie 不可用或页面跳转登录；
- `rate_limited`：验证码、滑块、安全验证、访问频繁或平台风控；
- `not_found_or_private`：用户不存在、被封禁、私密或无访问权限；
- `unknown_schema`：接口结构变化或无法识别的响应格式。

系统必须且 SHALL 仅在 `healthy` 或 `empty_bio` 状态下允许会话健康通过。对于 `auth_invalid`、`rate_limited`、`not_found_or_private`、`unknown_schema`，系统必须且 SHALL 跳过 `runtime/xhs/state.json` 与 `config/cookies/xhs_cookies.json` 的回写，并记录不含 Cookie 值的结构化日志。

#### Scenario: 小红书 Bio 正常返回并生成虚拟动态
- **WHEN** `otherinfo` 响应包含有效用户资料结构且 `data.desc` 非空时
- **THEN** 系统 SHALL 将状态分类为 `healthy`，合成唯一一条 `bio_{uid}` 虚拟动态，并允许健康会话回写

#### Scenario: 小红书 Bio 为空但用户资料结构有效
- **WHEN** `otherinfo` 响应明确表示用户存在且 `data.desc` 为空字符串或空白文本时
- **THEN** 系统 SHALL 将状态分类为 `empty_bio`，不生成虚拟动态，但允许健康会话结束和正常调度轮转

#### Scenario: 小红书登录态失效时阻止会话污染
- **WHEN** `otherinfo` 响应或页面状态显示登录失效、Cookie 不可用或跳转登录页时
- **THEN** 系统 SHALL 将状态分类为 `auth_invalid`，返回空结果并跳过 `state.json` 和种子 Cookie 回写

#### Scenario: 小红书触发验证或风控时进入隔离
- **WHEN** 页面或响应出现验证码、滑块、安全验证、访问频繁或风控特征时
- **THEN** 系统 SHALL 将状态分类为 `rate_limited`，停止本轮小红书后续抓取或触发平台级冷却，并禁止会话回写

### Requirement: 小红书关键 Cookie 校验与可信种子保护
系统必须且 SHALL 在小红书健康会话回写种子 Cookie 前执行关键 Cookie 校验。小红书关键 Cookie 至少包含 `web_session`、`a1`、`websectiga`、`xsecappid`，这些值必须存在且非空；`id_token` 可作为可观测字段记录但不作为强制必需项。若关键 Cookie 缺失，系统必须且 SHALL 允许当前结果返回，但禁止覆盖 `config/cookies/xhs_cookies.json`。

#### Scenario: 小红书关键 Cookie 完整时允许种子回写
- **WHEN** 小红书抓取状态健康且当前浏览器上下文包含所有关键 Cookie 时
- **THEN** 系统 SHALL 按既有格式安全更新 `config/cookies/xhs_cookies.json`

#### Scenario: 小红书关键 Cookie 缺失时保护种子文件
- **WHEN** 小红书抓取状态健康但当前浏览器上下文缺失 `web_session`、`a1`、`websectiga` 或 `xsecappid` 任一关键 Cookie 时
- **THEN** 系统 SHALL 跳过种子 Cookie 回写并记录缺失 Cookie 名称，但不得输出 Cookie 值

### Requirement: 小红书平台级冷却与失败类型调度
系统必须且 SHALL 为抓取调度记录平台级失败类型和下一次重试时间，使小红书不同失败状态采用不同冷却策略。调度状态必须至少记录 `last_scrape_status`、`last_scrape_error`、`next_retry_after`。调度查询必须且 SHALL 过滤仍在 `next_retry_after` 之后的记录，避免冷却期内反复访问同一平台账号。

状态策略必须满足：
- `success`、`empty_bio`：正常更新抓取时间戳并参与常规轮转；
- `timeout`：短冷却后允许重试；
- `auth_invalid`：长冷却并提示需要人工刷新 Cookie；
- `rate_limited`：平台级长冷却，且当前运行周期应暂停后续小红书抓取；
- `not_found_or_private`：正常轮转或长间隔轮转，不应高频重试；
- `unknown_schema`：中等冷却并记录响应摘要。

#### Scenario: 小红书风控后暂停本轮后续小红书任务
- **WHEN** 任一小红书账号抓取被分类为 `rate_limited` 时
- **THEN** 调度器 SHALL 设置平台级冷却，并在当前运行周期跳过后续小红书账号，避免继续触发风控

#### Scenario: 小红书网络超时使用短冷却
- **WHEN** 小红书抓取因 Playwright 超时或临时网络失败结束时
- **THEN** 系统 SHALL 记录 `last_scrape_status='timeout'` 和短 `next_retry_after`，而非立即反复重试

#### Scenario: 冷却期内的账号不进入调度队列
- **WHEN** 某小红书账号的 `next_retry_after` 晚于当前系统时间时
- **THEN** `list_active_cosers_by_schedule('xhs', ...)` SHALL 跳过该账号，直到冷却时间到达

### Requirement: 小红书批次上下文复用与自然访问节奏
系统必须且 SHALL 支持小红书批次抓取时复用同一个 Playwright Browser/Context 顺序访问多个用户主页，减少高频冷启动特征。批次内访问必须配置稳定的 User-Agent、viewport、locale、timezone、permissions，并执行页面预热、自然停留时间、有限滚动和随机 jitter。若检测到登录页、验证码、滑块或安全验证，系统必须立即停止后续交互并进入冷却，不得尝试绕过验证。

小红书核心接口请求必须且 SHALL 优先由真实页面导航后的前端 JS 自然触发，确保 Referer、Origin、Cookie、User-Agent、路由状态和页面执行环境自然一致。系统不得使用 Python HTTP 客户端直接请求小红书核心接口。若必须使用 Playwright request 进行诊断或兜底，请求必须复用当前 BrowserContext，并显式对齐当前页面的 Referer、Origin、User-Agent 与 Cookie，且不得绕过登录、验证或访问控制。

#### Scenario: 小红书批次复用同一上下文顺序抓取
- **WHEN** 调度器在同一运行周期内处理多个小红书账号时
- **THEN** 系统 SHALL 优先复用同一个 Browser/Context 顺序访问，账号间执行随机等待，并在批次结束后统一关闭上下文

#### Scenario: 小红书访问前进行轻量预热
- **WHEN** 小红书批次上下文首次创建时
- **THEN** 系统 SHALL 先访问小红书首页或安全的资料页进行轻量预热，再访问目标用户主页

#### Scenario: 小红书接口由页面上下文自然触发
- **WHEN** 系统需要获取小红书用户 `otherinfo` 数据时
- **THEN** 系统 SHALL 优先通过访问用户主页等待页面前端自然发起接口请求，而不是脱离页面上下文直接请求接口

#### Scenario: 小红书兜底请求保持 Referer 与 Origin 一致
- **WHEN** 未来实现中必须使用 Playwright request 兜底请求小红书核心接口时
- **THEN** 请求 SHALL 复用当前 BrowserContext，并携带与当前页面一致的 Referer、Origin、User-Agent 和 Cookie，不得使用 Python HTTP 客户端直接请求

#### Scenario: 检测到验证页面时停止模拟交互
- **WHEN** 页面状态显示验证码、滑块、安全验证或访问频繁时
- **THEN** 系统 SHALL 停止滚动、点击或后续页面访问，记录 `rate_limited` 并进入冷却

## MODIFIED Requirements

### Requirement: 个人主页简介抓取与虚拟推文合成

系统必须且 SHALL 在微博、B站、小红书三大平台的抓取逻辑中，自动提取 Coser 的个人主页简介（Bio/签名/个人介绍）文本，并合成为一条特殊的虚拟推文动态注入抓取列表：
- **虚拟动态标识**：虚拟推文的 `post_id` 必须且 SHALL 为 `bio_{uid}` 格式（例如 `bio_1923024604`），以绝对防范各平台未来真实推文 ID 的碰撞风险。
- **发布时间重锚**：虚拟推文的 `published_at` 必须且 SHALL 强制重锚为当前的北京抓取时刻（格式 `YYYY-MM-DD HH:MM:SS`），为后续的 AI 时间对齐推算提供确定的时空定位基准。
- **零成本数据合流**：合成的虚拟推文对象必须且 SHALL 原生追加到抓取到的推文列表最末尾一并返回，以无缝流转至数据库存储层，天然触发内容变动比对、去重及 `#v` 物理版本控制（如 `bio_{uid}#v1`, `bio_{uid}#v2`）。**对于小红书（XHS）平台，抓取列表最终应仅包含该条虚拟推文（不包含常规笔记内容）；而微博与B站平台仍需同时包含常规抓取到的笔记与动态。**
- **WAF 防风控与多级选择器降级**：系统在网页模式下抓取个人主页简介时，必须且 SHALL 采用多级候选选择器字典并在应用层进行 `try-except` 包裹。小红书必须优先解析 `otherinfo` 接口，其后使用多个 DOM 候选选择器和页面状态检测降级；若所有选择器均定位失败或提取发生异常，系统必须且 SHALL 根据业务健康分类决定是正常空 Bio、页面改版、登录失效还是风控状态，绝对不允许因此中断整个 CLI 进程。
- **空白简介前置拦截防御**：系统在 Scraper 组装虚拟推文时，必须且 SHALL 执行非空门槛校验。若提取 Rarer 的个人简介文本经 `strip()` 去除首尾空白后为 `""`，系统必须且 SHALL 拒绝生成该虚拟推文，也不得将其追加到推文列表中，物理断绝空白版本无休止递增膨胀。

#### Scenario: 成功抓取个人简介并合成为虚拟推文
- **WHEN** 启动针对特定 Coser 平台（如 weibo 或 xhs）的动态抓取，且其个人简介文本内容发生更新变动时
- **THEN** 采集层 SHALL 自动提取其最新简介文本，合成为 `post_id="bio_1923024604"` 且发布时间为当前抓取时刻 the 虚拟动态，数据库存储层物理递增该动态的版本至 `bio_1923024604#v{n}`，并原子的标记 `is_analyzed = 0` 触发 AI 增量分析提炼。**对于小红书（XHS），返回的推文列表仅包含该虚拟动态。**

#### Scenario: 简介解析出错时优雅降级不阻断抓取
- **WHEN** 抓取 B 站主页或小红书主页由于前端改版导致所有备选选择器及拦截均失效，触发抓取异常时
- **THEN** 采集端 Scraper SHALL 捕获异常，打印警告日志，默认返回空字符串或分类后的空结果，并且其余平台正常的博客动态仍能完美抓取交付，抓取作业绝不崩溃中断

#### Scenario: 简介为空白或被清空时自动跳过虚拟动态合成
- **WHEN** 抓取到 Coser 清空后的空白简介 `""` 或纯空白符号时
- **THEN** 采集端 Scraper SHALL 在组装前置过滤阶段直接将其丢弃，不生成 `bio_{uid}` 虚拟动态，也不在返回列表中追加，数据库版本保持静默不发生膨胀

### Requirement: Playwright 无头爬虫超时自愈与浏览器特征拟真
系统必须且 SHALL 对无头网页端抓取的底层会话生命周期进行加固防护，实现超时的精确自愈拦截、防爬风控特征伪装防御、会话健康判定与安全回写保护：
1. **超时精准捕获与自愈**：无头爬虫在加载网页 and 执行具体爬取动作时，必须且 SHALL 精准捕获 `playwright.async_api.TimeoutError` 以及内置 `TimeoutError` 异常。系统必须且 SHALL 对超时情况执行优雅静默降级处理，打印 `[Scraper Timeout ERROR]` 并记录为超时类型的日志且返回空结果列表，绝对不允许异常向上传播导致主定时进程崩溃。
2. **无头浏览器指纹特征防封控伪装与 WebDriver 特征抹除**：系统在以无头模式创建浏览器上下文（Browser Context）时，必须且 SHALL 显示配置伪装的桌面浏览器 User-Agent 字符串（去除了 `HeadlessChrome` 敏感无头特异字样），设置符合真实桌面设备的屏幕视口参数（`viewport`）。同时，在启动 Chromium 浏览器时必须且 SHALL 传入禁用 Blink features 的启动参数（包含 `--disable-blink-features=AutomationControlled`），在运行底层抹除 WebDriver 指纹，避免被社交平台安全风控防火墙（WAF）拦截识别。
3. **随机请求时间延迟抖动 (Sleep Jitter)**：在工作流编排调度层 `WorkflowOrchestrator` 循环抓取小红书等高敏感数据源的 Coser 时，为了模拟真实人机交互，相邻两个请求之间必须且 SHALL 执行可配置的随机休眠等待；小红书批次必须支持更宽的等待区间、周期性长暂停以及错误后的指数退避。
4. **持久会话损坏自动熔断冷启动**：当读取本地会话缓存（`state.json`）遭遇文件为空或格式损坏抛出 JSON 解析异常时，系统必须且 SHALL 自动触发损坏文件清除，并优雅安全地降级回静态种子 Cookie 重新进行冷启动，保障爬虫持续的自愈力。
5. **风控/限流 Session 隔离保护**：当爬虫检测到遭遇平台风控拦截（例如拦截接口失败且 DOM 也解析失败、抛出自定义限流异常、或小红书业务响应被分类为 `rate_limited` 时），系统必须且 SHALL 停止最新的会话回写，绝对不允许调用 `context.storage_state` 覆写持久化会话，也不得覆写静态种子 Cookie 文件，以隔离受污染的 Session 并保护本地可信凭证。
6. **健康会话下的安全 Cookie 回写**：当 Playwright 网页抓取任务成功执行完毕且平台健康判定通过时，系统必须且 SHALL 获取当前上下文中的有效 Cookie 列表，根据各平台规则重新组装并自动更新回写覆盖静态种子文件 `config/cookies/{platform}_cookies.json`。若平台健康状态未知、登录失效、风控或关键 Cookie 缺失，系统必须且 SHALL 跳过种子 Cookie 回写。

#### Scenario: 超时与损坏发生时成功触发静默自愈降级且不崩溃
- **WHEN** 页面在设置的 15s 内加载超时或 `state.json` 发生损坏时，启动网页爬取任务
- **THEN** 系统顺利自动清除损坏的 `state.json` 缓存，并在加载超时异常发生时，精准捕获 `playwright.async_api.TimeoutError`，静默输出超时警告日志并优雅返回空列表，主 CLI 抓取进程保持完全正常执行

#### Scenario: 规避 WebDriver 特征检测并随机延时爬取
- **WHEN** 启动小红书多用户爬取任务，且浏览器以上下文配置加载时
- **THEN** 浏览器成功隐蔽 `navigator.webdriver` 自动化参数特征，并在抓取各个 Coser 主页之间执行随机等待、必要长暂停和错误退避，避免触发限流

#### Scenario: 遭遇风控限流时成功隔离 Session 缓存不污染本地
- **WHEN** 小红书爬虫抓取接口和页面 DOM 均超时失败抛出限流异常，或业务响应被分类为 `rate_limited` 时
- **THEN** 调度器捕获该异常或分类结果，跳过 `storage_state` 和种子 Cookie 的保存回写，从而使持久化 `state.json` 与可信种子 Cookie 不受拦截污染

#### Scenario: 抓取健康时自动同步回写更新静态种子 Cookie 文件
- **WHEN** 任意网页端爬虫抓取任务执行成功且平台健康判定通过，并且关键 Cookie 校验通过时
- **THEN** 采集模块自动提取当前的有效 Cookie 状态并覆写 `config/cookies/{platform}_cookies.json` 种子文件，使下次冷启动可直接采用最新可用凭证
