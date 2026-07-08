## Context

当前项目已经具备 openai-agents SDK、Pydantic 输出契约、SQLite 强事务、DeepSeek JSON schema 降级、三态 `raw_posts.is_analyzed` 等基础能力。但审查发现几个边界仍由提示词或隐式约定承担：临时 LLM 故障可能被包装成 `ValueError` 后进入永久熔断，历史活动可能在数据库层以 `未开始` 落库，候选人抓取空结果可能被误判为非 Coser，多个模块各自读取当前日期导致测试和运行结果漂移。

本变更是跨模块加固，不改变 CLI 使用方式和数据库主表结构。实现应优先使用现有 SDK、仓储和模板模式，避免引入新依赖。

## Goals / Non-Goals

**Goals:**

- 将 LLM 临时失败与永久结构失败分开，保证可重试错误不会进入 `is_analyzed = 2`。
- 提供统一北京时间参考时钟，供模板、查询、持久化、物化和测试共用。
- 将仍硬编码的 Triage 与候选人核验 System Instructions 移入 `config/templates/`。
- 在数据库写入层阻断历史活动以 `未开始` 状态污染未来日程。
- 加固候选人状态合并与抓取不可确认场景，减少误忽略。
- 修复日期相关测试，使测试不依赖真实当前日期。

**Non-Goals:**

- 不重新设计整个 Agent pipeline。
- 不新增外部时间冻结库；测试可通过 monkeypatch 项目内部时间工具实现。
- 不变更 CLI 参数、命令名称或用户可见数据库 schema。
- 不把历史活动审计做成新的用户查询能力；本次只记录日志并阻断污染。

## Decisions

### 1. 新增项目内统一时钟工具

新增 `src/utils/time.py`，提供：
- `beijing_now() -> datetime.datetime`
- `beijing_today_str() -> str`
- `beijing_now_str() -> str`

所有当前日期判断改用该工具，包括 `templates.py`、`event_repository.py`、`query_service.py`、`materialize_service.py`、候选人冷却时间生成等新改动触达处。测试通过 monkeypatch 这些函数返回固定日期。

替代方案是每个测试分别 patch `datetime`，但该方式对 `from datetime import ...` 风格脆弱，且无法保证跨模块一致。

### 2. 用显式异常类型表达 LLM 临时失败

新增轻量异常类型，例如 `TransientLLMError`。当共识模式下所有 extractor 失败，或裁判/模型接口失败且没有结构性输出可判断时，Agent 层抛出该异常或普通网络异常，编排层将其归入暂时性失败，保持 `is_analyzed = 0`。

结构性失败仍由 `ValidationError`、`AssertionError`、`sqlite3.IntegrityError` 等确定性异常驱动 `mark_post_analysis_failed`。

替代方案是继续用 `ValueError` 并解析错误文本，但这会把语义藏在字符串里，容易再次误分类。

### 3. Prompt 模板承担 System Instructions

新增或拆分模板：
- `event_triage.jinja2`
- `candidate_verify_system.jinja2` 或调整现有 `candidate_verify.jinja2` 为 system/user 两段模板

Triage 与候选人核验 Agent 的 `instructions` 必须来自模板渲染结果。候选人的具体姓名和博文列表可以继续作为 Runner 输入，但核心行为规则、排除规则、输出契约和 `current_date` 放入 system prompt。

替代方案是继续把完整模板作为用户输入，但 system prompt 优先级不足，且不符合项目 AGENTS.md。

### 4. 数据库层过滤历史活动

在 `save_extracted_events_transactional` 中，事件进入融合和插入前先判断 `event_date`。若为标准日期且早于统一 `current_date`，记录 warning 并跳过，不调用 fusion，不插入 `cosplay_events`，不影响该博文最终标记为已分析。

这选择了“严格未来日程系统”语义。保留历史活动作为审计数据是另一个方向，但需要新的状态查询和导出策略，不属于本次范围。

### 5. 候选人核验保守处理不可确认空结果

候选人抓取层需要能表达“失败/不可确认”和“成功但无博文”。短期实现可以在 `DiscoveryService` 中将 scraper 异常与已知空返回路径显式标记；若 scraper 当前把超时吞成 `[]`，应优先调整返回元数据或在候选人核验入口保守处理：无强证据时保留 pending，而不是 hard-ignore。

重复发现合并时，`CandidateRepository.add_candidate` 保留既有 `is_verified=1` 和 `verify_reason`，除非新入参明确带来新的验证通过结果。

## Risks / Trade-offs

- [Risk] 历史活动被跳过后，用户无法通过 `scope=all` 查到 LLM 识别出的历史证据 → Mitigation: 记录审计日志；若以后需要历史审计，单独设计非未来日程归档能力。
- [Risk] 对不可确认空结果更保守会让 pending 候选人停留更久 → Mitigation: 7 天冷却和人工列表仍可处理，避免误删比减少 pending 更重要。
- [Risk] 统一时钟改动触及多个模块，可能漏改一处 `datetime.now()` → Mitigation: 增加针对导出、物化、模板渲染和持久化的冻结时间测试，并用 `rg "datetime\.date\.today|datetime\.datetime\.now" src` 做实现检查。
- [Risk] Prompt 模板拆分可能影响现有 LLM 输入格式 → Mitigation: 保留现有用户输入字段结构，仅提升 system instructions 来源和时间注入方式。

## Migration Plan

1. 新增统一时钟工具和异常类型，不改变外部接口。
2. 逐步替换触达模块的当前时间读取，先修测试覆盖的查询/导出/模板/物化路径。
3. 迁移 Triage 与候选人核验 Prompt 到模板，保持输出模型不变。
4. 加入历史活动跳过逻辑和候选人状态合并加固。
5. 运行完整 `uv run pytest`，并补充针对 7 个修复点的聚焦测试。

回滚策略：这些改动不涉及数据库 schema 迁移；如需回滚，可恢复调用点到原有 `datetime` 和硬编码 prompt，但不建议保留误熔断行为。

## Open Questions

- 历史活动是否未来需要单独审计表或 `已结束` 状态归档？本次默认不做。
- scraper 是否需要统一返回带状态的结果对象，以明确区分真实空列表和抓取失败？本次可先在 Discovery 层保守处理，后续再考虑接口升级。
