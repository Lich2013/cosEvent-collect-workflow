## Context

有些 Coser 不发布新动态，而是将近期的漫展/签售行程直接写在个人简介（Bio/签名）中。本系统目前只抓取推文动态，会漏掉这部分有价值的日程信息。因此需要将个人简介（Bio）抽象为一条特殊的虚拟动态推文，通过既有的分析与合并流程将其闭环。

## Goals / Non-Goals

**Goals:**
- 支持微博、B站、小红书三大平台的个人简介（Bio）抓取。
- 将抓取到的 Bio 文本，以 `bio_{uid}` 为 `post_id` 封装合成为一条虚拟推文，投递进原有的数据流。
- 100% 兼容既有的数据库去重与版本控制机制（`#v` 版本递增），如果个人简介内容更新，则物理新增一条高版本记录，重置分析状态。
- 原生兼容后续的 AI 增量分析提取与时空物化重建流程。

**Non-Goals:**
- 不修改现有的数据库表结构或进行数据表迁移。
- 不更改既有 AI 增量分析引擎（Analyze Command）与共识决策（Triage/Extractor/Judge）的核心契约。

## Decisions

### 决策一：采用 `bio_{uid}` 格式作为虚拟动态的 `post_id`
- **理由**：虽然 B站与微博的动态 ID 长度远超用户 UID，但在海量数据下直接使用 `uid` 作为 `post_id` 仍存在理论碰撞风险。通过前缀隔离（如 `bio_2075682`），可 100% 物理杜绝冲突，且使数据可读性、可追溯性达到最优。
- **备选方案**：直接使用 `uid` 作为 `post_id`（有极微小冲突隐患）。

### 决策二：在采集层（Scraper）完成虚拟动态合成与注入
- **理由**：各 Scraper 在拉取推文列表返回前，获取对应 UID 的 Bio，拼装出 `post_id = "bio_" + uid` 的虚拟推文对象，直接 `append` 到抓取结果 list 的最末尾。
- **收益**：数据库层（`DBService.save_raw_posts`）、AI 分析层及命令行调用层均**无需做任何感知和代码修改**。系统会天然将其当作一条新发布的推文进行处理，零成本接入去重和 `#v1` 物理版本控制。

### 决策三：采用 Ajax API 拦截（expect_response）作为个人简介抓取的首要通路
- **微博**：直接通过 `page.expect_response` 拦截并抓取 `/ajax/profile/info?uid={uid}` 接口（或从 `mymblog` 推文列表响应体的 `user.description` 提取），安全防爬，零 DOM 依赖。
- **Bilibili**：
  - **gRPC 模式**：尝试从 `DynSpaceResp` 响应体中的用户信息层提取 signature；
  - **Playwright 网页模式**：通过 `page.expect_response` 在底层透明拦截浏览器发出的 `/x/space/wbi/acc/info?mid={uid}` 接口。由于浏览器会自动算好 WBI 加密签名，我们只需直接读取拦截到的 JSON 中的 `data.sign`，100% 免疫网页 UI 元素改版或混淆编译。
- **小红书**：通过 `page.expect_response` 底层拦截浏览器自动执行的 `/api/sns/web/v1/user/otherinfo?target_user_id={uid}` 接口，直接读取响应 JSON 中的 `data.desc`，彻底斩断对 brittle 网页选择器的依赖。
- **多级备选 DOM 兜底**：若上述 Ajax 接口由于网络因素或超时未能成功拦截，系统将使用 `try-except` 包裹，尝试通过 DOM 选择器（如 B站 `.h-sign`，小红书 `.user-desc`）作为次级补爬。若双重保险均告失败，输出黄色 Warning 并返回空字符串 `""`，确保主程序抓取 100% 畅通不阻断。

## Risks / Trade-offs

- **[Risk] Coser 微调个人简介（如改个标点或表情）引发不必要的版本升级与 AI 消费**
  - *Mitigation*：我们已有的 **Triage Agent**（预检分流智能体）会在首轮执行极度廉价的快速初筛。若改动内容无具体活动，会通过 `has_event = False` 直接秒级熔断退出，API 消费近乎为 0。
- **[Risk] 空简介或删除简介（Bio 被清空）导致的空白版本死循环膨胀**
  - *Mitigation*：在 Scraper 组装虚拟推文时引入**前置门槛过滤**：如果提取出的简介文本经过 `strip()` 去除首尾空白后为空白字符串（如 `""`），则**直接跳过虚拟动态的生成，不追加到任何推文列表中**。这能彻底从源头上斩断空白版本无休止膨胀对数据库和 AI Token 的损耗。
- **[Risk] 简介动态无明确的发布时间戳，导致 AI 相对年份推算产生偏差**
  - *Mitigation*：在合成虚拟推文时，将 `published_at` 显式设为**当前系统抓取时间（北京时间）**。由于 AI 模板中已动态注入了当前系统参考时间，AI 可以完美识别简介中的相对月份，并正确规避已过期的历史活动。
