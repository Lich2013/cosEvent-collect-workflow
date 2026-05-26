## Context

当前系统在面对二次元小众线下日程（如一日店长、受邀到店模特、粉丝摄影会）时，由于提取指令和初筛分流规则强行聚焦在大型漫展和嘉宾出行上，很容易造成漏报或预检误杀。此外，系统缺乏对活动类型的打标机制，导致数据消费层无法分流筛选小众日程。

本设计旨在升级智能体提取边界，在数据库物理层引入 `event_type` 分类硬核防御，并在融合引擎中开发自适应类型旁路，实现二次元小众活动日程的智能打标与分类看板导出检索。

## Goals / Non-Goals

**Goals:**
- **智能体提取扩容**：微调首轮 Triage 智能体说明；升级 `event_analysis.jinja2` 提取提示词，增加一日店长、摄影会等小众活动提炼细则与 Few-shot 样例，锁定置信度得分下限。
- **物理表演进与防御**：物理升级 `cosplay_events` 数据表，新增 `event_type` 字段，物理在数据库级和 Python 校验级强锁值域为 `('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售')`。对老数据默认以 `'漫展'` 补全以向后兼容。
- **融合引擎前置旁路**：在 `EventFusionService` 融合算法最前置增加类型拦截，对于非 `'漫展'` 类型的小众活动直接独立建超级节点，100% 旁路模糊聚类与 LLM 裁判。
- **看板及导出精筛分流**：扩展 `calendar` 命令、`summary` 命令和 `export` 日历视图导出服务，支持可选参数 `--type` 进行物理类型精筛。

**Non-Goals:**
- 不主动去罗森等连锁便利店或女仆咖啡店官网爬取一日店长活动（完全基于 Coser 排班反向提炼）。
- 不破坏向后兼容性，保持原有的 Scraper 数据结构与 analyze 数据流生命周期不变。

## Decisions

### Decision 1: 首轮 Triage 初筛指令与 Extractor Prompt 物理微调
为了最大化减少小众高价值活动在流水线首尾的损耗，执行以下微调：
- **Triage 扩容**：Triage instructions 将“一日店长、到店模特、摄影会、私设会”明文声明为有效行程意图，确保 `has_event=True` 秒速放行。
- **Few-Shot 注入**：在 `event_analysis.jinja2` 模板中追加“一日店长（罗森联动）”典型样本，指引大模型根据“沪”等字规整出城市，并将置信度评分强制判定为 `>0.9` 锁死，防范日常宣传误杀。

### Decision 2: 融合引擎的小众活动智能旁路 (Bypass Mechanism)
在 `EventFusionService.find_or_create_normalized_event` 入口首行，前置拦截判断：
- 设日程的分类为 `event_type`。若 `event_type != '漫展'`（即为一日店长、摄影会等）：
  - 系统**100% 旁路**滑动时间窗粗筛、`SequenceMatcher` 模糊相似度比对以及 `run_fusion_judge_agent` 金牌裁判确权。
  - 直接在数据库中为此活动创建唯一的 `normalized_events` 超级节点，以防它们由于同名或相近时间被算法误判归入普通漫展节点，保障漫展指纹库的纯净。

### Decision 3: 数据库级与应用级分类值域硬核双重防御 (Double State Defense)
为了贯彻 `AGENTS.md` 的软件状态机值域防线：
- 数据库建表与热升级检查物理在 `cosplay_events` 新增 `event_type`：
  ```sql
  event_type TEXT DEFAULT '漫展' CHECK (event_type IN ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'))
  ```
- 应用层在 `db_service.py` 嵌套辅助函数中定义 `validate_type`：
  ```python
  def validate_type(type_val: str):
      assert type_val in ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'), f"Event Type '{type_val}' is invalid!"
  ```
  在物理写入和 Upsert 前进行断言截断，防止非标状态写入。

---

## Risks / Trade-offs

### Risk 1: 小众活动在老数据中没有 `event_type` 字段
- **Description**: 数据库热升级追加 `event_type` 后，历史存量日程此字段会变为空，可能导致查询报错。
- **Mitigation**: 在热升级语句中指定 `DEFAULT '漫展'` 约束，在热迁移完毕后自动将存量数据补齐为 `'漫展'`，完全杜绝空值引起的系统异常。

### Risk 2: 用户只想在 calendar 看板中纯净展示大型漫展
- **Description**: 引入一日店长后，纯漫展排期看板中可能会混入很多小众咖啡店活动，导致阅读体验变差。
- **Mitigation**: CLI `cosevent calendar` 与 `summary --by-event` 默认支持并强化 `--type` 筛选。默认展示时只显示 `'漫展'` 类型日程，若想看一日店长，指定 `--type 一日店长` 即可，做到了完美的视觉分流。
