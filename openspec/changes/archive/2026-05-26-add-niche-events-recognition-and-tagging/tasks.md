## 1. 数据库存储演进与强契约值域防御

- [x] 1.1 在 `src/models/schemas.py` 中升级 `CosEvent` 强契约模型，新增 `event_type` 字段，默认值为 `"漫展"`，并添加类型注解与描述。确保绝不声明 `coser_name` 字段以防产生 LLM 幻觉。
- [x] 1.2 在 `src/models/db_models.py` 中升级数据库模型定义与建表 SQL 语句，为 `cosplay_events` 表与 `normalized_events` 表物理新增 `event_type` 字段（默认为 `'漫展'`），并物理内置 `CHECK (event_type IN ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'))` 约束防线。
- [x] 1.3 在 `src/services/db_service.py` 中编写健壮的数据库热升级检查，如果 `event_type` 字段在物理表中不存在，通过 `ALTER TABLE` 物理追加字段并设置默认值为 `'漫展'`。
- [x] 1.4 在 `src/services/db_service.py` 中编写嵌套的 `validate_type` 辅助值域断言函数，在执行任何活动入库与 Upsert 事务前强锁值域合法性，防止非标状态写入。

## 2. 智能体预检与提取 Prompt 动态模版升级

- [x] 2.1 升级首轮预检智能体（Triage Agent）的 `instructions` 指令，显式允许识别并放行一日店长、到店特邀模特、摄影会、快闪/签售等小众二次元日程（`has_event=True`）。
- [x] 2.2 升级 `config/templates/event_analysis.jinja2` 提取提示词模版，显式注入小众活动的提炼分类准则，并将一日店长（如罗森一日店长）作为典型 Few-shot 样例注入，指引大模型精准生成城市、名称并锁死高置信度分值（`>0.9`）。

## 3. 融合引擎小众活动智能旁路 (Bypass Engine)

- [x] 3.1 升级 `src/services/fusion_service.py` 的融合模块，在聚类合并与裁判判定最前置，拦截 `event_type != '漫展'` 的日程。
- [x] 3.2 针对小众日程（`event_type != '漫展'`），100% 旁路时空粗筛、`SequenceMatcher` 模糊度比对以及裁判智能体（Judge Agent），直接在 `normalized_events` 表中单独建立并持久化一个唯一的标准超级节点，且其超级节点的 `event_type` 与之严格一致。

## 4. 查询接口、CLI 看板与导出服务升级

- [x] 4.1 升级 `src/services/db_service.py` 的数据查询层，让 `get_event_centric_summary`、`get_all_events`、`get_normalized_events` 均支持可选的 `event_type` 物理筛选。特别地，日历排期查询 `get_normalized_events` 在未指定 `--type` 时，必须且 SHALL 默认仅返回 `'漫展'` 类型的超级节点以保持看板纯净。
- [x] 4.2 升级 `src/services/export_service.py` 中的导出服务，支持可选的 `event_type` 参数精细过滤，同时联动 calendar 视图，仅导出该类型的 Markdown / CSV 表格数据。
- [x] 4.3 升级 `src/main.py` 中的 Click 命令行入口，为 `summary`、`calendar` 和 `export` 子命令新增 `@click.option("--type", ...)` 参数，物理连通上述过滤逻辑。

## 5. 系统集成测试与质量保障验证

- [x] 5.1 编写 `tests/test_niche_events.py` 单元测试，验证一日店长等小众活动在 Triage 预检放行、Extractor 提取打标的完整链路正确性。
- [x] 5.2 编写融合引擎旁路测试，验证 `event_type != '漫展'` 时，SequenceMatcher 与裁判智能体被完全旁路，生成单独的超级节点。
- [x] 5.3 编写数据库层物理 CHECK 值域约束与 `validate_type` 应用层异常拦截测试，验证非标活动类型无法被持久化写入。
- [x] 5.4 验证全量 Click 命令行工具 `--type` 参数执行的流畅性，确保 pytest 测试套件 100% 绿灯通过。
