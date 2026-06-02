## Context

在 B站 gRPC 抓取（`fetch_bilibili_posts_grpc`）中，我们虽然能够在 DynSpace 响应中读取 `UserInfo` 结构，但由于 B站服务端优化，该列表响应中的 `author.sign` 签名（Bio）字段实际上是未填充的空字符串。且由于 gRPC 运行无误，系统不会降级进入 Playwright 网页抓取，这导致 gRPC 模式下的个人主页简介抓取完全失效。

为了在不冷启动沉重浏览器的前提下，闭环 gRPC 通路下的签名数据，本设计决定引入轻量级的 B站公开 Web 名片接口（`x/web-interface/card`）作为就地联动补爬通路。

---

## Goals / Non-Goals

**Goals:**
- 在 B站 gRPC 抓取模式中，当发现响应签名为空时，通过轻量级名片接口自动补充抓取 Coser 主页的 Bio/签名。
- 使用极低成本的原生 Python 网络请求，彻底免除 Playwright 无头浏览器冷启动开销。
- 引入严密的 `try-except` 异常包裹，确保接口超时或受限时优雅降级，绝对不崩溃阻断主进程抓取。
- 完成对 `bio_{uid}` 虚拟推文的非空过滤和格式化合流注入。

**Non-Goals:**
- 不修改既有的 SQLite 数据库物理表结构。
- 不冷启动无头浏览器，不引入任何多余的三方 HTTP 请求库依赖。

---

## Decisions

### 1. 采用 B站公开 Web 名片接口作为签名抓取通路
- **决策**：通过发起 HTTP GET 请求到 `https://api.bilibili.com/x/web-interface/card?mid={uid}`，直接解析返回 JSON 中的 `data.card.sign`。
- **考量**：
  - **免签名**：该名片接口是 B站完全公开的接口，不需要进行复杂的客户端 WBI 签名计算，也不受 Cookie 强制绑定的制约。
  - **抗风控防爬**：请求时只需注入常规的桌面端拟真 `User-Agent`（如 `Mozilla/5.0`），即可 100% 获得 `code: 0` 的成功响应，极具鲁棒性。
  - **替代方案评估**：若采用专门的 gRPC 关系/名片 stub 调用，由于相关 protobuf 结构高度复杂且极易随客户端版本升级而失效失效，维护成本过高。采用公开 Web 名片接口是当前最稳健的选择。

### 2. 采用原生异步线程包裹的 `urllib.request` 发起调用
- **决策**：在 `fetch_bilibili_posts_grpc` 的异步调用链中，使用 `asyncio.to_thread` 或者是已有的异步并发机制，配合 Python 内置的 `urllib.request` 模块发起 HTTP 请求：
  ```python
  import urllib.request
  import json
  
  def _fetch_bio():
      req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
      with urllib.request.urlopen(req, timeout=5) as response:
          ...
  ```
- **考量**：
  - 避免引入外部重型请求库（如 `requests`、`aiohttp`），保持极简依赖。
  - 配合 5s 严格超时控制，防止因 B站接口响应缓慢而导致爬虫大循环被死锁挂起。

---

## Risks / Trade-offs

- **[Risk] B站名片接口在未来增加防爬风控或改版**
  - **Mitigation**：将补爬逻辑使用 `try-except Exception` 进行严密包裹。一旦网络请求失败、超时或返回数据结构异常，系统仅优雅打印 Warning 日志并继续执行后续，返回空简介虚拟推文，**绝对不会阻断**已成功抓取到的常规 gRPC 动态数据。
- **[Risk] 频繁请求名片接口引起 B站对 IP 的单点频控**
  - **Mitigation**：由于我们仅在每个 Coser 抓取循环的末尾（获取整个动态列表完毕后）执行一次名片接口调用，请求频次与主抓取任务完全一致，不会产生任何额外的频控过载风险。
