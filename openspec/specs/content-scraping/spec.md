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
