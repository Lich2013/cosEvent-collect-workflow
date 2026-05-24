## Context

当前项目中，微博爬虫抓取得到的博文详情页链接 `post_url` 由于错误的 `bid` 字段（微博响应包中不存在此字段）而包含了大量 `None` 值空值，被污染为了 `https://weibo.com/{uid}/None`。此外，微博的发布日期 `published_at` 仍采用原始非标准格式（HTTP-date 风格），与 B站动态时间及数据库审计时间 `scraped_at` / `created_at` 等严重不对齐。最后，SQLite 数据库在写入这些审计时间时默认采用 UTC 时间，引起了 8 小时的时区偏置，导致“抓取时间”反而比“发布时间”慢 8 小时，产生时空上的错乱。

## Goals / Non-Goals

**Goals:**
- **微博 URL 防御修复**：优先使用 `mblogid` 短码生成微博链接，降级使用 `idstr` 和 `id`，彻底修复微博详情页链接。
- **微博发布日期格式统一**：将微博原始的 HTTP-date 格式转换为统一的东八区北京时间 `"YYYY-MM-DD HH:MM:SS"`，实现数据库内的一致性。
- **数据库审计列全局北京时区对齐**：废弃 SQLite 的 UTC 时间 `DEFAULT CURRENT_TIMESTAMP` 占位，所有审计时间（如 `cosers.created_at`, `raw_posts.scraped_at`, `cosplay_events.created_at`）统一在 Python 层写入时生成东八区北京时间写入，实现全库时间一致性。

**Non-Goals:**
- 不会对除 `cosers`, `raw_posts`, `cosplay_events` 之外的数据库 Schema 结构进行改变，保持数据库底层兼容。

## Decisions

### 决策 1：微博 URL 降级式自适应提取算法
- **技术选型**：利用 Python 字典对象的 `get` 降级读取与 `or` 运算符拼接。
- **实现**：
  `post_id_url = item.get("mblogid") or item.get("idstr") or item.get("id")`
  `post_url = f"https://weibo.com/{uid}/{post_id_url}"`
- **考量**：`mblogid` 是最标准的短链接 ID；`idstr` 和 `id` 是长数字 ID 兜底，从而彻底避免空值造成的 None 链接。

### 决策 2：使用 email.utils 健壮解析微博 HTTP-Date
- **技术选型**：利用 Python 内置标准库中的 `email.utils.parsedate_to_datetime` 进行 RFC 2822 时间解析。
- **实现**：由于微博的 `"created_at"` 时间包含了特定的时区名和时区偏移（例如 `Thu Jan 01 17:12:59 +0800 2026`），使用内置标准库 `email.utils` 可以天然安全且免受第三方时区包依赖干扰地处理时区，随后通过 `.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")` 输出。

### 决策 3：全库写入时显式注入北京时间
- **技术选型**：在 `db_service.py` 写入数据库时，对于原先依赖 SQLite `CURRENT_TIMESTAMP` 的审计字段，直接在 SQL 参数中显式传入 `now_str`（格式为 `YYYY-MM-DD HH:MM:SS` 锁死至北京时间）。
- **实现**：
  ```python
  beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
  now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
  # 在 INSERT 和 UPDATE 语句中作为参数传给 scraped_at 和 created_at 字段
  ```

## Risks / Trade-offs

- **[Risk] 微博时间解析异常造成 published_at 字段为 None**
  - **Mitigation**：在 `email.utils` 解析时包裹完善的 `try...except` 异常屏障，如果解析发生阻碍，自适应降级为当前抓取时的系统北京时间（`now_str`），确保不会因为时间转换崩溃。
- **[Risk] 存量旧数据的兼容与时区差**
  - **Mitigation**：由于我们对数据库中的表采用向上对齐的原则，老数据的 UTC 格式在新增北京时间时不受冲突干扰，系统未来的排序查询可完全无损兼容。
