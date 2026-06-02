## Why

现有的 B站 gRPC 抓取模式在获取 Coser 动态时，需要用到移动端 App 方式授权的 `access_token` 和 `refresh_token`。然而，这些令牌具有一定的有效期（通常 access_token 为 180 天，且会因 B站风控、密码变更或 IP 重大变更而提失效）。
目前系统完全缺乏 Token 自动刷新机制：
1. 之前的扫码登录脚本（`bili_app_qr_login.py`）只引导用户复制了 `access_token`，未保存 `refresh_token`，且在 `.env` 模板中也未默认启用。
2. 当 Token 过期失效时，gRPC 抓取会报错 `grpc.RpcError (-101/账号未登录)` 并熔断降级回网页 Playwright 爬虫，失去了 gRPC 高速、低耗、低风控的采集优势。

本变更旨在引入 B站移动端第一方 Token 自动刷新与自愈持久化机制，实现 gRPC 抓取通道的长期高可用性。

## What Changes

- **Token 自动检测与自愈刷新**：在 gRPC 抓取遭遇 `grpc.RpcError`（由于 Access Token 过期/校验失败导致）时，自动触发 Token 刷新逻辑，利用 `refresh_token` 置换新 Token，并重试 gRPC 请求。
- **配置持久化更新**：刷新成功后，系统自动将最新的 `access_token` 和 `refresh_token` 持久化写回根目录下的 `.env` 文件，同时更新内存中的 `settings` 配置，保障后续运行正常。
- **登录引导优化与自动写入**：升级 `bili_app_qr_login.py` 扫码脚本，支持输出 `refresh_token` 并自动更新写入 `.env` 文件，极大降低用户的手动维护心智。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `content-scraping`: 增加 B站 gRPC 授权凭证自动检测、利用 `refresh_token` 刷新、写入 `.env` 以及重试的鲁棒性要求。

## Impact

- **Bilibili Scraper** (`src/tools/bilibili_scraper.py`): 核心处理逻辑，在 `fetch_bilibili_posts_grpc` 异常处理中截获 RpcError 并进行 Token 刷新，更新配置并重试，包含 `_update_dotenv` 和 `refresh_bilibili_grpc_token` 等方法。
- **Config Loader** (`src/config.py`): 增加 `bilibili_grpc_refresh_token` 配置项 of 加载和环境变量插值支持。
- **Settings Yaml** (`config/settings.yaml` / `settings.yaml.example`): 增加 `refresh_token: "${BILIBILI_REFRESH_TOKEN}"` 配置字段。
- **Dotenv Template** (`.env`): 默认追加/开启 `BILIBILI_REFRESH_TOKEN` 环境变量。
- **App Login Script** (`scripts/bili_app_qr_login.py`): 升级登录提示信息，输出 `refresh_token`，并支持交互式一键自动保存至项目 `.env` 文件。
