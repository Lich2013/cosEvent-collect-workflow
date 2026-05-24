## 1. 爬虫与数据库底层安全加固

- [x] 1.1 修改 `src/tools/weibo_scraper.py` 中的微博转发解析逻辑，对原作者 `screen_name` 进行 Falsy 真值兜底，杜绝注销用户导致的 `@None` 干扰缺陷
- [x] 1.2 修改 `src/tools/bilibili_scraper.py` 中的 B 站动态解析逻辑，提取 `pub_ts` 并将其标准化转化为 `published_at` 进行时序化回写，`edit_count` 默认为 0
- [x] 1.3 全面重构 `src/services/db_service.py` 中的所有底层数据库函数，使用 `with conn.cursor() as cursor:` 上下文释放游标，在时间分流事务中显式绑定北京时区限制
- [x] 1.4 修改 `src/tools/bilibili_scraper.py`，识别并过滤纯视频、纯图片等无任何文本附言的投稿动态，杜绝无依据的空博文入库

## 2. 裁判智能体 Token 降维精简优化

- [x] 2.1 修改 `src/agents/event_agent.py` 中的 `consensus` 共识流程，在终审裁判智能体输入 Prompts 前，对 `valid_outputs` 列表进行字段过滤降维，仅提取核心对比属性

## 3. 单元测试与回归验证

- [x] 3.1 在 `tests/test_cosevent.py` 中编写 `test_harden_and_timezone_align` 单元测试，Mock 转发原作者 None 值、服务器 UTC 时区偏移等情况，验证加固逻辑的准确性
- [x] 3.2 运行本地 `uv run pytest` 回归，确保全部 15 个测试场景（含新增的 2 个加固测试）完美成功通过
- [x] 3.3 在 `tests/test_cosevent.py` 中增加对 B站空文本动态过滤的 Mock 测试，验证跳过逻辑的安全正确性
