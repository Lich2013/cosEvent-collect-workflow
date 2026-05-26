## 1. 数据库层级与物理建表升级

- [x] 1.1 新增并实现 `normalized_events` 表以及 `event_aliases` 表的 SQLite 物理建表逻辑 (`src/models/db_models.py` 与 `src/services/db_service.py`)
- [x] 1.2 升级 `cosplay_events` 表，安全增设外键 `normalized_event_id` 指向超级漫展节点，确保向后兼容

## 2. 核心时空融合引擎 (Temporal Fusion Engine) 研发

- [x] 2.1 研发启发式时空指纹聚类算法，实现基于 `difflib.SequenceMatcher` 的模糊名称相似度判定与同城 $\le 3$ 天的滑动时间窗粗筛
- [x] 2.2 实现 LLM 裁判智能体（Judge Agent）的调用与别名缓存逻辑，当相似度在中间态 $[0.5, 0.75)$ 时触发确权并写入 `event_aliases` 表
- [x] 2.3 编写外包络区间计算逻辑，确保 `normalized_events` 表的 `start_date` 与 `end_date` 总是关联日程的标准最大包络

## 3. 日程保存事务与级联融合集成

- [x] 3.1 改造 `save_extracted_events_transactional` 事务，在每次 AI 分析保存日程时，自动透明地运行融合算法对齐超级漫展 ID
- [x] 3.2 确保整个级联对齐、别名追加和 raw_posts 状态更新包裹在同一个原生 SQL 事务中，执行物理 `validate_status` 防御

## 4. 漫展集结看板与日历查询 CLI 实现

- [x] 4.1 扩展 CLI 命令行中的 `summary` 命令，新增并处理 `--by-event` 选项，以漫展为超级节点多层嵌套展示 Coser 集结详情
- [x] 4.2 开发 CLI 中的 `calendar` 命令，支持按城市 (`--city`) 和时域范围 (`--scope`) 精细过滤，格式化渲染月份嵌套展讯

## 5. 日历视图格式化数据导出开发

- [x] 5.1 升级 `export` 服务与 CLI 命令，增加可选参数 `--view` (Choice: `["default", "calendar"]`)
- [x] 5.2 实现 Markdown 等宽对齐表格的格式化导出渲染逻辑，支持重定向管道分流（stdout/stderr），保障 Windows Excel BOM 导出无乱码

## 6. 测试用例与全面功能验证

- [x] 6.1 编写单元测试验证智能时空聚类对 CP30/萤火虫等模糊漫展的自动归一化融合逻辑
- [x] 6.2 编写 CLI 命令测试，验证 `summary --by-event`、`calendar` 以及 `export --view calendar` 的数据展示、文件生成 and 标准重定向分流
