## ADDED Requirements

### Requirement: 原始博文表的数据库定义与外键关联
系统必须在 SQLite 数据库中创建并维护原始博文表 `raw_posts`，用于缓存和去重。该表必须严格按照以下 SQL 规范建立，以确保与 Coser 实体的一对多物理外键关联，以及平台级的去重约束：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `coser_id` (INTEGER, NOT NULL, FOREIGN KEY REFERENCES `cosers`(`id`) ON DELETE CASCADE)
- `platform` (TEXT, NOT NULL)
- `post_id` (TEXT, NOT NULL)
- `content` (TEXT, NOT NULL)
- `post_url` (TEXT, NULL)
- `is_analyzed` (INTEGER, DEFAULT 0)
- `scraped_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)
- 唯一联合索引约束：`UNIQUE(platform, post_id)`

#### Scenario: 成功创建 raw_posts 表并建立物理外键关联
- **WHEN** 数据库初始化且存在 Coser 记录时，向 `raw_posts` 插入一条关联对应 Coser 且 `post_id` 唯一的博文记录
- **THEN** 数据库操作成功，外键约束和唯一联合索引约束生效

### Requirement: Playwright 静态 JSON 种子会话恢复、更新与 Git 屏蔽
系统必须实现通用的 `BaseScraper` 模块。当启动爬虫任务时，系统必须：
1. 优先检测本地是否存在 `runtime/{platform}/state.json` 文件；
2. 如果存在，启动 Headless 模式并使用 `storage_state` 还原完整的会话状态（Cookies + LocalStorage）；
3. 如果不存在或损坏，使用用户在 `config/cookies/{platform}_cookies.json` 中提供的静态 JSON 格式种子 Cookies 构建上下文，并自动生成并保存完整的 storage state 到 `state.json` 文件中；
4. 每次数据爬取完毕后，必须调用 Playwright 原生 `context.storage_state` 将最新 Cookie 及浏览器缓存更新回写到 `state.json` 文件；
5. 所有敏感凭证文件（`runtime/` 及 `config/cookies/*.json`，排除 `.example.json` 模板文件）必须强制写入项目的 `.gitignore` 中。

#### Scenario: 首次启动无本地持久化状态时使用静态 JSON 种子 Cookie 初始化
- **WHEN** 执行爬取命令且本地不存在 `runtime/weibo/state.json` 文件，但存在 `config/cookies/weibo_cookies.json` 种子时
- **THEN** 爬虫加载静态 JSON 文件成功创建页面并抓取，最终自动生成并保存完整的 `state.json` 状态文件

### Requirement: 微博、B站、小红书的多平台原生 API 响应拦截与可配置限制
系统必须使用 Playwright 原生网络请求拦截功能，在页面加载时监听并拦截特定的 Ajax 请求，极速获取无损的 JSON 数据并抽取博文正文。爬行条数必须支持通过 CLI `--limit N` (默认 10) 进行参数化配置：
- 微博：拦截包含 `weibo.com/ajax/statuses/mymblog` 的请求，抽取 `text_raw`；
- B站：拦截包含 `api.bilibili.com/x/polymer/web-dynamic/v1/feed` 的请求，抽取 `module_dynamic` -> `desc` -> `text`；
- 小红书：拦截包含 `api/sns/web/v1/user_posted` 的请求并解析对应笔记详情。

#### Scenario: 成功拦截B站动态列表 Ajax 响应并抓取配置限制数目的正文
- **WHEN** 执行命令 `cosevent scrape --limit 5` 爬取 Coser 的B站动态时
- **THEN** Playwright 成功拦截捕获 `feed` 响应，且入库保存的博文数目不超过 5 条

### Requirement: Click CLI scrape 控制流、NULL 平台跳过与错误恢复策略
Click 命令行工具必须提供 `cosevent scrape` 独立爬取命令。该命令的控制流逻辑必须为：
1. 从数据库中查询所有 `is_active = 1` 的 Coser；
2. 循环遍历每个 Coser 绑定的微博、B站、小红书 UID；
3. **NULL/空值跳过**：若某个 Coser 绑定的平台 UID 为 `NULL` 或为空字符串，系统必须优雅跳过当前平台的爬取而不抛出异常；
4. **加载超时与崩溃恢复**：单次页面加载必须设置 15s 严格超时。一旦超时或 Playwright 浏览器发生意外崩溃，系统必须捕获异常，打印错误日志，优雅重启浏览器上下文并**继续**执行下一个 Coser 的任务，绝对不能中断阻断 CLI 整体运行。

#### Scenario: 部分平台 UID 为空及页面加载超时不中断整体爬取
- **WHEN** Coser A 的微博 UID 为空，Coser B 发生 15s 页面加载超时，用户执行 `cosevent scrape` 命令时
- **THEN** 爬虫优雅跳过 Coser A 微博，捕获 Coser B 的超时错误并记录日志，顺利执行完其他 Coser 的爬行任务并正常退出，退出码为 0
