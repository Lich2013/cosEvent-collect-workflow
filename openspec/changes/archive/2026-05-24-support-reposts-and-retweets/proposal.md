## Why

在微博和 B 站上，Coser 经常通过转发（转发博文/转发动态）的方式来公布自己的出行日程或排班计划（例如转发官方漫展招募、次元集市日程或同行的排班表，并在转发语中写上自己的出席日期和扮演角色）。目前爬虫系统仅抓取原创博文正文，忽略了转发内容，导致大量 Cosplay 活动计划被遗漏。

支持转发/重贴内容的合并解析与提取，能够极大提升 Cosplay 计划提取的召回率和准确性。

## What Changes

- **微博爬虫数据拦截升级**：拦截并解析 `retweeted_status` 字段，提取原作者昵称和原博文正文，与 Coser 的附言按照统一的对话样式格式进行拼接合并。
- **B站爬虫数据拦截升级**：拦截并解析 `orig` 字段，提取原动态作者昵称和原动态正文，与 Coser 的附言按照统一的对话样式格式进行拼接合并。
- **零数据库破坏与零 Prompt 改变**：合并后的拼接文本直接作为博文正文写入 `raw_posts.content`。这确保了向下兼容性，且 downstream LLM 智能体能自然提取出信息，无需修改数据库 Schema 和 LLM 提示词。
- **新增回归测试**：在测试套件中添加模拟拦截转发数据包的单元测试，确保解析合并功能持续稳定。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `content-scraping`: 微博和 B 站的原生 API 拦截逻辑升级，拦截并解析 `retweeted_status` 及 `orig` 字段，并完成与 Coser 附言的拼接合并。

## Impact

- **修改的模块**：
  - [weibo_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/weibo_scraper.py)（修改 `fetch_weibo_posts` 解析逻辑）
  - [bilibili_scraper.py](file:///Users/lich/work/cosEvent-workflow/src/tools/bilibili_scraper.py)（修改 `fetch_bilibili_posts` 解析逻辑）
- **数据库影响**：无。合并后的拼接字符串直接存入 `raw_posts.content`，无需迁移数据库。
- **测试影响**：[test_cosevent.py](file:///Users/lich/work/cosEvent-workflow/tests/test_cosevent.py) 中新增 `test_repost_and_retweet_parsing` 单元测试。
