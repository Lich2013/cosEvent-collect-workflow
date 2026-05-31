## Context

当前系统由 `EventFusionService` 负责超级归一化漫展节点的维护与日程绑定。然而，先前为了应对二次元小众日程打标而引入的“非漫展小众日程直接 100% 旁路时空合并与裁判引擎”策略存在严重缺陷：
1. **小众日程重复建档**：如果不同 Coser 去往同一个特定命名的小众活动（如“石家庄Mars EXPO签售”、“Nikke罗森一日店长”），因为其分类属于“快闪/签售”或“一日店长”，系统会 100% 旁路合并流程并直接插入全新超级节点，生成了大量分裂行。
2. **存量数据冗余无清洗途径**：历史多次抓取产生的具体城市下的冗余分裂超级节点，目前缺少一键式的安全事务级去重修复工具，只能任其存在。

## Goals / Non-Goals

**Goals:**
- **小众日程智能闸门化融合**：重构小众日程的旁路控制。仅对极简的泛称活动（如“签售”、“店长”等）保持旁路以防止坍塌；而对于包含特定品牌、展会名等专有名词的具体小众日程（如“明日方舟Only”、“罗森一日店长”、“罗森店长”），允许进入常规的时空融合管道进行秒配和归一化合并。
- **一键式去重 CLI 修复指令**：开发 `deduplicate` CLI 运维指令，可安全合并数据库中现存的冗余重复活动节点，并进行完整的级联重定向及外键防崩溃熔断防御。
- **别名映射完整性追溯审计**：在合并 alias 别名时，如果发生 UNIQUE 约束冲突，不进行静默抹除，而是输出带有源-宿 ID 链路的可观测审计日志。

**Non-Goals:**
- 修改已有的 SQLite 表 Schema 结构。
- 修改 Extractor 智能体的日程提取及 `event_type` 物理打标机制（继续尊重小众日程的打标结果，只重构时空融合层的合并决策）。

## Decisions

### 1. 基于名称特征过滤的智能旁路闸门（Gated Bypass）
- **方案选择**：在 `fusion_service.py` 头部，针对 `event_type != "漫展"` 的小众日程，添加名称过滤闸门：
  - 定义泛指名词黑名单：`BYPASS_GENERIC_NAMES = {"签售", "一日店长", "店长", "摄影会", "受邀模特", "快闪", "签售会"}`。
  - **收紧长度判定阈值**：当且仅当 `name_slug` 在黑名单中，或者 `len(name_slug) <= 3` 且不包含任何主要展览地级市名时，才允许 100% 旁路；
  - 否则，一律放行进入常规时空融合引擎，享有 O(1) 通道和 fallback 时间窗口判定。这确保了包含品牌词的 4 字小众日程（如 `"罗森店长"`）能安全通过闸门并被正常合并。
- **对比与权衡**：
  - *全量融合*：彻底抹除旁路。会产生把 Coser A 的极简“签售”与 Coser B 位于不同店面的极简“签售”错误坍塌到一起的污染。
  - *特征闸门（本方案）*：既保留了泛指活动的安全防坍塌边界，又使特定命名活动（如“石家庄Mars EXPO签售”）以及 len=4 的边界活动（如“罗森店长”）得以放行重聚，最为理想。

### 2. 共享工具化重构：`clean_event_name` 抽离至公共解析层
- **方案选择**：为了规避 `dedup_service.py` 与 `EventFusionService` 之间产生循环交叉依赖，我们将原 `EventFusionService._clean_name` 物理剥离至公共工具模块 `src/utils/parsers.py` 中，并重命名为 `clean_event_name(name)`。
- **理由**：`parsers.py` 作为纯净的叶子节点函数集，没有任何上游依赖，去重服务与时空融合引擎均能无锁式安全调用，分层职责极其清晰。

### 3. 抗外键级联冲突一键去重 CLI 模块
- **方案选择**：在 `src/services/db/dedup_service.py` 中实现一键物理去重原子服务 `DeduplicationService.deduplicate_database`，并在 `src/main.py` 注册 `deduplicate` CLI 控制台指令。
- **去重 `date_window` 设定**：去重比对时的时间相容窗口严格与 O(1) 快速秒配通道的 **`±7 天`** 对齐，保障清洗工具与主流程在去重边界判定上的一致性。
- **数据清洗规则**：
  1. 按照 `[city, name_slug, date_window (±7天)]` 查找 `normalized_events` 中的重复节点。
  2. 选定 ID 最小的为“保留者（Winner）”，其余为“合并者（Loser）”。
  3. 在同一个原子 SQL 事务中执行 `UPDATE cosplay_events SET normalized_event_id = Winner.id WHERE normalized_event_id = Loser.id;` 重定向日程。
  4. 级联重定向别名：
     - 查询 Loser 关联的所有别名，尝试更新其 `normalized_event_id = Winner.id`。
     - 若触发别名表 `UNIQUE(alias_name, city)` 主键冲突，捕获冲突并检查其映射。输出 `[Spatial Rectification Audit]` 审计日志，并 `DELETE` 冲突的 Loser 别名行以完成合并。
  5. 级联删除 Loser 节点：使用 `try-except sqlite3.IntegrityError` 进行健壮包裹，若抛出异常则自动跳过物理删除，确保横向可扩展性。

## Risks / Trade-offs

- **[Risk 1] 泛指词语（如“漫展签售会”）字数大于4被误融合**
  - **Mitigation**：设置白名单以及精确清洗规则，且融合本身受 ±3 天至 ±7 天的时间窗口强约束，即使误融合，影响范围也被限缩在极小的同城档期内。
- **[Risk 2] 存量去重由于涉及大量级联 UPDATE，可能会在非事务环境下发生崩溃残留**
  - **Mitigation**：去重模块的所有数据库数据库写操作必须且 SHALL 包裹在同一个 `conn.transaction`（同一个 SQLite 原子事务）中执行，若发生任何异常，物理 `ROLLBACK`，保障数据原子性。
