## Context

当前系统在分析提取未处理的原始博文时，从 SQLite 数据库查询 `raw_posts` 数据，并通过命令行主逻辑调用智能体模块进行分析。智能体目前仅接收运行时系统的当前日期（如 `2026-05-24`）作为系统时间参考，这导致相对日期描述（如“下周末”、“明天”）极易发生计算偏差，阻碍了活动提取精度。

因此，我们需要将 `raw_posts` 中已有的 `published_at` 博文发表时间通过整个链路进行接力传递，并在 User Prompt 组装时动态拼装注入，为智能体进行相对时间推导提供物理基准。

## Goals / Non-Goals

**Goals:**
- **博文发布日期全链路传递**：扩充数据库查询、命令方法传递和智能体入参，将 `published_at` 完美传导。
- **高精度相对日期推导**：通过在智能体输入中显式注入“博文发布时间”，使得 LLM 具备完整的时序对照关系，精准解析相对日程。
- **平滑降级与兼容**：对于一些 `published_at` 为 `None` 或者是历史脏数据的场景，能够优雅忽略或忽略提示词，避免解析崩溃。

**Non-Goals:**
- **不在数据库表结构中增加新列**：因为 `raw_posts` 表本身已经包含 `published_at` 字段，所以不需要修改数据库 Scheme 定义。
- **不干预爬行（Scrape）逻辑**：该重构仅涉及数据消费读取（Analyze）和提示词拼装层面。

## Decisions

### 核心决策：全链路传导 `published_at` 并重写 User Prompt 构建逻辑

#### 1. 数据传递路径设计
```
[SQLite: SELECT published_at]
         │
         ▼
[DBService.get_unanalyzed_posts] (在回传字典字典中增加 "published_at")
         │
         ▼
[src/main.py -> _async_analyze] (提取出 p["published_at"] 并传参给智能体)
         │
         ▼
[src/agents/event_agent.py -> analyze_post_with_retry] (动态修改 input_text)
```

#### 2. User Prompt (智能体输入文本) 重构方案
在 `src/agents/event_agent.py` 的 `analyze_post_with_retry` 中，接收可选的 `published_at: str | None = None`：
```python
    input_text = "请提取这篇博文中的未来 Cosplay 活动计划。若不包含任何二次元漫展，则返回空列表。\n\n"
    if published_at:
        input_text += f"博文发布时间:\n{published_at}\n\n"
    input_text += f"博文正文:\n{content}\n\n原帖链接:\n{url}"
```

对于 system 角色对应的 Jinja2 模板（`event_analysis.jinja2`），无需做任何侵入修改，因为它会继续持有当前系统运行日期作为“过滤过期活动”的依据；而 User Prompt 里的“博文发布时间”将专门作为 LLM 进行“下周末23号”等相对时间计算的“原点”。两者相辅相成。

## Risks / Trade-offs

- **[Risk] `published_at` 字段为 NULL 或格式错误时引发大模型反噬** → **Mitigation**: 在 `event_agent.py` 的 `analyze_post_with_retry` 入口处对 `published_at` 执行检验，只有当其为真值且是非空字符串时才进行 Prompt 拼接；否则退回原有逻辑，保证强大的前向与向下兼容性。
