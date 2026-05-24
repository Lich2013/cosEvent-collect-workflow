## Why

当前系统在分析提取 Cosplay 活动时，会动态向智能体注入运行时的“当前系统参考时间”（格式 `YYYY-MM-DD`）以判断并过滤已发生的历史活动。但在处理博文中包含的相对日期描述（如“下周末23号”、“明天见”、“本周五出行”等）时，仅有运行时系统时间作为上下文是远远不够的。

智能体无法知道该条博文在物理现实中是什么时间被发表的（即缺乏 `published_at` 博文发布时间），导致其在解析“下周末”或“明天”时，使用的是当前运行分析时间作为计算基准，这产生了严重的相对时间偏差（甚至导致正确提取的活动被判定为历史已过期活动而被误杀过滤）。因此，必须向智能体输入中显式引入博文发布时间上下文。

## What Changes

- **数据库读取层扩展**：修改 `DBService.get_unanalyzed_posts`，在查询未分析原始博文列表时，扩展 `SELECT` 语句，一并取出 `published_at` 字段并随字典传回。
- **分析命令调用层适配**：修改 `src/main.py` 中的 `_async_analyze` 逻辑，在迭代博文调用 `analyze_post_with_retry` 时，显式提取并传入 `p["published_at"]`。
- **智能体接口与提示词注入**：修改 `src/agents/event_agent.py` 中的 `analyze_post_with_retry` 函数签名，支持接收可选的 `published_at`。如果 `published_at` 存在且非空，则动态将其格式化拼接并追加到 User Prompt 的最头部（如 `"博文发布时间:\n2026-05-15 17:00:00\n\n"`），提供精准的时序对齐基准。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `event-extraction`: 升级智能体分析时序判定契约。系统必须且 SHALL 在向大模型智能体提交博文分析请求时，提取并显式注入博文发表日期时间（`published_at`）作为环境参考，以绝对保证相对日期描述（如“下周末”、“明天”）能够以博文发表时序为物理基准被高精度精准提取与对齐。

## Impact

- `src/services/db_service.py`: `get_unanalyzed_posts` 需加选并回传 `published_at` 字段。
- `src/main.py`: `_async_analyze` 增量传递参数。
- `src/agents/event_agent.py`: `analyze_post_with_retry` 参数及 prompt 动态组装适配。
- `tests/test_cosevent.py`: 需增加单元测试，构造带有历史发表日期的博文，验证相对时间如“下周末23号”能否借助注入的发布日期，被大模型精确对齐为绝对日期并成功返回。
