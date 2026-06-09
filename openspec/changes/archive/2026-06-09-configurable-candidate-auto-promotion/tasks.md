## 1. 配置管理调整

- [x] 1.1 在 `config/settings.yaml` 中新增配置项 `auto_approve_candidates: true`
- [x] 1.2 在 `src/config.py` 的 `Settings` 类中加载并解析 `auto_approve_candidates`，默认值为 `True`

## 2. 状态流转逻辑拦截

- [x] 2.1 修改 `src/services/discovery_service.py` 中的 `verify_pending_candidates`，在 `action == "approve"` 分支处，根据 `settings.auto_approve_candidates` 配置拦截审批流程
- [x] 2.2 当关闭自动审批且验证通过时，只保留 `is_verified=1` 并在 `verify_reason` 记录理由，不自动调用 `approve_candidate` 提拔候选人到正式库

## 3. 单元测试与验证

- [x] 3.1 编写单元测试验证 `auto_approve_candidates` 配置为 `True` 时的正常自动提拔行为
- [x] 3.2 编写单元测试验证 `auto_approve_candidates` 配置为 `False` 时的保留待审核行为
