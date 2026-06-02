## Why

现有的 B站 gRPC 抓取模式在获取 Coser 动态时，由于 B站移动端第一方 `DynSpace` 接口响应体中没有对 `UserInfo.sign` 签名（Bio）字段进行数据下发，导致 gRPC 抓取下的签名记录始终为空。又因为 gRPC 运行无错，程序无法触发网页 Playwright 降级分支，造成配有 gRPC 凭证的用户在抓取 B站日程时 100% 丢失主页个人介绍。本变更旨在通过极轻量、免签名的公开名片接口进行联动，彻底闭环 gRPC 通路下的 B站 Bio 抓取完整性。

## What Changes

- **B站 gRPC 模式 Bio 联动抓取**：在 B站 gRPC 动态列表解析阶段，若常规 gRPC 响应中的 signature 为空，系统自动通过标准的免 WBI 加密名片接口进行补爬，并将抓取到的签名重锚合成虚拟推文一并合流交付。
- **免无头浏览器冷启动**：联动补爬采用原生 Python `urllib` 请求，伪装桌面端 `User-Agent` 指纹，完美避开无头 Playwright 浏览器的冷启动，保持 gRPC 通路极高的数据抓取效率。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 增加 B站 gRPC 抓取模式下，自动调用轻量级公开 Card API 获取主页简介，并完美合成为 `bio_{uid}` 虚拟推文合流返回的规范约束。

## Impact

- **Bilibili Scraper** (`src/tools/bilibili_scraper.py`): 核心修改文件，在 gRPC 获取常规动态列表后，异步并发/同步请求 web-interface card 接口解析 sign，无缝追加虚拟推文。
- **采集性能**: 相比于冷启动 Playwright 无头浏览器，该方案仅增加一个常规的毫秒级 HTTP GET 请求，对系统总体吞吐无任何副作用。
