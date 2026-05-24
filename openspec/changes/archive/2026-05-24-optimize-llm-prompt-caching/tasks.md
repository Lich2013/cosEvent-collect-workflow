## 1. 提示词系统模板优化与整合

- [x] 1.1 更新 `config/templates/event_analysis.jinja2` 模板，在合适部分整合原本位于代码中的静态核心提取动作与过滤说明
- [x] 1.2 更新 `config/templates/event_consensus_judge.jinja2` 模板，在规则与规范部分合并原本位于代码尾端的静态裁决合并去重指令

## 2. 智能体提取与裁决逻辑代码重构

- [x] 2.1 修改 `src/agents/event_agent.py` 中的并行提取逻辑，移除 `input_text` 变量前部的静态引导文案前缀，使其仅拼接动态的发布时间、正文与链接
- [x] 2.2 修改 `src/agents/event_agent.py` 中的终审裁决逻辑，从 `judge_prompt` 的尾部彻底剥离静态裁决合并引导指令，维持输入部分的纯净化数据格式

## 3. 单元测试更新与全量验证

- [x] 3.1 修改 `tests/test_cosevent.py` 中 `test_relative_date_parsing_with_published_at` 单元测试，重构其针对 mock 调用所捕获的 User Prompt 最头部的字符串对齐断言
- [x] 3.2 在本利虚拟环境下执行全量测试套件 `uv run pytest`，确保全套 19/19 个测试案例通过，确认重构未引入任何回归故障
