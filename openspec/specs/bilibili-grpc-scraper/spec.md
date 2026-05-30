# bilibili-grpc-scraper Specification

## Purpose
TBD - created by archiving change integrate-bilibili-grpc-dynamic-updater. Update Purpose after archive.
## Requirements
### Requirement: B站 gRPC 凭证配置与初始化读取
系统必须且 SHALL 从配置文件 `config/settings.yaml` 或系统环境变量（支持 `.env` 文件覆盖）中读取 B 站 gRPC 抓取所必需的移动端凭证（`bilibili_grpc_access_token` 和 `bilibili_grpc_mid`）。
在 scraper 实例化或初始化时，系统必须检查这些配置项是否存在且非空。若均有效，则置为 gRPC 优先模式；若缺失，则自动标记为网页降级模式。

#### Scenario: 成功加载凭证并启用 gRPC 优先模式
- **WHEN** BilibiliScraper 初始化并读取配置，发现 `access_token` 和 `mid` 均存在且有效
- **THEN** 系统 SHALL 将内部抓取模式标记为 gRPC 优先，为后续抓取流作好准备

#### Scenario: 凭证缺失静默降级为 Playwright
- **WHEN** BilibiliScraper 启动时发现凭证为空或缺失
- **THEN** 系统 SHALL 输出包含 `[Scraper Warning]` 标识的警告日志，并直接降级为 Playwright 网页拦截模式，不抛出任何运行时崩溃异常

### Requirement: gRPC 空间动态数据安全请求与解析
在 gRPC 模式下，系统必须且 SHALL 通过安全 gRPC 信道（`grpc.biliapi.net:443`）和 stub `DynSpace` 方法请求目标 UID 主的空间动态列表。
请求时，必须且 SHALL 注入完整的移动端 Metadata 头部，包括 `authorization` (`identify_v1 {access_token}`), `x-bili-mid`, `x-bili-aurora-eid`, `x-bili-trace-id` 及序列化后的二进制 Device/Network/Restriction/Locale 等 Protobuf 结构体，以绕过服务器的风控指纹阻断。
解析响应时：
- 动态 ID：必须且 SHALL 从 `item.extend.dyn_id_str` 提取。
- 正文内容：必须遍历 `module_opus_summary.summary` 的文本节点并进行合并，若无则降级从 `module_desc.text` 获取。若为转发动态，必须且 SHALL 合并原作者和原动态内容。
- 时间解析：必须且 SHALL 从 `module_author.ptime_label_text` 中解析发布/编辑时间，判定是否含有“编辑于”字样。

#### Scenario: 成功通过 gRPC 抓取并解析动态
- **WHEN** 传入有效 UID 进行 gRPC 空间动态抓取并得到成功响应
- **THEN** 系统返回包含真实动态 ID、完整合并正文、`published_at`（标准北京时间格式）、以及 `is_grpc = True` 和 `is_edited = True/False` 标志的博文字典列表

### Requirement: ptime_label_text 时间正则解析与年份智能推导
系统必须且 SHALL 编写高效健壮的正则时间解析函数。
若时间标签含有 `"编辑于"` 字样，系统必须且 SHALL 将其判定为已编辑（`is_edited = True`），并提取后面的日期时间字符串。
系统必须且 SHALL 支持绝对时间（如 `"2026年5月25日 04:05"`、`"5月25日 04:05"`、`"05-25"`）与相对时间（如 `"昨天 04:05"`、`"1小时前"`）的解析。
若日期缺少年份，系统必须且 SHALL 根据当前系统参考时间年份进行补齐。如果补齐后的日期时间在未来（早于当前时间但超出临界点），系统必须且 SHALL 自动减去 1 年以防止年份幻觉。

#### Scenario: 成功解析高精度物理编辑时间并完成年份补齐
- **WHEN** 解析时间标签 `"编辑于 5月25日 04:05"`，且当前系统时间为 `2026-05-29 01:41:25`
- **THEN** 系统返回 `is_edited = True` 且 `published_at = "2026-05-25 04:05:00"`

### Requirement: 传输层 RpcError 健壮性异常捕获与熔断降级
在进行 gRPC 交互时，系统必须且 SHALL 用 `try-except grpc.RpcError` 结构对网络与通信进行强健壮性包裹。
若发生任何网络连接超时、鉴权失败（`-101`）或风控阻断（`-352`）等 RPC 报错，系统必须且 SHALL 捕获异常，输出黄色 `WARNING` 并立刻执行熔断降级，自动回退到 Playwright 无头浏览器抓取机制。

#### Scenario: gRPC 报错自动且零崩溃降级为 Playwright
- **WHEN** 运行 gRPC 空间动态请求遭遇鉴权失效的 `RpcError`
- **THEN** 系统打印警告日志，熔断当前 gRPC 连接，并调用 Playwright 网页抓取流顺利返回抓取结果

