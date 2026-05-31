## Why

当前系统在处理非“漫展”小众日程（如“快闪/签售”、“一日店长”等）时采用了一刀切的 100% 旁路融合策略。这导致不同 Coser 在去往同一个大型展会的签售会（如“石家庄Mars EXPO签售”）或同一个罗森店店长活动时，由于旁路机制而生成了大量分裂且重复的历史超级节点。此外，系统也缺乏针对具体城市存量历史重复超级节点的一键式安全清洗和去重修复工具，导致前台看板冗余度高。

## What Changes

- **智能闸门小众日程融合（Gated Fusion）**：重构小众二次元日程的融合匹配逻辑，移除硬编码的一刀切旁路过滤。改为基于名称特征的智能闸门拦截——对于极简泛称（如“签售”、“店长”）保持旁路以防止泛指名词坍塌，而对于包含特定专有名词或足够长度的特定命名事件（如“石家庄Mars EXPO签售”、“明日方舟Only”）则放行进入 O(1) 通道和 fallback 融合匹配。
- **抗外键约束与防数据丢失的一键去重 CLI 模块**：在 CLI 中新增 `deduplicate` 指令，实现存量数据的被动自愈。当检测到相同城市、同名或同别名且时间相容的超级节点时，自动执行级联 `UPDATE` 重定向，并通过 `try-except sqlite3.IntegrityError` 防御外键约束冲突，以及在别名表冲突时输出 `[Spatial Rectification Audit]` 警告，以防别名映射关系静默丢失。

## Capabilities

### New Capabilities

### Modified Capabilities

- `niche-events-tagging`: 优化二次元小众日程的物理归一化存储与融合规则，将粗暴的一刀切旁路限制升级为智能闸门特征过滤与时空重定向合并。

## Impact

- **Affected Code**: `src/services/fusion_service.py` (时空闸门融合控制), `src/main.py` (新增去重 CLI 控制台命令), `tests/test_niche_events.py` (测试用例与测试契约调整)
- **New Code**: `src/services/db/dedup_service.py` 或 `src/services/db/event_repository.py` (增加一键物理去重数据原子事务层)
- **Dependencies**: 对已存的微博/B站定时分析和爬取流程完全向上兼容。
