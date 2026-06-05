## Context

目前，系统使用 B 站第一方移动端 gRPC 接口抓取空间动态。为了防范风控，gRPC 请求中注入了部分模拟的设备元数据（Device/Network/Restriction/Locale 等）。然而，在频繁抓取或调用 `DynDetail` 接口时，B 站的安全机制依然会触发并返回错误码 `-352`（请求被拦截/风控阻断），导致无法精准提取动态的编辑时间。为了规避此风控，需要在 gRPC 请求中携带通过安全签名生成的 `x-bili-ticket` JWT 凭证，并针对 `-352` 实现自愈重试逻辑。

## Goals / Non-Goals

**Goals:**
- 实现 B 站 `bili_ticket` 票据的生成，并将其持久化缓存到本地 `.env` 文件。
- 实现 Ticket 的有效期（3天）校验，在过期前（如设定10分钟安全余量）或失效时自动置换。
- 在 gRPC `DynSpace`（空间动态列表）和 `DynDetail`（单条动态详情）请求中透明注入 `x-bili-ticket` 元数据。
- 改造错误处理机制，使 `DynSpace` 和 `DynDetail` 能智能识别并截获 `-352` 错误，执行“强制刷新 Ticket + 单次重试”自愈流程。

**Non-Goals:**
- 不修改除 B 站 gRPC 爬虫之外的其他平台（微博、小红书）的数据采集逻辑。
- 不修改底层数据库表结构或大模型 Agent 核心流程。

## Decisions

### 1. Ticket 生成方式选型：HTTP API 优先
- **方案**：使用 B 站 Web 端的官方票据接口 `https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket`。
- **原因**：虽然 gRPC 也有 `GetTicket` 方法，但 HTTP `GenWebTicket` 接口的签名规则（使用 `XgwSnGZ1p` 密钥的 HmacSHA256 算法与秒级时间戳）非常明晰，易于在 Python 中通过内置库快速实现，无需依赖额外的 C++ 动态库或过于复杂的设备指纹算法。

### 2. 持久化缓存介质：物理写入 `.env`
- **方案**：在系统根目录下的 `.env` 中缓存 `BILIBILI_TICKET` 和 `BILIBILI_TICKET_EXPIRES_AT`。
- **原因**：项目目前没有引入 Redis 或其他持久化 K-V 缓存。考虑到 Token 的刷新也是直接物理回写 `.env` 文件（通过 `_update_dotenv`），将 Ticket 也缓存于此能够保持技术栈的统一，并且保证跨 CLI 进程运行时不需要重复申请 Ticket。

### 3. `-352` 自愈重试深度：分层异常捕获与重试
- **方案**：
  - **接口层重试**：如果 `DynSpace` 遇到 `-352` 错误，外层捕获后触发 `_get_valid_bili_ticket(force_refresh=True)` 并重新请求一次（最大重试1次）。
  - **局部循环内重试**：对于 `DynDetail`（在循环中获取多条动态详情），如果单次调用抛出 `-352` 异常，先就地尝试刷新 Ticket 并重试当前动态的 `DynDetail` 调用。只有在重试后依然失败时，才打印 Warning 警告并跳过，避免个别动态的风控阻断整个列表的数据补全。

## Risks / Trade-offs

- **[Risk] Ticket 频繁失效/封禁**  
  *Mitigation*: 在每次触发 `-352` 时，最多只执行一次 Ticket 强行刷新和重试。如果重试依旧失败，说明当前设备指纹或 IP 被硬风控，系统将优雅降级到 Playwright 网页端无头浏览器抓取，防止陷入死循环。
- **[Risk] 多进程并发修改 `.env` 冲突**  
  *Mitigation*: 本系统作为单机定时 CLI 任务运行，并发概率极低。但在写入 `.env` 时，仍采用临时文件替换或文件锁方式（可复用原有的 `_update_dotenv` 字符串正则替换逻辑）以提高文件写入稳定性。
