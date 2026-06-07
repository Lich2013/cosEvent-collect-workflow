## Why

当前 Coser 候选人的自动验证仅依赖于 B站/微博的个人空间简介（Bio）关键词匹配，对于简介中没有明确二次元/Coser 关键词的活跃 Coser，极易产生漏检，导致验证召回率偏低。通过爬取候选人最新的博文并使用大模型进行纯文本活动相关性分析，可以大幅提升候选人身份自动核验的准确性与召回率。

## What Changes

- **物理隔离候选人博文存储**：在数据库中新增独立物理表 `candidate_raw_posts`，与生产环境的正式 `raw_posts` 隔离，用于暂存候选人的最近博文。
- **候选人博文增量抓取与调度**：在工作流中新增候选人博文的轻量级抓取，每次抓取待核验候选人的 3-5 条最新博文。
- **博文内容 LLM 智能体分类核验**：新增纯文本核验智能体，读取候选人近期博文，并输出是否为 Coser 的布尔结论及判定依据（verify_reason）。
- **待审批候选人展示增强**：增强终端命令行列表展示，在待审批候选人列表中直观呈现 LLM 的判定依据，方便人工审查一键转正。

## Capabilities

### New Capabilities

- *(无)*

### Modified Capabilities

- `coser-candidates`: 增强候选人核验判定能力，由原来的仅 Bio 核验升级为“空间Bio核验 + 近期博文 LLM 文本分类核验”双重核验机制，同时物理隔离存储候选人博文，并在终端直观呈现核验理由。

## Impact

- 数据库 Schema：`db_models.py` 新增 `candidate_raw_posts` 表，`coser_candidates` 表新增 `verify_reason` 字段。
- 业务流程层：`discovery_service.py` 升级 `verify_pending_candidates`，加入候选人博文爬取和 LLM 文本分类调用，回写核验结论。
- 智能体层：`event_agent.py` 新增 `CandidateVerifyAgent` 及相关 Pydantic 契约模型。
- 展示层：`main.py` 优化 `list-candidates` 终端渲染。
