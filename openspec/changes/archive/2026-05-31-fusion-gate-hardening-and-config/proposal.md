## Why

在当前系统运行过程中，智能二次元小众日程融合引擎（`EventFusionService`）中的极简泛称旁路闸门（Gated Fusion）在特征判定和配置上存在两处严重的架构和业务缺陷：
1. **黑名单硬编码**：极简泛指黑名单（`BYPASS_GENERIC_NAMES`）以 Python Set 形式直接硬编码在代码中，管理员在实际运维中无法通过 `settings.yaml` 配置文件动态扩充，维护灵活性低。
2. **子串检测误伤**：在小众旁路检测中，对于地级市前缀检测采用的是简单的子串包含检查（如 `any(city in name_slug ...)`）。当名称为“上海一日店长”时，因其包含“上海”导致被判定为“包含地级市名”，从而绕过旁路闸门进入常规时空融合通道。这将导致同城同天不同门店的极简“上海一日店长”排班发生错误塌陷与重定向合并，产生脏数据。

本提案通过将小众旁路名单动态配置化，并加固闸门判定算法以实现正则边界安全隔离，彻底解决上述问题。

## What Changes

- **配置动态化**：在 `settings.yaml` 中新增 `fusion.bypass_generic_names` 数组配置，支持管理员动态维护小众泛称黑名单；代码启动时动态热加载并加载此配置列表。
- **闸门算法加固**：重构 `fusion_service.py` 内部的小众日程旁路过滤判定，弃用不安全的 `any(city in name_slug ...)` 子串检测，改为基于正则匹配的精确边界提取：只有包含非地级市名称的专有名词品牌（如“罗森一日店长”）才会被放行，而对于“北京一日店长”、“一日店长”等泛指词或带城市前缀的极简泛指词，将强制精准拦截并触发旁路（Bypass）生成独立节点，防范合并塌陷。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `event-normalization-deduplication`: 加固小众日程融合的闸门防塌陷判定算法，并将黑名单规则动态迁移至统一配置文件中。

## Impact

- **Affected Files**:
  - `src/services/fusion_service.py`: 闸门过滤逻辑重构与配置读取。
  - `src/config.py`: 配置对象读取。
  - `config/settings.yaml` / `config/settings.example.yaml`: 添加新配置项。
- **Dependencies**: 无新增第三方库依赖。
- **Compatibility**: 100% 向后兼容，存量数据库结构无须变更。
