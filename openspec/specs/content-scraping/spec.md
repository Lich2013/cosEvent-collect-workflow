# content-scraping Specification

## Purpose
This capability specifies requirements for scraping Coser social media feeds, managing raw post storage, fine-grained command filters, and personal bio virtual dynamic post synthesis.
## Requirements
### Requirement: 原始博文表的数据库定义与外键关联及多平台编辑版本控制
系统必须且 SHALL 在 SQLite 数据库中创建并维护原始博文表 `raw_posts`，用于缓存、去重与多版本回溯追踪。该表必须严格按照以下 SQL 规范建立，以确保与 Coser 实体的一对多物理外键关联，以及平台级的去重与编辑版本控制：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `coser_id` (INTEGER, NOT NULL, FOREIGN KEY REFERENCES `cosers`(`id`) ON DELETE CASCADE)
- `platform` (TEXT, NOT NULL)
- `post_id` (TEXT, NOT NULL) -- 微博二次编辑时动态追加版本后缀 `#v{edit_count}` (例如 `5039129502#v1`)
- `content` (TEXT, NOT NULL)
- `post_url` (TEXT, NULL)
- `is_analyzed` (INTEGER, DEFAULT 0)
- `edit_count` (INTEGER, DEFAULT 0) -- 编辑次数跟踪列
- `published_at` (TEXT, NULL) -- 原始发表/编辑时间列。若编辑次数 `edit_count > 0`，应优先填充物理精准编辑发布时刻或原始年份时间，并基于既存状态智能决策是否进行当前时间重锚
- `scraped_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)
- 唯一联合索引约束：`UNIQUE(platform, post_id)`

#### 跨平台编辑版本感知规约与高精度时间重锚：
- 微博平台：利用原生 API 字段 `edit_count` 驱动，若 `edit_count > 0`，动态拼接追加版本后缀 `#v{edit_count}`。爬虫层必须且 SHALL 尝试异步请求微博 `editHistory` 接口抓取最新编辑版本的真实 `statuses[0].created_at` 字段作为发布时间；若发生反爬或请求受限，系统必须且 SHALL 自动降级使用该微博的原始 `created_at` 以锁死年份上下文，绝不采用抓取时间兜底。数据库写入层必须且 SHALL 智能检测：若库中不存在任何该博文的先前版本（历史首次录入），则必须且 SHALL 维持爬虫传入的高精度/原始发布时间；若库中已存在先前版本（实时编辑检测），则必须且 SHALL 重锚为当前北京抓取时间以对齐相对日期解析原点。
- B站/小红书等无显式编辑计数的平台：系统必须且 SHALL 在保存博文时，进行已存内容（Content）的变化对比监测。若新抓取内容与数据库中已存内容发生不一致，系统必须且 SHALL 在应用层合成版本号，使 `edit_count = 数据库已存 edit_count + 1`，并对 `post_id` 追加 `#v{edit_count}` 后缀录入，以触发全新增量分析并流转软状态机。

#### Scenario: 成功创建或升级 raw_posts 表并支持编辑控制列与时间重锚
- **WHEN** 数据库初始化、执行数据库升级或爬取微博二次编辑信息时
- **THEN** `raw_posts` 中成功具备 `edit_count` 和 `published_at` 字段，编辑版本 `post_id` 自动追加 `#v` 版本后缀，`published_at` 精准重锚对齐为北京时间，联合索引及外键生效

### Requirement: Click 命令行支持抓取细粒度参数过滤
系统终端入口的 `scrape` 命令行必须且 SHALL 支持接收可选的 `--name`（姓名昵称）参数，以及具有指定枚举的选择参数 `--platform`（包含 `weibo`、`bilibili`、`xhs`、`all` 选项，默认 `all`）。
系统必须对这些参数进行正确的类型解析，并安全透传给下游编排调度层。

#### Scenario: 无参数默认执行全量抓取
- **WHEN** 终端以默认形式 `uv run python src/main.py scrape` 启动，未指定任何过滤选项
- **THEN** 系统 SHALL 自动抓取数据库中所有已激活 of Coser 的所有平台（微博、B站、小红书）动态，保持原有全量批处理作业行

#### Scenario: 带过滤参数执行特定单点抓取
- **WHEN** 终端以包含参数的命令（例如 `uv run python src/main.py scrape --name "池咲misa" --platform bilibili`）启动
- **THEN** 系统 SHALL 仅对昵称为 "池咲misa" 且处于激活状态 of Coser 启动 B 站平台抓取任务，其他 Coser 和平台任务必须且 SHALL 优雅旁路跳过

