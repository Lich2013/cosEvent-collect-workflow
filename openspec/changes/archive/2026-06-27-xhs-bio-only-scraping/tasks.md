## 1. 采集端小红书爬虫逻辑修改

- [x] 1.1 修改 `src/tools/xhs_scraper.py` 中的网络响应拦截逻辑，将期待响应接口由笔记列表 `api/sns/web/v1/user_posted` 改为个人信息接口 `api/sns/web/v1/user/otherinfo`。
- [x] 1.2 移除 `xhs_scraper.py` 中解析常规笔记的 notes 循环，确保不爬取、不解析小红书的笔记数据。
- [x] 1.3 确保在获取 Bio 文本后（不管是通过 API 拦截还是 DOM 选择器 `.user-desc` 兜底），仅组装一条以 `bio_{uid}` 为 `post_id` 的虚拟动态，并放入 posts 数组中返回。

## 2. 单元测试与集成测试验证

- [x] 2.1 修改 `tests/test_coser_bio_scraping.py` 中的 `test_xhs_bio_scraping_dom_fallback` 单元测试，将拦截的 mock URL 改为 `user/otherinfo`，并验证其能只返回 1 条合成的 Bio 虚拟推文。
- [x] 2.2 在 `tests/test_coser_bio_scraping.py` 中补充测试用例 `test_xhs_bio_scraping_api_success`，验证当 `otherinfo` 拦截成功并提取到 Bio 时能正常合成虚拟推文。
- [x] 2.3 运行 `pytest tests/test_coser_bio_scraping.py` 验证 Bio 爬取逻辑 of 单元测试通过。
- [x] 2.4 运行 `pytest tests/test_fine_grained_scrape.py` 验证细粒度过滤及 Mock Scraper of 测试不受本重构影响，全量通过。
