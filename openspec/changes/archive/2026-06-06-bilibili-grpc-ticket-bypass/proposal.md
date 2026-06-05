## Why

在通过 B 站第一方移动端 gRPC 接口拉取动态列表时，系统虽然实现了针对凭证失效（错误码 `-101`）的 `refresh_token` 自动置换与自愈机制，但频繁查询单个动态详情（`DynDetail` 接口获取高精度编辑时间）容易触发 B 站的 WAF/安全风控，导致服务器拒绝请求并返回错误码 `-352`（请求被拦截/风控阻断）。

由于 `-352` 与 Token 过期（`-101`）性质不同，现有的 Token 刷新无法对其自愈；且 `DynDetail` 的异常被局部捕获并降级为日志警告，未能有效触发任何重试或降级，导致动态的发布与编辑时间提取精度受损。此时，必须引入动态获取并携带 `x-bili-ticket` 安全票据的机制以绕过 `-352` 安全拦截。

## What Changes

- **新增 Ticket 自动生成机制**：在 scraper 启动或遇到风控阻断时，系统能自动生成用于安全校验的 `bili_ticket`（使用 B 站官方接口，并提供 hmac_sha256 签名密钥 `XgwSnGZ1p` 保护）。
- **新增 Ticket 本地物理缓存与校验**：在 `.env` 中维护 `BILIBILI_TICKET` 与 `BILIBILI_TICKET_EXPIRES_AT`，避免每次程序运行都重新请求票据。
- **元数据 (Metadata) 头注入**：在 `DynSpace` 与 `DynDetail` 的 gRPC 请求中注入 `('x-bili-ticket', ticket)` 元数据头。
- **强化 `-352` 自愈与重试逻辑**：
  - 在 `DynDetail` 或 `DynSpace` 中，若捕获到 `-352` 异常，系统主动清除缓存的 Ticket 并重新申请一次进行就地重试（最大重试 1 次）。
  - 若重试依然失败，则对单个接口进行优雅降级或静默回退，保证爬虫整体流程不受阻断。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `bilibili-grpc-scraper`: 升级 B 站 gRPC 爬取能力，支持 `bili_ticket` 的生成、缓存、注入，以及针对 `-352` 风控错误的自愈式重试，降低被 B 站 WAF 阻断的概率，提升高精度编辑时间采集的成功率。

## Impact

- **代码层面**：
  - `src/config.py`：新增 `bilibili_grpc_ticket` 和 `bilibili_grpc_ticket_expires_at` 配置项。
  - `src/tools/bilibili_scraper.py`：实现 `_get_valid_bili_ticket()` 票据获取和 `.env` 物理更新逻辑，并在 gRPC 通信和异常捕获分支中引入 ticket 注入与重试流程。
- **环境文件**：
  - `.env` 增加 `BILIBILI_TICKET` 和 `BILIBILI_TICKET_EXPIRES_AT` 字段。