### Requirement: 抓取调度层条件筛选与免冷启动熔断
工作流编排调度层 `WorkflowOrchestrator.run_scrape` 必须且 SHALL 接收 `coser_name` 与 `platform` 作为可选筛选参数。
- 姓名过滤：在捞取活跃名单后，若指定了姓名过滤，系统必须且 SHALL 在内存中进行精准裁剪。若名单匹配后为空，系统必须且 SHALL 打印黄色 `WARNING` 并优雅返回 `(0, {}, 0)`，绝不允许抛出任何异常。
- 平台过滤：在大循环派发任务前，系统必须且 SHALL 进行平台校验。对于未被指定的平台，系统必须且 SHALL 提前执行 `continue` 跳过，杜绝其 Scraper 实例的构建、Playwright 无头浏览器冷启动与超时等待。
- 数据兼容：即使仅抓取单人或单平台，调度层返回的返回值必须且 SHALL 严格对齐已存的三元组契约 `(total_cosers, success_platforms, total_inserted)` 以保证终端渲染及统计层在零修改的前提下完全适配。

#### Scenario: 匹配特定 Coser 平台成功执行抓取并返回三元组契约
- **WHEN** 调度器传入有效的 Coser 姓名及指定平台进行同步抓取且有数据入库
- **THEN** 系统顺利仅对该 Coser 对应平台执行同步、物理去重及事务入库，并成功返回三元组契约以渲染精美的总结报告

### Requirement: 个人主页简介抓取与虚拟推文合成

系统必须且 SHALL 在微博、B站、小红书三大平台的抓取逻辑中，自动提取 Coser 的个人主页简介（Bio/签名/个人介绍）文本，并合成为一条特殊的虚拟推文动态注入抓取列表：
- **虚拟动态标识**：虚拟推文的 `post_id` 必须且 SHALL 为 `bio_{uid}` 格式（例如 `bio_1923024604`），以绝对防范各平台未来真实推文 ID 的碰撞风险。
- **发布时间重锚**：虚拟推文的 `published_at` 必须且 SHALL 强制重锚为当前的北京抓取时刻（格式 `YYYY-MM-DD HH:MM:SS`），为后续的 AI 时间对齐推算提供确定的时空定位基准。
- **零成本数据合流**：合成的虚拟推文对象必须且 SHALL 原生追加到抓取到的推文列表最末尾一并返回，以无缝流转至数据库存储层，天然触发内容变动比对、去重及 `#v` 物理版本控制（如 `bio_{uid}#v1`, `bio_{uid}#v2`）。
- **WAF 防风控与多级选择器降级**：系统在网页模式下抓取个人主页简介时，必须且 SHALL 采用多级候选选择器字典并在应用层进行 `try-except` 包裹。若所有选择器均定位失败或提取发生异常，系统必须且 SHALL 优雅输出警告日志，并返回空文本 `""` 兜底，绝对不允许因此中断整个 Coser 动态的抓取流。
- **空白简介前置拦截防御**：系统在 Scraper 组装虚拟推文时，必须且 SHALL 执行非空门槛校验。若提取的个人简介文本经 `strip()` 去除首尾空白后为 `""`，系统必须且 SHALL 拒绝生成该虚拟推文，也不得将其追加到推文列表中，物理断绝空白版本无休止递增膨胀。

#### Scenario: 成功抓取个人简介并合成为虚拟推文
- **WHEN** 启动针对特定 Coser 平台（如 weibo）的动态抓取，且其个人简介文本内容发生更新变动时
- **THEN** 采集层 SHALL 自动提取其最新简介文本，合成为 `post_id="bio_1923024604"` 且发布时间为当前抓取时刻的虚拟动态，数据库存储层物理递增该动态的版本至 `bio_1923024604#v{n}`，并原子的标记 `is_analyzed = 0` 触发 AI 增量分析提炼

#### Scenario: 简介解析出错时优雅降级不阻断抓取
- **WHEN** 抓取 B 站主页由于前端改版导致所有备选选择器均失效，触发抓取异常时
- **THEN** 采集端 Scraper SHALL 捕获异常，打印警告日志，默认返回空字符串，并且其余正常的博客动态仍能完美抓取交付，抓取作业绝不崩溃中断

