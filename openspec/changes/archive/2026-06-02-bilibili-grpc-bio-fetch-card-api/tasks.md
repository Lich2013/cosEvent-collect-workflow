## 1. B站 gRPC 模式 Card API 联动补爬代码实现

- [x] 1.1 修改 `src/tools/bilibili_scraper.py` 中的 `fetch_bilibili_posts_grpc`：当常规 gRPC 动态数据中提取 of `bio` 签名为空时，动态发起 HTTP GET 请求至 `https://api.bilibili.com/x/web-interface/card?mid={uid}`。
- [x] 1.2 在请求中显式设置 macOS Desktop `User-Agent` 拟真指纹以防 WAF 拦截，并配置 5s 严格加载超时限制。
- [x] 1.3 对补爬请求添加严密的 `try-except` 异常拦截保护，发生超时或报错时打印 Scraper Warning 并优雅降级返回，绝不阻断常规 gRPC 动态列表返回。
- [x] 1.4 解析响应 JSON 中的 `data.card.sign` 并执行非空校验，若有效则在列表最末尾合成为以 `bio_{uid}` 为 `post_id`、以当前北京抓取时刻为发布时间的虚拟动态。

## 2. 测试验证与回归校验

- [x] 2.1 修改/增补 `tests/test_coser_bio_scraping.py` 中的单元测试：模拟常规 gRPC 响应无签名但 Web Card 接口成功返回签名的场景，验证虚拟推文合成与合流正确性。同时测试网络异常报错下的优雅降级自愈能力。
- [x] 2.2 运行全量测试套件 `pytest tests/` 进行回归验证，确保所有 78 项测试 100% 绿色通过。
