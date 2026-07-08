## Why

当前分析链路存在几类会产生静默错误的边界：临时 LLM 故障可能被熔断为永久失败，历史活动可能越过 Prompt 约束写入数据库，候选人抓取空结果可能被误判为非 Coser，同时测试和运行逻辑对“当前日期”的使用不稳定。现在需要把这些边界从提示词约束提升为代码和规格层面的硬防线，避免增量调度、导出和候选人核验在真实运行中产生不可恢复的状态污染。

## What Changes

- 区分 LLM 暂时性异常与永久结构性异常，避免供应商超时、所有 extractor 临时失败等情况错误标记 `raw_posts.is_analyzed = 2`。
- 引入统一北京时间参考时钟，并让测试能够冻结当前日期，消除导出、查询、物化、Prompt 渲染之间的时间漂移。
- 将 Triage 与候选人核验 Agent 的 System Instructions 迁移到 `config/templates/`，并统一注入 `current_date` 与必要上下文。
- 在活动持久化层对历史活动增加硬兜底：历史日期不得以 `未开始` 状态写入未来日程流。
- 加固候选人核验状态机：抓取不可确认时不得直接 hard-ignore；重新发现候选人时不得覆盖已核验结果。
- 修复导出范围测试，确保 `future`/`all` 范围在任意真实日期下保持确定性。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `event-extraction`: 分析异常分类、Agent 模板化、历史活动持久化兜底、三态状态机语义需要加固。
- `coser-candidates`: 候选人核验对抓取失败、空结果、已验证候选人重复发现的状态流转要求需要加固。
- `data-export`: 导出范围依赖统一参考日期，并需要可测试的日期锚定保证。

## Impact

- 影响 `src/agents/event_agent.py`、`src/services/workflow_orchestrator.py`、`src/services/db/event_repository.py`、`src/services/db/query_service.py`、`src/services/db/materialize_service.py`、`src/services/discovery_service.py`、`src/services/db/candidate_repository.py`、`src/utils/templates.py` 及测试。
- 需要新增或调整 Prompt 模板文件，例如 triage 与候选人核验 system prompt。
- 不引入新的外部依赖；新增的时间工具应保持纯 Python 标准库实现。
- 不改变 CLI 参数和数据库表结构，除非实现阶段发现需要补充审计字段。
