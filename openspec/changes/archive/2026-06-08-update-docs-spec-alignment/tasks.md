## 1. 更新 AGENTS.md 规范

- [x] 1.1 更新 AGENTS.md 中的 Pydantic Schema 示例，为 `CosEvent` 补充 `event_type` 字段，并新增 `FusionJudgeOutput` 与 `CandidateVerifyOutput` 的契约声明
- [x] 1.2 更新 AGENTS.md 提示词模板列表，补充 `event_consensus_judge.jinja2` 等全部四个 Jinja2 模板
- [x] 1.3 更新 AGENTS.md 中的容错与降级机制，写入 `is_analyzed = 2` 的三态状态机硬熔断机制、`BEGIN IMMEDIATE` 强事务锁规约及 `validate_type` 值域断言
- [x] 1.4 新增 AGENTS.md 的第 6 节，阐述候选人自动核验流程（Bio强词、LLM核验、undetermined 待定冷却期流转规则）

## 2. 更新 README.md 主项目文档

- [x] 2.1 更新 README.md 中的系统整体架构与数据流图解，补充 Bio 虚拟推文合成与 B站 Card API 补爬、网页超时自愈和 gRPC 凭证自愈刷新细节
- [x] 2.2 更新 README.md 中聚类引擎与物化视图小结，将 100% 旁路更正为 Gated Bypass，并补充时空纠偏、物化冷热分区与 MD5 确定性 ID 细节
- [x] 2.3 更新 README.md 的 CLI 命令说明，补齐 `export --view`、`sync-bili` 的 WAF 降级与免检通道、`Candidates` 的自动核验命令行描述

## 3. 验证与回归测试

- [x] 3.1 检查 README.md 与 AGENTS.md 排版及 Markdown 链接可访问性
- [x] 3.2 运行本地 pytest 单元测试套件，确认全量测试用例 100% 通过且无回归异常
