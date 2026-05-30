## MODIFIED Requirements

### Requirement: 原始博文表的数据库定义与外键关联及多平台编辑版本控制
系统必须在 SQLite 数据库中创建并维护原始博文表 `raw_posts`，用于缓存、去重与多版本回溯追踪。该表必须严格按照以下 SQL 规范建立，以确保与 Coser 实体的一对多物理外键关联，以及平台级的去重与编辑版本控制：
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


## ADDED Requirements

### Requirement: Click 命令行支持抓取细粒度参数过滤
系统终端入口的 `scrape` 命令行必须且 SHALL 支持接收可选的 `--name`（姓名昵称）参数，以及具有指定枚举的选择参数 `--platform`（包含 `weibo`、`bilibili`、`xhs`、`all` 选项，默认 `all`）。
系统必须对这些参数进行正确的类型解析，并安全透传给下游编排调度层。

#### Scenario: 无参数默认执行全量抓取
- **WHEN** 终端以默认形式 `uv run python src/main.py scrape` 启动，未指定任何过滤选项
- **THEN** 系统 SHALL 自动抓取数据库中所有已激活的 Coser 的所有平台（微博、B站、小红书）动态，保持原有全量批处理作业行

#### Scenario: 带过滤参数执行特定单点抓取
- **WHEN** 终端以包含参数的命令（例如 `uv run python src/main.py scrape --name "池咲misa" --platform bilibili`）启动
- **THEN** 系统 SHALL 仅对昵称为 "池咲misa" 且处于激活状态的 Coser 启动 B 站平台抓取任务，其他 Coser 和平台任务必须且 SHALL 优雅旁路跳过

### Requirement: 抓取调度层条件筛选与免冷启动熔断
工作流编排调度层 `WorkflowOrchestrator.run_scrape` 必须且 SHALL 接收 `coser_name` 与 `platform` 作为可选筛选参数。
- 姓名过滤：在捞取活跃名单后，若指定了姓名过滤，系统必须且 SHALL 在内存中进行精准裁剪。若名单匹配后为空，系统必须且 SHALL 打印黄色 `WARNING` 并优雅返回 `(0, {}, 0)`，绝不允许抛出任何异常。
- 平台过滤：在大循环派发任务前，系统必须且 SHALL 进行平台校验。对于未被指定的平台，系统必须且 SHALL 提前执行 `continue` 跳过，杜绝其 Scraper 实例的构建、Playwright 无头浏览器冷启动与超时等待。
- 数据兼容：即使仅抓取单人或单平台，调度层返回的返回值必须且 SHALL 严格对齐已存的三元组契约 `(total_cosers, success_platforms, total_inserted)` 以保证终端渲染及统计层在零修改的前提下完全适配。

#### Scenario: 匹配特定 Coser 平台成功执行抓取并返回三元组契约
- **WHEN** 调度器传入有效的 Coser 姓名及指定平台进行同步抓取且有数据入库
- **THEN** 系统顺利仅对该 Coser 对应平台执行同步、物理去重及事务入库，并成功返回三元组契约以渲染精美的总结报告
