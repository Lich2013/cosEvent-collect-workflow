## MODIFIED Requirements

### Requirement: 微博、B站、小红书的多平台原生 API 响应拦截与可配置限制
系统**必须且 SHALL** 使用 Playwright 原生网络请求拦截功能，在页面加载时监听并拦截特定的 Ajax 请求，极速获取无损的 JSON 数据并抽取博文正文。系统**必须且 SHALL** 支持解析和合并转发（Weibo retweeted_status 和 Bilibili orig）的文本内容。爬行条数必须且 SHALL 支持通过 CLI `--limit N` (默认 10) 进行参数化配置：
- 微博：拦截包含 `weibo.com/ajax/statuses/mymblog` 的请求，抽取并合并 `text_raw`：若包含 `retweeted_status` 字段，则获取原博作者昵称和原博文本，按照统一的对话样式格式（`转发了 @{原作者} 的博文：“{原博文}”\n说：“{Coser附言}”`）进行拼接合并后存入 `content` 字段。系统**必须且 SHALL** 对原作者昵称进行严格的 Falsy 兜底校验，若原作者昵称为 `None` 或空字符串时，必须将其规整兜底为 `"原作者"` 以防止破坏下游提取结构。系统**必须且 SHALL** 优先获取微博的 `mblogid` 短码生成 `post_url`，降级使用 `idstr` 或 `id`，绝对防御 `None` 字段链接的发生。系统**必须且 SHALL** 解析微博原始发布日期格式并对齐到东八区北京时间与 `YYYY-MM-DD HH:MM:SS` 格式后存入 `published_at`。同时系统**必须且 SHALL** 抓取博文的 `edit_count`，如果抓取到的 `edit_count` 大于数据库中已存的数值，则执行内容更新，并将 `is_analyzed` 重置为 `0` 以激活下游增量重跑。
- B站：拦截包含 `api.bilibili.com/x/polymer/web-dynamic/v1/feed` 的请求，抽取并合并 `module_dynamic` -> `desc` -> `text`：若包含 `orig` 字段，则获取原动态作者昵称 and 原动态文本，按照统一的对话样式格式进行拼接合并后存入 `content` 字段。系统**必须且 SHALL** 抓取动态原生发布时间戳 `pub_ts` 并将其格式化写入 `raw_posts.published_at` 以对齐时序。系统**必须且 SHALL** 过滤无文本附言（如纯视频、纯图片投稿等最终合并 `content` 字段为空字符或纯空白字符）的动态记录，防范空文本博文入库占位。
- 小红书：拦截包含 `api/sns/web/v1/user_posted` 的请求并解析对应笔记详情。
- 时区一致性约束：系统在进行博文发表时间审计和时间轴分流判断时，**必须且 SHALL** 全局统一采用东八区北京时间（`Asia/Shanghai` 时区）获取参考系统日期（`YYYY-MM-DD`），彻底消除运行服务器物理环境对业务时序判定的干扰。

#### Scenario: 成功将 None 原作者作者兜底解析为“原作者”
- **WHEN** 抓取到一条被转发作者注销的微博，其 `user.screen_name` 显式为 `None` 时
- **THEN** 合并后的 content 中的原作者名字被正确替换填充为 "原作者"，且最终分析没有破坏

#### Scenario: B站动态提取 pub_ts 成功时序化写入
- **WHEN** 拦截到带有秒级时间戳 of B 站动态数据响应时
- **THEN** 提取该时间戳并转化为 `YYYY-MM-DD HH:MM:SS` 格式成功存入数据库的 `published_at` 字段中

#### Scenario: 成功跳过空文本的B站纯视频投稿动态
- **WHEN** 拦截到一条 B 站动态，该条动态是投稿视频且没有任何文字附言，解析得到的文字内容为空时
- **THEN** 系统安全跳过此动态，抓取返回列表中不包含此动态，数据库中也未被插入空内容记录

#### Scenario: 微博成功采用 mblogid 拼接详情页链接且转换日期时区对齐
- **WHEN** 微博爬虫抓取到新博文，带有 mblogid `"Ql7djrATz"` 且 `created_at` 为 `"Thu Jan 01 17:12:59 +0800 2026"` 时
- **THEN** 生成的 post_url 值为 "https://weibo.com/1923024604/Ql7djrATz"，且 published_at 被格式化对齐为 "2026-01-01 17:12:59"