#### Scenario: 简介为空白或被清空时自动跳过虚拟动态合成
- **WHEN** 抓取到 Coser 清空后的空白简介 `""` 或纯空白符号时
- **THEN** 采集端 Scraper SHALL 在组装前置过滤阶段直接将其丢弃，不生成 `bio_{uid}` 虚拟动态，也不在返回列表中追加，数据库版本保持静默不发生膨胀

### Requirement: B站 gRPC 模式个人简介 Card API 联动补爬与合流
系统在 B站 gRPC 模式下抓取动态列表后，必须且 SHALL 执行签名（Bio）的提取与补爬处理：
- **gRPC 签名提取**：系统必须且 SHALL 首先尝试从 gRPC 响应 `DynSpaceRsp` 列表的作者信息（`module_author.author.sign`）中提取签名。
- **免浏览器冷启动 Web Card API 联动补爬**：若上述 gRPC 提取出的签名为空，系统必须且 SHALL 在应用层动态通过标准的免签名公开名片接口 `https://api.bilibili.com/x/web-interface/card?mid={uid}` 并注入拟真 macOS Desktop `User-Agent` 标头进行 HTTP 补爬获取主页签名，且绝对禁止冷启动重型的 Playwright 浏览器，以保护 gRPC 通路的极致效率。
- **非空虚拟推文合成**：若补爬获取到的签名经过 `strip()` 去除首尾空白后非空，系统必须且 SHALL 将其封装为以 `bio_{uid}` 为 `post_id`、以当前抓取时间为发布时间的虚拟推文合流返回。如果仍为空，则不合成虚拟推文，物理拦截空白版。

#### Scenario: gRPC 模式下成功通过 Card API 补爬并合成签名
- **WHEN** 启动 B站 gRPC 模式抓取，常规 gRPC 数据不含签名，但通过轻量级 Web Card API 成功抓取到用户签名 "热爱cos的普通人" 时
- **THEN** 采集层 SHALL 成功合成 `post_id="bio_2075682"` 且内容为 `[个人简介] 热爱cos的普通人` 的虚拟推文合流返回

#### Scenario: 接口请求异常时优雅降级不阻断常规抓取
- **WHEN** B站 Web Card 接口请求由于超时或网络故障报错时
- **THEN** 采集层 SHALL 优雅捕获异常，输出 Warning 警告日志，默认签名为空不合成虚拟推文，并且常规的 gRPC 博文列表正常返回，整个抓取进程绝对不崩溃中断

### Requirement: Playwright 无头爬虫超时自愈与浏览器特征拟真
系统必须且 SHALL 对无头网页端抓取的底层会话生命周期进行加固防护，实现超时的精确自愈拦截与防爬风控特征伪装防御：
1. **超时精准捕获与自愈**：无头爬虫在加载网页和执行具体爬取动作时，必须且 SHALL 精准捕获 `playwright.async_api.TimeoutError` 以及内置 `TimeoutError` 异常。系统必须且 SHALL 对超时情况执行优雅静默降级处理，打印 `[Scraper Timeout ERROR]` 并记录为超时类型的日志且返回空结果列表，绝对不允许异常向上传播导致主定时进程崩溃。
2. **无头浏览器指纹特征防封控伪装**：系统在以无头模式创建浏览器上下文（Browser Context）时，必须且 SHALL 显示配置伪装的桌面浏览器 User-Agent 字符串（去除了 `HeadlessChrome` 敏感无头特异字样），同时必须且 SHALL 设置符合真实桌面设备的屏幕视口参数（`viewport`），降低被社交平台安全风控防火墙（WAF）拦截的风险。
3. **持久会话损坏自动熔断冷启动**：当读取本地会话缓存（`state.json`）遭遇文件为空或格式损坏抛出 JSON 解析异常时，系统必须且 SHALL 自动触发损坏文件清除，并优雅安全地降级回静态种子 Cookie 重新进行冷启动，保障爬虫持续的自愈力。

#### Scenario: 超时与损坏发生时成功触发静默自愈降级且不崩溃
- **WHEN** 页面在设置的 15s 内加载超时或 `state.json` 发生损坏时，启动网页爬取任务
- **THEN** 系统顺利自动清除损坏的 `state.json` 缓存，并在加载超时异常发生时，精准捕获 `playwright.async_api.TimeoutError`，静默输出超时警告日志并优雅返回空列表，主 CLI 抓取进程保持完全正常执行

