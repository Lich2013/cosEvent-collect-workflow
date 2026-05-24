## Context

在共识分析机制中，并行提取器（Parallel Extractors）在 `Runner.run` 执行后，会返回各自的候选列表并被序列化。现有的流控制逻辑在提取完后，即使所有成功运行的提取器的候选活动列表全部为空，依然会强行唤醒并调用金牌裁判智能体。

这造成了不必要的 API 费用损耗以及网络时延。我们需要在并行提取结果汇总过滤完毕后，加入一段自适应零值判断与裁判旁路退出逻辑。

## Goals / Non-Goals

**Goals:**
- **自适应旁路判定**：成功提取并序列化 `valid_outputs` 之后，累加所有提取器候选活动总数。若总数为 `0`，则直接绕过终审裁判（Judge Agent）的调用，安全且快速返回空列表。
- **与分歧仲裁隔离**：如果至少有一个提取器提取出了活动，系统仍旧照常唤醒高智商裁判智能体进行核验、模糊去重和合并。
- **高覆盖测试验证**：新增 Mock 单元测试，拦截大模型流程，验证旁路状态下裁判的调用次数为 0。

**Non-Goals:**
- **不更改智能体的 Pydantic 最终契约定义**（`FinalOutput` 等不变）。
- **不对单模型模式（Single Mode）和预检过滤模式（Triage）做其他破坏性修改**。

## Decisions

### 核心决策：在 `event_agent.py` 的提取后过滤块中注入旁路退出分支

我们在 `src/agents/event_agent.py` 的并行提取结果处理中注入旁路判定：
```python
        # 1. 过滤并收集正常输出的候选
        valid_outputs = []
        for i, res in enumerate(candidate_results):
            ...
            elif res and hasattr(res, "event_list"):
                serialized = [event.model_dump() for event in res.event_list]
                valid_outputs.append({
                    "provider": prov,
                    "model": mod,
                    "event_list": serialized
                })
        
        if not valid_outputs:
            raise ValueError("所有并行提取器皆运行失败，提取主任务异常。")

        # 【核心重构：零值自适应旁路】
        total_extracted_candidates = sum(len(out["event_list"]) for out in valid_outputs)
        if total_extracted_candidates == 0:
            print("\x1b[1;32m[Agent] 所有存活的提取器提取的候选活动数皆为空，免除终审裁判二次仲裁，直接安全退出。\x1b[0m")
            return []
            
        if len(valid_outputs) == 1:
            ...
```

#### 决策优势：
- *极低延迟与资费优化*：由于完全绕过了最昂贵的裁判智能体调用，当分析日常废博文时（例如预检发生了微弱的误判抖动进入了分析，但提取器全部返回空），系统能在这个切面上实现 **100% 的裁判大模型降费**。
- *完全不改变分歧处理逻辑*：当提取器 1 提取到 2 个活动，提取器 2 提取到 0 个活动时，`total_extracted_candidates == 2 > 0`，逻辑完美跳过该旁路分支，照常流向下方的裁判仲裁块，完全维护了系统在分歧状态下的极高安全与去重准确性。

## Risks / Trade-offs

- **[Risk] 并行提取器返回空由于脏数据或 ValidationError 引发了异常而不是合规的 event_list** → **Mitigation**: 异常已经在 `isinstance(res, Exception)` 中被优雅拦截捕捉并记录 WARNING 日志，只有正常提取成功且返回 `event_list` 为空的提取器才会被计入 `total_extracted_candidates` 统计，因此旁路判定非常严密和安全。
