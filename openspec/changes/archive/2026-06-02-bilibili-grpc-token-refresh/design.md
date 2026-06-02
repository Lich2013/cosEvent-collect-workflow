## Context

在 B站 gRPC 抓取（`fetch_bilibili_posts_grpc`）中，我们需要利用扫码登录或抓包获取的 `access_token` 进行鉴权。由于该 Token 存在 180 天有效期或临时风控失效风险，当其过期时，gRPC 会抛出 `grpc.RpcError (-101: 账号未登录)` 异常。
目前系统遇到该异常时只能降级回 Playwright 网页爬虫，导致运行速度变慢，且容易触发社交平台的前端风控。
为解决此问题，本设计决定在 gRPC 抓取中集成一个**自愈式 Token 刷新与持久化写入机制**，当检测到鉴权失败时，利用已保存的 `refresh_token` 自动请求 B站移动端刷新 API，并在成功后自动写入更新 `.env` 配置文件。

---

## Goals / Non-Goals

**Goals:**
- 在 gRPC 抓取遭遇 `grpc.RpcError` 且可能是由于 Token 失效引起时，自动拦截。
- 调用 B站移动端 Token 刷新 API：`https://passport.bilibili.com/api/v2/oauth2/refresh_token`。
- 刷新成功后，自动通过重正则解析并替换物理 `.env` 文件中的 Token 变量（保存最新状态，跨进程持久化）。
- 同时在内存中热更新 `settings` 凭证，重新进行一次 gRPC 动态抓取尝试。
- 对扫码登录脚本 `bili_app_qr_login.py` 进行重构，支持一键交互式写入/升级根目录下 `.env` 文件的 `BILIBILI_ACCESS_TOKEN`、`BILIBILI_REFRESH_TOKEN` 和 `BILIBILI_MID`，降低维护成本。

**Non-Goals:**
- 不改变既有的 gRPC protobuf 依赖结构。
- 不执行 Playwright Web Cookie 的自动刷新（两者鉴权通路隔离，Web 端的 Cookie 刷新已有独立的 `cookie_refresh.md` 规范且由 Scraper 自动降级维护，此处专指 App gRPC token 刷新）。

---

## Decisions

### 1. 拦截 RpcError 与自愈式 Token 刷新重试
- **决策**：在 `fetch_bilibili_posts_grpc` 核心 gRPC 调用外侧封装重试与错误自愈拦截：
  ```python
  try:
      return await self._fetch_bilibili_posts_grpc_internal(uid, limit)
  except Exception as e:
      if self._is_bili_grpc_auth_error(e) and settings.bilibili_grpc_refresh_token:
          print("Detect Bilibili gRPC Token expired, attempting self-healing refresh...")
          success = await self.refresh_bilibili_grpc_token()
          if success:
              print("Bilibili Token refreshed successfully! Retrying gRPC...")
              return await self._fetch_bilibili_posts_grpc_internal(uid, limit)
      raise e
  ```
- **考量**：
  - **精准判定**：`_is_bili_grpc_auth_error` 负责识别 `grpc.RpcError`，并检测其描述中是否含有 `"identify_v1"`, `"-101"`, `"unauthenticated"`, `"signature"` 等 B站移动端特征鉴权错误关键字，防止因网络故障、DNS 失败等非鉴权因素发起无效刷新。
  - **单次重试门槛**：刷新成功后仅允许重试 1 次，若重试依然失败，则原样抛出异常，让程序安全降级到 Playwright，绝对不引发无尽死循环。

### 2. 刷新签名计算与 API 调用
- **决策**：调用 B站移动端 Passport 刷新接口：`POST https://passport.bilibili.com/api/v2/oauth2/refresh_token`。
  - 根据 `settings.bilibili_grpc_mobi_app`（例如 `android_hd`、`android`）在代码中预存的客户端 AppKey/AppSecret 对照表中查出对应的授权密钥（默认 HD 平板版 `dfca71928277209b`/`b5475a8825547a4fc26c7d518eaaa02e`）。
  - 对 `access_token`, `refresh_token`, `appkey`, `ts` 进行升序排序并拼接 `appsec` 计算 MD5 生成 `sign` 参数。
  - 使用 `requests.post` 并通过 `asyncio.to_thread` 包装发起非阻塞的 HTTP 提交。
- **考量**：
  - 这种签名计算机制与登录脚本 `calc_sign` 100% 对齐，已在社区中得到充分逆向工程和验证，极度稳定。

### 3. 多行正则 `.env` 物理写入与持久化
- **决策**：利用正则对根目录下的 `.env` 文件进行物理匹配写入：
  - 用 `re.sub` 针对 `BILIBILI_ACCESS_TOKEN` 进行替换，匹配以该变量开头的单行。
  - 用 `re.sub` 针对 `BILIBILI_REFRESH_TOKEN` 进行替换，能够同时匹配可能被注释（如 `# BILIBILI_REFRESH_TOKEN=...`）或已存在的有效行。
- **考量**：
  - 许多用户在初次使用时没有配置 `BILIBILI_REFRESH_TOKEN`。通过正则感知，我们即使在变量以 `#` 注释的形式存在时，也能够直接将其解锁并自动升级写入成最新有效的非注释配置项！

### 4. 模拟登录工具一键交互式写入自愈
- **决策**：升级 `bili_app_qr_login.py` 扫码脚本，在展示完 token 信息后，主动询问：
  `是否要自动将这些变量保存到项目根目录的 .env 文件中？(y/n, 默认 y):`
  并在确认后利用正则物理自动刷新根目录下的 `.env` 变量，免除用户繁琐的手动复制动作。

---

## Risks / Trade-offs

- **[Risk] 频繁调用刷新接口导致账号频控/风控**
  - **Mitigation**：因为 B站 Token 有效期极长（180 天），仅在 gRPC 鉴权失败报错时才会触发本自愈刷新（典型频率为数月一次，即使异常发生也只有单次重试），完全不会产生高频刷新造成的风控压力。
- **[Risk] B站 Passport 刷新接口升级或屏蔽**
  - **Mitigation**：由于我们仅将 gRPC 作为首选，一旦刷新接口在未来失效导致返回非 0 code，系统仅打印 `[Scraper Error]` 日志返回 `False`，并自动通过 `raise e` 降级回 Playwright 网页抓取，确保主流程 100% 具备卓越的抗震防灾能力。
