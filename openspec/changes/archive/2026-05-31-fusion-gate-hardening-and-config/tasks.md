## 1. 配置项动态化改造与解析集成

- [x] 1.1 在 `config/settings.yaml` 与 `config/settings.example.yaml` 中新增 `bypass_generic_names` 数组配置，并同步添加相关注释文档。
- [x] 1.2 重构 `src/config.py` 中的 `Settings` 类：在 `__init__` 中新增 `self.bypass_generic_names` 字段默认值，并在配置加载 block 中添加对 `bypass_generic_names` 配置项的安全解析及赋值逻辑。

## 2. 融合智能闸门过滤算法加固

- [x] 2.1 修改 `src/services/fusion_service.py`：动态读取 `settings.bypass_generic_names` 替换原硬编码的 `BYPASS_GENERIC_NAMES` 集合声明。
- [x] 2.2 重构 `EventFusionService.find_or_create_normalized_event` 内的小众日程旁路过滤拦截逻辑，实现精确的城市前缀检测与基础词分离剥离匹配算法。

## 3. 单元测试更新与回归验证

- [x] 3.1 在 `tests/test_niche_events.py` 中，编写针对城市前缀旁路拦截（如“上海一日店长”被隔离，而“上海罗森一日店长”被放行）的专用测试断言。
- [x] 3.2 运行全量 `.venv/bin/pytest tests/` 回归测试套件，验证新智能闸门过滤和配置加载的完整性与安全性，确保 100% 绿色通过。

