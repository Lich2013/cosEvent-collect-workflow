## Why

随着追踪的 Coser 数量逐渐增长（当前已超过 100 位），在通过命令行 `cosevent coser add` 或 `update` 添加/修改 Coser 时，用户极易面临以下问题：
1. **名字拼写细微不一致**：同一个 Coser 在不同平台名字可能多出下划线或后缀（如 "杜杜Dolly_" 与 "杜杜Dolly"），导致用户误以为其未录入，从而重复添加了新的同人记录。
2. **多平台凭证冲突/错配**：用户在录入 UIDs 时，可能将其他 Coser 已拥有的 UID 错误绑定到新 Coser 身旁，或者重复录入同一账号，造成网络去重失败与数据库 `UNIQUE` 博文索引物理冲突。

本变更旨在引入轻量、不阻断的**实体碰撞与凭证冲突双重警告校验机制**，提升录入体验并确保数据一致性。

## What Changes

- **Coser 名字相似度模糊碰撞报警**：在添加或重命名 Coser 前，系统必须且 SHALL 计算输入昵称与库中所有既存 Coser 名字的相似度（基于归一化比对、子串包含判定及 Levenshtein 比对），若匹配度高，在控制台输出醒目的黄色 `Warning`。
- **平台 UID 占用冲突检测与警报**：在添加或修改 Coser 凭证前，系统必须且 SHALL 校验即将绑定的 `weibo_uid`、`bilibili_uid`、`xhs_uid`（不包含 `-` 或空字符串等占位符）是否已被其他 Coser 记录占用；若被占用，必须且 SHALL 在控制台打印黄色 `Warning` 占用详情，但不强制中断操作。
- **CRUD 控制台交互输出增强**：在 `add` 与 `update` 执行完毕后，警告内容必须且 SHALL 以醒目的黄色警告标色渲染，提升终端人机感知体验。

## Capabilities

### New Capabilities

*(无)*

### Modified Capabilities

- `coser-management`: 增加新增与更新 Coser 实体的名字相似度、UID 重用冲突模糊检测及非阻断警示日志的规范约束。

## Impact

- **Coser Repository** (`src/services/db/coser_repository.py`): 增加 UID 占用冲突查询方法（或在逻辑层统一实现）。
- **Click CLI Controller** (`src/main.py`): 在 `add_coser` 和 `update_coser` 方法中接入校验流程，控制台友好输出警告，确保零兼容性破坏。
