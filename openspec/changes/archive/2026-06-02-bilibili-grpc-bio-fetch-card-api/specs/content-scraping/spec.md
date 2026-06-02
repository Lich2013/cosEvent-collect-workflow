## ADDED Requirements

### Requirement: B站 gRPC 模式个人简介 Card API 联动补爬与合流
系统在 B站 gRPC 模式下抓取动态列表后，必须且 SHALL 执行签名（Bio）的提取与补爬处理：
- **gRPC 签名提取**：系统必须且 SHALL 首先尝试从 gRPC 响应 `DynSpaceRsp` 列表的作者信息（`module_author.author.sign`）中提取签名。
- **免浏览器冷启动 Web Card API 联动补爬**：若上述 gRPC 提取出的签名为空，系统必须且 SHALL 在应用层动态通过标准的免签名公开名片接口 `https://api.bilibili.com/x/web-interface/card?mid={uid}` 并注入拟真 macOS Desktop `User-Agent` 标头进行 HTTP 补爬获取主页签名，且绝对禁止冷启动重型的 Playwright 浏览器，以保护 gRPC 通路的极致效率。
- **非空虚拟推文合成**：若补爬获取到的签名经过 `strip()` 去除首尾空白后非空，系统必须且 SHALL 将其封装为以 `bio_{uid}` 为 `post_id`、以当前抓取时间为发布时间的虚拟推文合流返回。如果仍为空，则不合成虚拟推文，物理拦截空白版。

#### Scenario: gRPC 模式下成功通过 Card API 补爬并合成签名
- **WHEN** 启动 B站 gRPC 模式抓取，常规 gRPC 数据不含签名，但通过轻量级 Web Card API 成功抓取到用户签名 "热爱cos的普通人" 时
- **THEN** 采集层 SHALL 成功合成 `post_id="bio_2075682"` 且内容为 `[个人简介] 热爱cos的普通人` 的虚拟推文合流返回

#### Scenario: 接口请求异常时优雅降级不阻断常规抓取
- **WHEN** B站 Web Card 接口请求由于超时或网络故障报错时
- **THEN** 采集层 SHALL 优雅捕获异常，输出 Warning 警告日志，默认签名为空不合成虚拟推文，并且常规的 gRPC 博文列表正常返回，整个抓取进程绝对不崩溃中断
