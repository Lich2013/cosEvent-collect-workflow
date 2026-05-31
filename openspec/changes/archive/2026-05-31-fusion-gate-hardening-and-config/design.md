## Context

在智能二次元小众日程融合阶段，非漫展小众活动（如一日店长、签售等）包含极强的泛指属性。为了防止极简名称（如“一日店长”）在同一城市不同时间/不同地点发生大范围坍塌错误，系统在 `EventFusionService` 中引入了智能旁路闸门（Gated Fusion）。
但当前旁路闸门的设计存在两个关键技术缺陷：
1. `BYPASS_GENERIC_NAMES` 集合硬编码在代码中，不易动态更新。
2. 城市前缀剔除不彻底，对于“上海一日店长”等带有城市前缀但核心名词依然为极简泛指的场景，容易绕过闸门发生坍塌合并。

## Goals / Non-Goals

**Goals:**
- 将极简泛称黑名单迁移为配置项，实现在 `config/settings.yaml` 中配置并动态读取。
- 引入前缀过滤与智能前缀断言机制，完美识别具有地级市前缀的极简泛称（如“上海一日店长”、“北京摄影会”），强制进行 100% 旁路隔离以规避坍塌。
- 确保专有品牌名称小众活动（如“罗森一日店长”、“罗森店长”）以及带城市前缀的具体品牌活动（如“上海罗森一日店长”）仍能正确放行。

**Non-Goals:**
- 对除 `EventFusionService` 旁路判断外的常规 O(1) 秒配与 Similarity 聚类机制进行算法变更。
- 修改底层 SQLite 数据表物理结构。

## Decisions

### 1. 配置项动态化
在 `Settings` 类中新增 `bypass_generic_names` 属性（默认值与原硬编码黑名单一致），并在 `config/settings.yaml` 中开放配置：
```yaml
# ==============================================================================
# Fusion Bypass Generic Names List
# ==============================================================================
bypass_generic_names:
  - "签售"
  - "一日店长"
  - "店长"
  - "摄影会"
  - "受邀模特"
  - "快闪"
  - "签售会"
```
代码中统一通过单例 `settings.bypass_generic_names` 动态读取，实现配置热隔离。

### 2. 城市前缀剥离与精确边界判定算法
在旁路闸门判断中，新增地级市前缀检测与基础词分离逻辑：
```python
# 1. 检测并剔除地级市名前缀，提取 base_slug
base_slug = name_slug
for city in MAJOR_CITIES_COMBINED:
    if name_slug.startswith(city.lower()):
        base_slug = name_slug[len(city):]
        break

# 2. 获取配置的黑名单并判定
bypass_list = set(settings.bypass_generic_names)

if base_slug in bypass_list:
    is_bypass = True
else:
    # 针对极简泛词的降级过滤，如“摄影会”
    no_city_name = not any(city in name_slug for city in MAJOR_CITIES_COMBINED)
    is_bypass = (len(name_slug) <= 3 and no_city_name)
```
* **对比分析**：
  * **上海一日店长**：剥离“上海”前缀后，基础词 `base_slug` 为“一日店长”，命中 `bypass_list` $\to$ 触发旁路隔离（符合预期）。
  * **罗森一日店长**：无城市前缀，基础词为“罗森一日店长”，未命中 `bypass_list`，长度为6 $\to$ 放行常规合并（符合预期）。
  * **上海罗森一日店长**：剥离“上海”前缀后，基础词为“罗森一日店长”，未命中 `bypass_list`，长度为8 $\to$ 放行常规合并（符合预期）。

## Risks / Trade-offs

* **[Risk]** $\to$ 城市前缀如果与其他正常品牌名冲突（例如拼音或汉字前缀被误切）
* **[Mitigation]** $\to$ `MAJOR_CITIES_COMBINED` 均包含完整地级市名（如“上海”、“北京”），其命名极为特殊且只在 `name_slug` 头部严格进行 `startswith` 判定，不会发生中途误切。
