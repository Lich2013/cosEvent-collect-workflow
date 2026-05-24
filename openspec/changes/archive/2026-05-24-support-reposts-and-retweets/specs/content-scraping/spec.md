## MODIFIED Requirements

### Requirement: 微博、B站、小红书的多平台原生 API 响应拦截与可配置限制
系统必须使用 Playwright 原生网络请求拦截功能，在页面加载时监听并拦截特定的 Ajax 请求，极速获取无损的 JSON 数据并抽取博文正文。系统**必须且 SHALL** 支持解析和合并转发（Weibo retweeted_status 和 Bilibili orig）的文本内容。爬行条数必须支持通过 CLI `--limit N` (默认 10) 进行参数化配置：
- 微博：拦截包含 `weibo.com/ajax/statuses/mymblog` 的请求，抽取并合并 `text_raw`：若包含 `retweeted_status` 字段，则获取原博作者昵称和原博文本，按照统一的对话样式格式（`转发了 @{原作者} 的博文：“{原博文}”\n说：“{Coser附言}”`）进行拼接合并后存入 `content` 字段。
- B站：拦截包含 `api.bilibili.com/x/polymer/web-dynamic/v1/feed` 的请求，抽取并合并 `module_dynamic` -> `desc` -> `text`：若包含 `orig` 字段，则获取原动态作者昵称和原动态文本，按照统一的对话样式格式（`转发了 @{原作者} 的动态：“{原动态}”\n说：“{Coser附言}”`）进行拼接合并后存入 `content` 字段。
- 小红书：拦截包含 `api/sns/web/v1/user_posted` 的请求并解析对应笔记详情。

#### Scenario: 成功拦截B站动态列表 Ajax 响应并抓取配置限制数目的正文
- **WHEN** 执行命令 `cosevent scrape --limit 5` 爬取 Coser 的B站动态时
- **THEN** Playwright 成功拦截捕获 `feed` 响应，且入库保存的博文数目不超过 5 条

#### Scenario: 成功拦截并解析微博转发博文
- **WHEN** 执行爬虫抓取到包含 `retweeted_status` 的微博响应时
- **THEN** 系统解析原博作者与正文，并合并存储为“转发了 @{原作者} 的博文：...”格式

#### Scenario: 成功拦截并解析B站转发动态
- **WHEN** 执行爬虫抓取到包含 `orig` 结构的 B 站动态响应时
- **THEN** 系统解析原作者与原动态正文，并合并存储为“转发了 @{原作者} 的动态：...”格式
