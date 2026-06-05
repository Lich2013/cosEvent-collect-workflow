## 1. 配置与凭证环境准备

- [x] 1.1 在 `src/config.py` 中增加 `bilibili_grpc_ticket` 和 `bilibili_grpc_ticket_expires_at` 属性，并支持从 `config/settings.yaml` 或系统环境变量/`.env` 中加载与解析。
- [x] 1.2 在 `.env` 中初始化 `BILIBILI_TICKET` 和 `BILIBILI_TICKET_EXPIRES_AT`。

## 2. BiliTicket 生成与持久化缓存实现

- [x] 2.1 在 `src/tools/bilibili_scraper.py` 中实现 `_get_valid_bili_ticket(force_refresh=False)` 函数。使用 `hmac_sha256` 生成 `hexsign`，通过 HTTP POST 请求 `GenWebTicket` 接口申请 ticket。
- [x] 2.2 在 `src/tools/bilibili_scraper.py` 中实现 `_update_dotenv_ticket(ticket, expires_at)` 函数，动态且安全地将生成的 ticket 及其过期时间戳物理回写更新到本地 `.env` 文件。

## 3. Metadata 注入与自愈重试逻辑改造

- [x] 3.1 在 `_fetch_bilibili_posts_grpc_internal` 请求头构造中调用 `_get_valid_bili_ticket()`，并在 gRPC 元数据 `metadata` 列表中追加 `('x-bili-ticket', ticket)`。
- [x] 3.2 改造 `DynDetail` 循环请求的错误捕获：如果在请求单个动态详情时遭遇 `-352` 错误，清空缓存强制刷新 Ticket 后进行 1 次就地重试；重试依然失败则降级输出 `Scraper Warning` 并不阻断流程。
- [x] 3.3 改造外层 `fetch_bilibili_posts_grpc` 异常自愈分支：支持判定 `-352` 的 `RpcError`（或在 `_is_bili_grpc_auth_error` 中新增 `-352` 和风控错误的快速识别），触发强制刷新 Ticket + 整体重试抓取 1 次。
- [x] 3.4 确保当重试依然失败时，能够优雅降级熔断到 Playwright 网页抓取，确保主采集程序不崩溃。

## 4. 测试与验证

- [x] 4.1 在 `tests/test_bilibili_grpc.py` 中新增针对 `bili_ticket` 自动获取、失效强刷、以及 `-352` 错误触发自愈重试和降级流程的单元测试。
- [x] 4.2 运行现有的和新增的 B 站抓取测试（`pytest tests/test_bilibili_grpc.py`），确保测试全部通过且功能工作正常。
