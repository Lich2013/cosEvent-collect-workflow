## 1. 修改 Ticket 刷新网络请求传参

- [x] 1.1 在 `src/tools/bilibili_scraper.py` 的 `_get_valid_bili_ticket()` 函数中，使用 `urllib.parse.urlencode(params)` 获得查询字符串，将其拼接至 `GenWebTicket` 接口的 URL 后面
- [x] 1.2 在实例化 `urllib.request.Request` 时，将拼接后的完整 URL 作为参数传入，且不传入 `data`（保持为 `None`），使得以空 Body 发送 POST 请求

## 2. 验证与回归测试

- [x] 2.1 编写或运行针对 B站 凭证获取逻辑的单元测试（如 `tests/test_bilibili_scraper.py`），确认本地逻辑在 Mock 与非 Mock 环境下均符合规范
- [x] 2.2 运行包含 gRPC 调用的测试（或临时触发爬虫刷新 ticket 逻辑），核对日志输出是否包含 `B站 ticket 申请成功！` 且 `data.ticket` 获取成功，验证 -400 参数缺失错误已彻底消除
- [x] 2.3 运行项目全量单元测试 `uv run pytest`，确保全量 107 个用例 100% 成功通过，不引入任何功能回归
