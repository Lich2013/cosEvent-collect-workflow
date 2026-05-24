## 1. 爬虫解析升级与时间对齐

- [x] 1.1 修改 `src/tools/weibo_scraper.py` 中的 `fetch_weibo_posts` 解析逻辑，将 `post_url` 拼装时所获取的 bid 参数替换为 `mblogid` 短码，并提供对 `idstr` 和 `id` 的健壮兜底
- [x] 1.2 修改 `src/tools/weibo_scraper.py` 中的微博发布日期解析，利用 `email.utils` 标准库安全还原 `"created_at"`，并强行将其对齐为东八区北京时间与 `YYYY-MM-DD HH:MM:SS` 格式后回写

## 2. 数据库审计字段北京时区全局对齐

- [x] 2.1 修改 `src/services/db_service.py` 中的 `add_coser` 方法，在插入 Coser 实体时显式注入北京时间的 `created_at` 字符串，取代 SQLite 的默认 UTC 占位
- [x] 2.2 修改 `src/services/db_service.py` 中的 `save_raw_posts` 方法，在插入或二次编辑更新 raw_posts 时，显式以当前系统北京时间填充 `scraped_at` 列
- [x] 2.3 修改 `src/services/db_service.py` 中的 `save_extracted_events_transactional` 方法，在向 `cosplay_events` 写入所提炼活动时，显式在 SQL 事务中以北京时间注入 `created_at` 列

## 3. 单元测试与回归验证

- [x] 3.1 更新 `tests/test_cosevent.py`，增加对微博详情页链接 `post_url` 非空非 `None` 且正常拼装 mblogid 的断言校验，以及微博发布日期格式统一对齐的验证
- [x] 3.2 增加单元测试对数据库审计字段（`scraped_at` 和 `created_at` 等）全部统一为北京时间且格式为 YYYY-MM-DD HH:MM:SS 的断言断定校验
- [x] 3.3 运行本地回归测试，确保 15 个用例（包括新增用例）全部完美 PASS 通过
