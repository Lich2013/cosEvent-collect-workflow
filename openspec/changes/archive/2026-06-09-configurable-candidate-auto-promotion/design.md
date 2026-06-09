# Technical Design: Configurable Candidate Auto-Promotion

## Context

在目前的 Coser 发现与校验流程中，当候选人通过了强特征匹配（Bio 关键词）或弱特征抓取后的 LLM 判定时，系统在验证环节会自动调用 `DBService.approve_candidate` 将其晋升至正式追踪库（`cosers` 表），并物理删除临时博文。

为了让用户能依据个人审美或特定标准进行人工筛选与把关，系统需要支持可配置的自动审批开关。当该开关关闭时，核验通过的候选人只更新其已核验状态与理由，但保留在 pending 列表中，等待用户通过 CLI 手动批准或拒绝。

## Goals / Non-Goals

**Goals:**
- 在配置文件中引入自动审批控制开关 `auto_approve_candidates`，默认为 `true` 以保持向下兼容。
- 当 `auto_approve_candidates = false` 时，核验通过的候选人其 `is_verified` 设为 `1` 并记录 `verify_reason`，但**不**自动提升至 `cosers` 列表，状态保持为 `'pending'` 留在待审核队列中。
- 用户能通过已有的 `coser list-candidates` 和 `approve-candidate` 命令来查看并手动审批这些已通过 LLM 验证的候选人。
- 保证整个候选人发现与验证链路的其他状态（如 `ignored`、`undetermined`）及物理隔离规则不受影响。

**Non-Goals:**
- 本次修改不涉及为候选人设计新的 Web GUI，仍通过现有 click CLI 界面及 repository 数据流提供服务。
- 不修改底层 SQLite 的 `coser_candidates` 和 `cosers` 关系，亦不需要变更已有的表结构 schema。

## Decisions

### 1. 配置项设计与解析位置
我们将在 `config/settings.yaml` 中新增全局变量 `auto_approve_candidates: true/false`，并在 `src/config.py` 中的 `Settings` 类中解析该配置，默认值为 `true`。

- **选择方案**：在 `Settings.__init__` 读取 `yaml` 文件并赋给 `self.auto_approve_candidates`，如果 yaml 中没有配置该项，则使用默认值 `True`。
- **替代方案**：直接在 `discovery_service.py` 内部读取环境变量。但这违背了系统内统一使用 `src.config.settings` 集中管理全局参数的架构设计。

### 2. 状态流转拦截逻辑
修改 `src/services/discovery_service.py` 中的 `verify_pending_candidates` 内部的 `action == "approve"` 分支。
- **选择方案**：
  ```python
  if success:
      if settings.auto_approve_candidates:
          # 自动核验自动通过 (Auto-Promotion) 并物理清理临时博文
          DBService.approve_candidate(cand_id)
          newly_verified += 1
          bili_info = f" -> B站(UID: {bili_uid})" if bili_uid else ""
          weibo_info = f" -> 微博(UID: {weibo_uid})" if weibo_uid else ""
          print(f"\x1b[1;32m[Discovery] ✓ 成功自动验证并批准候选人 [{name}]{bili_info}{weibo_info} | 原因: {verify_reason} | 置信度: {candidate_bili_scores.get(cand_id, 0.0):.1f}\x1b[0m")
      else:
          # 仅保留已核验状态，等待手动审核
          newly_verified += 1 # 依然统计为新核验过的人数，或者作为本次成功处理的记录
          bili_info = f" -> B站(UID: {bili_uid})" if bili_uid else ""
          weibo_info = f" -> 微博(UID: {weibo_uid})" if weibo_uid else ""
          print(f"\x1b[1;32m[Discovery] ✓ 成功核验候选人 [{name}]{bili_info}{weibo_info}，已记录核验状态与理由，待手动审批导入。\x1b[0m")
  ```
- **Rationale**：由于 `DBService.add_candidate` 能够正确把 `is_verified` 设为 `1` 并记录 `verify_reason`（在 `coser_candidates` 中更新对应记录的字段），当不调用 `DBService.approve_candidate` 时，该候选人在 `coser_candidates` 表中依然是 `status = 'pending'`，且 `is_verified = 1`。这完美契合了 pending 待手动审核状态。
- **注意点**：当 `auto_approve_candidates` 为 `false` 且核验通过时，我们**不应该**物理清理临时博文数据（因为用户在手动批准或拒绝时可能还需要查看他们的数据，或者根据 `approve_candidate` 内的清理逻辑——即只有在真正执行 `approve` 或 `reject` 物理变更状态时，才去物理清理）。目前的 `CandidateRepository.approve_candidate` 和 `reject_candidate` 都有物理清理 `candidate_raw_posts` 的逻辑。所以在 `verify_pending_candidates` 阶段只执行 `add_candidate` 写入核验状态而不提升时，不主动清理博文，非常符合逻辑。

## Risks / Trade-offs

- [Risk]：当候选人由于关闭自动导入而保持 `is_verified = 1` 且 `status = 'pending'` 时，下一轮的 `verify_pending_candidates` 扫描是否会重复处理他们？
  - **Mitigation**：分析 `DiscoveryService.verify_pending_candidates` 开头的 SQL 语句：
    ```sql
    SELECT id, name, source_ref, platform, matched_bili_uid, matched_weibo_uid, status, status_updated_at
    FROM coser_candidates 
    WHERE (status = 'pending' AND is_verified = 0) OR ...
    ```
    因为已核验的候选人的 `is_verified` 已变为 `1`，所以他们**不会**再被 `(status = 'pending' AND is_verified = 0)` 匹配到，从而完美避免了重复抓取和重复核验的性能与 API 浪费。
- [Risk]：如果在关闭自动批准的情况下，候选人被用户通过 `coser reject-candidate` 拒绝，其博文是否被清理？
  - **Mitigation**：是的，`CandidateRepository.reject_candidate` 中包含对 `candidate_raw_posts` 的物理清理，流转一致。
