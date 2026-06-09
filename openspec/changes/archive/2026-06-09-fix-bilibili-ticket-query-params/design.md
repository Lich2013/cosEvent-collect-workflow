## Context

当 B站 空间动态 gRPC 抓取因 `-352` 风控机制被拦截时，爬虫会自动尝试刷新安全凭证 Ticket。
刷新凭证需要通过 HTTPS POST 方法请求 B站 接口：
`https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket`

当前代码的实现是将参数 `key_id`, `hexsign`, `context[ts]`, `csrf` 放入了 POST 请求体 (Body) 中发送。因为 B站 接口底层校验机制的限制，在 body 中发送无法正确提取 `context[ts]` 等鉴权时间戳参数，导致接口拒绝并抛出 `empty ts field (code: -400)` 异常。

## Goals / Non-Goals

**Goals:**
- 将 `_get_valid_bili_ticket` 中对 `GenWebTicket` 接口的调用参数位置，由 POST Body 调整为 URL Query String。
- 保证凭证能够顺利申请成功并持久化回写至 `.env` 配置文件。
- 当 ticket 更新成功后，确保 gRPC 调用可以顺利附带 `x-bili-ticket` 并完成抓取。

**Non-Goals:**
- 不对 gRPC 数据传输层报文与元数据协议做任何改动。
- 不引入 `requests` 等外部第三方 HTTP 依赖，继续使用内置的 `urllib.request`。

## Decisions

### 1. 将 POST 参数全部迁移至 URL 查询参数中
即使 HTTP 请求方法是 `POST`，B站的此 API 仍然从 URL 路径后方的查询参数里读取校验字段。

**实现细节**：
- 使用 `urllib.parse.urlencode` 对参数字典 `params` 进行转义编码。
- 拼装到 URL 尾部：`full_url = f"{url}?{query_string}"`。
- 实例化 `urllib.request.Request(full_url, method="POST")`，不要传递任何 `data`（保留 `data=None`），使其以空 POST Body 状态发出。

## Risks / Trade-offs

- **[Risk]** 在 URL 中传递敏感签名等参数可能受到一般性的 URL 暴露风险。
  - **Mitigation**：此请求是向 B站 第一方安全接口传输，全程基于 HTTPS 加密协议，不存在明文拦截的风险，且此 API 设计规范即为此结构，该设计安全可行。
