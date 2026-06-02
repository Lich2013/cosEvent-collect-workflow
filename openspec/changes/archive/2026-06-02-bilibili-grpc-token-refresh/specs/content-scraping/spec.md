## ADDED Requirements

### Requirement: B站 gRPC 凭证自愈式刷新与持久化配置自更新
系统在第一方移动端 gRPC 模式抓取用户动态时，必须且 SHALL 支持 Token 自动过期检测、接口自愈刷新与配置的持久化热写入：
- **过期与鉴权异常拦截判定**：当 gRPC 调用抛出 `grpc.RpcError` 时，系统必须且 SHALL 检测其错误状态与描述文本。若包含表示鉴权失败/Token过期的特征关键字（包含 `"identify_v1"`, `"-101"`, `"unauthenticated"`, `"signature"`），且本地配置中存在 `refresh_token`，系统必须且 SHALL 触发自愈式刷新逻辑，绝对不允许直接崩溃。
- **签名签名安全计算与置换**：自愈刷新必须且 SHALL 发起 POST 请求至 B站移动端刷新接口 `https://passport.bilibili.com/api/v2/oauth2/refresh_token`。请求参数必须包含 `access_token`, `refresh_token`, `appkey` 以及 Unix 时间戳 `ts`，并依据参数键值升序排列拼装当前 emulated 客户端 AppKey 对应的 `appsec` 计算 32 位 MD5 作为 `sign` 标头以通过防爬风控校验。
- **双重热更新与物理持久化**：刷新接口成功返回新的 `access_token` 和 `refresh_token` 后，系统必须且 SHALL 同时执行两步持久化操作：第一步，物理重写根目录下的 `.env` 文件，用正则表达式匹配并动态替换 `BILIBILI_ACCESS_TOKEN` 与 `BILIBILI_REFRESH_TOKEN` 的内容（即使被 `#` 注释也必须且 SHALL 自适应取消注释并写入）；第二步，在内存中更新 `settings` 对应的变量。
- **单次安全重试与降级**：热写入完毕后，gRPC 采集层必须且 SHALL 自动使用新 Access Token 重新发起 1 次 DynSpace 动态抓取请求；若重试再次失败或刷新过程中接口报错，系统必须且 SHALL 优雅向上抛出异常，以便主流程安全熔断并降级回网页 Playwright 爬虫抓取，保护采集流的高可用。

#### Scenario: gRPC 抓取因 Token 过期成功触发自愈刷新与持久化重试
- **WHEN** 启动 B站 gRPC 抓取用户动态，常规请求由于 Token 过期报错 code = -101，且本地存有 refresh_token "old_refresh" 时
- **THEN** 采集层 SHALL 精准拦截该异常，自动请求 B站刷新接口置换出 "new_access" 和 "new_refresh"，物理将新值写入 `.env` 并更新配置，随后成功重试 gRPC 抓取拿到动态列表

#### Scenario: 刷新接口异常时优雅熔断降级不崩溃
- **WHEN** 在刷新 Token 过程中，B站接口返回签名校验错误或网络异常报错时
- **THEN** 采集层 SHALL 优雅捕获该异常，物理停止重试，直接向上抛出最初的 gRPC 异常，使得系统顺利熔断并降级到 Playwright 网页抓取，抓取作业绝不崩溃中断
