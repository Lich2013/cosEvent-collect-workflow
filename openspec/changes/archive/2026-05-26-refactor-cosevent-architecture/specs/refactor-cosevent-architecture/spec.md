## ADDED Requirements

### Requirement: 保留所有现有行为与契约
重构后的系统 MUST 完整保留所有的时空融合逻辑、大模型分析流程、命令行接口以及数据库完整性约束。

#### Scenario: 单元测试回归通过
- **WHEN** 在重构后在根目录运行 pytest 单元测试套件
- **THEN** 所有既存的单元测试用例均应一秒钟无损且成功通过
