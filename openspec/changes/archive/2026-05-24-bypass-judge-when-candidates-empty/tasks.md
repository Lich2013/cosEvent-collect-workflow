## 1. 核心流程控制重写与裁判智能旁路实现

- [x] 1.1 修改 `src/agents/event_agent.py` 中的共识模式处理块。在收集并成功序列化并行提取器的候选列表 `valid_outputs` 之后，统计并累加所有提取器提取到的候选活动总数 `total_extracted_candidates`
- [x] 1.2 在 `event_agent.py` 中，如果 `total_extracted_candidates == 0`，打印调试日志并自动旁路（跳过）终审裁判智能体（Judge Agent）的调用，直接返回空列表 `[]`
- [x] 1.3 确保非空候选（存在分歧）的逻辑完全不受影响，依旧能够正常流转并唤醒金牌裁判大模型执行去重与模糊合并仲裁

## 2. 单元测试与旁路拦截有效性验证

- [x] 2.1 更新 `tests/test_cosevent.py`，新增单元测试用例 `test_judge_bypass_when_candidates_empty`。模拟共识模式（Consensus Mode）下的提取流，配置两个并行提取模型均正常运行且返回空候选列表，断言智能体分析结果立即返回 `[]`，且终审裁判大模型的 `Runner.run` 从未被唤醒调用（调用次数为 0）
- [x] 2.2 运行本地 `uv run pytest` 回归测试，确保包含新增用例在内的 19 个测试用例全部完美通过
