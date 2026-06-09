## MODIFIED Requirements

### Requirement: 传输层 RpcError 健壮性异常捕获与熔断降级
在进行 gRPC 交互（包含 `DynSpace` 与 `DynDetail` 接口调用）时，系统必须且 SHALL 用 `try-except grpc.RpcError` 结构对网络与通信进行强健壮性包裹。
- 若发生任何网络连接超时或鉴权失败（`-101`）等 RPC 报错，系统必须且 SHALL 自动触发 `refresh_token` 机制或立即降级回退。
- 若遭遇风控阻断（`-352`）且尚未进行过重试自愈，系统必须且 SHALL 自动清空本地 Ticket 缓存并在线请求生成最新的 `bili_ticket` 物理回写至 `.env`，然后对当前失败的请求执行就地重试。在在线请求生成 Ticket 时，系统必须且 SHALL 将所有必须的校验字段（包括 `key_id`, `hexsign`, `context[ts]`, `csrf`）作为 URL 查询参数 (Query String) 拼接到请求 URL 中发送，并保持 POST 请求体 (Body) 为空，以规避 `empty ts field (code: -400)` 错误。
- 若重试依然报 `-352` 错误或遭遇不可恢复的 RPC 报错，系统必须且 SHALL 捕获该异常，输出黄色 `WARNING` 并熔断降级，自动回退到 Playwright 无头浏览器抓取机制。

#### Scenario: 遭遇 -352 风控拦截并成功执行 Ticket 重试自愈
- **WHEN** 运行 gRPC 空间动态或单条详情请求遭遇 `-352` 的 `RpcError`
- **THEN** 系统自动刷新并持久化 `bili_ticket`，执行一次就地重试并成功返回数据，不触发 Playwright 网页抓取降级

#### Scenario: gRPC 报错自动且零崩溃降级为 Playwright
- **WHEN** 运行 gRPC 空间动态请求遭遇鉴权失效的 `RpcError` 或重试后依然报 `-352` 拦截
- **THEN** 系统打印警告日志，熔断当前 gRPC 连接，并调用 Playwright 网页抓取流顺利返回抓取结果

#### Scenario: 成功生成新 Ticket 凭证自愈
- **WHEN** 调用 Ticket 申请接口且将校验参数置于 URL 查询参数中发送时
- **THEN** 接口成功返回 code 为 0 且包含合法 ticket 字段的 JSON 结构，并成功将新票据持久化回写
