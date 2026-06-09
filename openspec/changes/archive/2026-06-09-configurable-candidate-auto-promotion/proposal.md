## Why

在目前的 Coser 发现与校验流程中，只要候选人通过了 LLM 判定或强特征词匹配，系统就会自动执行 `approve_candidate` 将其晋升至正式追踪库（`cosers` 表）。这使得用户无法依据个人审美、圈子契合度或质量标准进行人工筛选与把关。因此，系统需要支持可配置的自动审批开关，在关闭自动审批时，将核验通过的候选人保留在待审队列中，供用户手动核准决策。

## What Changes

- **新增配置项**：在 `config/settings.yaml` 和应用配置类 `Settings` 中新增 `auto_approve_candidates` 开关（默认为 `true` 保持向后兼容，用户可手动设为 `false`）。
- **流转逻辑调整**：
  - 当 `auto_approve_candidates` 为 `true` 时，继续执行原有的自动审批导入逻辑。
  - 当 `auto_approve_candidates` 为 `false` 时，强特征匹配或 LLM 判定通过后，仅将候选人的 `is_verified` 设为 `1` 并记录 `verify_reason`，但**不调用** `DBService.approve_candidate`，将候选人状态保持为 `'pending'` 留在待审核列表中。
- **命令行审核联动**：用户随时可以通过已有的 `coser list-candidates` 查看这些已通过核验（`is_verified=1`）但尚未导入的候选人，并通过 `approve-candidate` / `reject-candidate` 手动决策。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `coser-candidates`: 优化验证和流转规则，使其支持在验证通过后根据配置开关选择自动导入或保持 pending 等待手动审核。

## Impact

- **配置模块**：修改 `src/config.py` 和 `config/settings.yaml`，提供配置定义及解析逻辑。
- **发现服务**：修改 `src/services/discovery_service.py` 中的 `verify_pending_candidates`，在 `action == "approve"` 的处理分支中，根据 `settings.auto_approve_candidates` 的值来决定是否执行 `DBService.approve_candidate` 提拔操作。
- **测试用例**：需要为新配置的流转分支编写单元测试，确保关闭开关时不会自动导入，且可通过 CLI 手动批准。
