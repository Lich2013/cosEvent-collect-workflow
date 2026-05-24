## MODIFIED Requirements

### Requirement: 原始博文表的数据库定义与外键关联
系统必须在 SQLite 数据库中创建并维护原始博文表 `raw_posts`，用于缓存和去重。该表必须严格按照以下 SQL 规范建立，以确保与 Coser 实体的一对多物理外键关联，以及平台级的去重与编辑版本控制：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `coser_id` (INTEGER, NOT NULL, FOREIGN KEY REFERENCES `cosers`(`id`) ON DELETE CASCADE)
- `platform` (TEXT, NOT NULL)
- `post_id` (TEXT, NOT NULL)
- `content` (TEXT, NOT NULL)
- `post_url` (TEXT, NULL)
- `is_analyzed` (INTEGER, DEFAULT 0)
- `edit_count` (INTEGER, DEFAULT 0) -- 微博编辑次数跟踪列
- `published_at` (TEXT, NULL) -- 微博原始发表时间列
- `scraped_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)
- 唯一联合索引约束：`UNIQUE(platform, post_id)`

#### Scenario: 成功创建或升级 raw_posts 表并支持编辑控制列
- **WHEN** 数据库初始化或执行数据库升级，存在 Coser 记录时
- **THEN** `raw_posts` 中成功具备 `edit_count` 和 `published_at` 字段，且联合索引及外键生效

### Requirement: 微博、B站、小红书的多平台原生 API 响应拦截与可配置限制
系统必须使用 Playwright 原生网络请求拦截功能，在页面加载时监听并拦截特定的 Ajax 请求，极速获取无损的 JSON 数据并抽取博文正文。系统**必须且 SHALL** 支持解析和合并转发（Weibo retweeted_status 和 Bilibili orig）的文本内容。爬行条数必须支持通过 CLI `--limit N` (默认 10) 进行参数化配置：
- 微博：拦截包含 `weibo.com/ajax/statuses/mymblog` 的请求，抽取并合并 `text_raw`：若包含 `retweeted_status` 字段，则获取原博作者昵称和原博文本，按照统一的对话样式格式进行拼接合并后存入 `content` 字段。同时系统**必须且 SHALL** 抓取博文的 `edit_count` 和原始发表时间 `created_at`，如果抓取到的 `edit_count` 大于数据库中已存的数值，则执行内容更新，并将 `is_analyzed` 重置为 `0` 以激活下游增量重跑。
- B站：拦截包含 `api.bilibili.com/x/polymer/web-dynamic/v1/feed` 的请求，抽取并合并 `module_dynamic` -> `desc` -> `text`：若包含 `orig` 字段，则获取原动态作者昵称和原动态文本，按照统一的对话样式格式进行拼接合并后存入 `content` 字段。
- 小红书：拦截包含 `api/sns/web/v1/user_posted` 的请求并解析对应笔记详情。

#### Scenario: 微博编辑版本升级并重置分析状态
- **WHEN** 微博爬虫拦截到某条微博最新 `edit_count` 大于数据库已有数值时
- **THEN** 系统更新该博文的 `content` 和 `edit_count` 字段值，并将 `is_analyzed` 重置为 0
