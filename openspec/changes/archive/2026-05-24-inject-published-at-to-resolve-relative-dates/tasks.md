## 1. 全链路传递与 Prompt 组装重构

- [x] 1.1 修改 `src/services/db_service.py` 中的 `get_unanalyzed_posts`，在查询未分析原始博文时将 `published_at` 一并 `SELECT` 选出并回传到待分析的博文字典中
- [x] 1.2 修改 `src/main.py` 中的 `_async_analyze` 逻辑，在取出未处理博文进行提取迭代时，显式提取 `p["published_at"]` 并将其参数化传入给 `analyze_post_with_retry`
- [x] 1.3 重构 `src/agents/event_agent.py` 中的 `analyze_post_with_retry`，使其方法签名支持接收可选参数 `published_at: str | None = None`
- [x] 1.4 在 `analyze_post_with_retry` 中重构最终发送给 LLM 智能体的 `input_text` (User Prompt) 拼接逻辑，若传入了非空 `published_at`，则在博文正文前部显式且动态拼接并格式化注入 `"博文发布时间:\n{published_at}\n\n"` 字段

## 2. 单元测试与高精度时序回归验证

- [x] 2.1 更新 `tests/test_cosevent.py`，新增时序精准对齐解析单元测试 `test_relative_date_parsing_with_published_at`，手动传入带精确 `published_at` (例如 `2026-05-15 17:00:00`，为周五) 以及带相对模糊时间（例如“下周末23号见咯”）的博文，断言智能体在解析提取出该活动日期时能够被精确还原为绝对日期 `"2026-05-23"`
- [x] 2.2 运行本地 `uv run pytest` 回归测试，确保包含新增用例在内的 18 个测试用例全部完美通过
