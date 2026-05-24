## 1. 爬虫模块功能升级

- [x] 1.1 修改 `src/tools/weibo_scraper.py` 中的 `fetch_weibo_posts` 解析逻辑，支持识别 `retweeted_status` 字段并安全读取原博文作者与正文
- [x] 1.2 在 `WeiboScraper` 中按照约定的对话拼接格式完成内容合并，存入 `content` 键中，处理可能的 Null 或 KeyError 异常
- [x] 1.3 修改 `src/tools/bilibili_scraper.py` 中的 `fetch_bilibili_posts` 解析逻辑，支持识别 `orig` 字段并安全读取原作者与原动态文本
- [x] 1.4 在 `BilibiliScraper` 中按照约定的对话拼接格式完成内容合并，存入 `content` 键中，防范字段缺失异常

## 2. 单元测试与回归验证

- [x] 2.1 在 `tests/test_cosevent.py` 中编写 `test_repost_and_retweet_parsing` 单元测试，分别构造 Mock 微博/B站转发的 JSON 数据包，并验证 scrapers 解析合并逻辑的准确性
- [x] 2.2 运行本地 `uv run pytest` 回归测试套件，确认新增测试通过且原有测试 100% PASS
