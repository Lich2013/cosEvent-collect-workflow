## 1. 采集端个人简介抓取与虚拟推文合成开发

- [x] 1.1 修改 `src/tools/weibo_scraper.py`：在 Playwright 抓取主页动态时，从拦截数据（`mymblog`）的 `user.description` 属性中提取微博个人简介（Bio），并在返回动态列表的最末尾合成追加一条以 `bio_{uid}` 为 `post_id` 的虚拟动态。
- [x] 1.2 修改 `src/tools/bilibili_scraper.py`：
  - [x] 在 gRPC 抓取模式的 `DynSpaceRsp` 响应体中直接读取用户 `sign`（签名/Bio）；
  - [x] 在 Playwright 网页模式的主页渲染中使用 DOM 选择器 `page.locator(".h-sign")` 定位并抓取签名；
  - [x] 在返回动态列表的最末尾合成追加一条以 `bio_{uid}` 为 `post_id` 的虚拟动态。
- [x] 1.3 修改 `src/tools/xhs_scraper.py`：在 Playwright 主页渲染中，通过 DOM 选择器 `page.locator(".user-desc")` 定位并提取小红书个人介绍（Bio），并在返回动态列表的最末尾合成追加一条以 `bio_{uid}` 为 `post_id` 的虚拟动态。

## 2. 单元与集成测试验证

- [x] 2.1 新建 `tests/test_coser_bio_scraping.py` 单元测试：编写测试模拟微博、B站、小红书的动态抓取，验证个人主页简介能成功合成为以 `bio_{uid}` 为 `post_id`、以抓取当前北京时间为 `published_at` 的虚拟推文，并随推文列表安全合流返回。
- [x] 2.2 编写集成测试：模拟 Bio 变动的场景，验证数据库存储层（`DBService.save_raw_posts`）能针对 `bio_{uid}` 虚拟推文成功触发内容比对去重、`#v1` 和 `#v2` 版本自适应物理递增，并原子的标记 `is_analyzed = 0`。
- [x] 2.3 运行全量测试套件执行回归核验，确保 100% 绿色通过。
