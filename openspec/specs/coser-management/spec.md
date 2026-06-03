# coser-management Specification

## Purpose
TBD - created by archiving change cosplay-event-workflow. Update Purpose after archive.
## Requirements
### Requirement: Coser 列表在 SQLite 中的持久化与表结构定义
系统必须且 SHALL 在本地 SQLite 数据库中创建 `cosers` 数据表，用于持久化存储 Coser 实体和各社交平台的身份绑定。该表必须且 SHALL 严格按照以下 SQL 定义建立：
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT)
- `name` (TEXT, NOT NULL, UNIQUE)
- `weibo_uid` (TEXT, NULL)
- `bilibili_uid` (TEXT, NULL)
- `xhs_uid` (TEXT, NULL)
- `is_active` (INTEGER, DEFAULT 1)
- `created_at` (TEXT, DEFAULT CURRENT_TIMESTAMP)

#### Scenario: 成功创建数据库表结构并插入 Coser 记录
- **WHEN** 初始化数据库脚本执行时
- **THEN** 数据库中成功创建 `cosers` 表，且能够成功插入支持微博、B站、小红书 UID 的 Coser 记录

### Requirement: click 命令行管理工具提供增删改查 (CRUD) 接口
Click 命令行工具必须且 SHALL 提供统一的子命令入口 `cosevent coser`，其下支持 `add`, `list`, `update`, `delete` 四个子命令，以实现对 SQLite 数据库中 Coser 数据的完全管理：
- `add` 命令必须接受 `--name`, `--weibo`, `--bili`, `--xhs` 参数并执行数据插入。
- `list` 命令必须以格式化表格（如 Tabulate 风格）输出数据库中所有活跃及禁用的 Coser 及其绑定的各平台 UID。
- `update` 命令必须支持依据 `--name` 更新任意平台 UID，或修改启用状态（`--active 0/1`）。
- `delete` 命令必须支持依据 `--name` 从数据库中物理删除对应记录。
- 所有操作必须在终端给出直观的彩色提示日志。

#### Scenario: 使用命令行新增 Coser 并通过列表查询展示
- **WHEN** 用户在终端中执行命令 `cosevent coser add --name "测试Coser" --weibo "9125039159"` 成功后，再次执行 `cosevent coser list`
- **THEN** 命令行界面中能清晰展示包含 "测试Coser" 及其绑定的微博 UID "9125039159" 的格式化表格记录

### Requirement: Coser 新增与更新时的名字相似度及平台 UID 占用校验与警示
系统在执行新增（add）或修改（update）Coser 时，必须且 SHALL 支持名字相似度与各平台 UID 占用冲突的前置校验：
1. **新增时名字相似度校验**：仅在新增 Coser 时执行姓名模糊碰撞比对。系统从库中提取已有 Coser 姓名列表，通过归一化（去除符号并转小写）、长短子串包含（较短方长度 $\ge 2$）或 `difflib` 相似度评分（$\ge 0.7$）判定。若发现相似，在返回数据中抛出警告。更新 Coser 属性时不执行此比对。
2. **多平台 UID 精准占用校验**：对于输入的不为空（忽略 `None`、`""`、`"-"`）的微博、B站、小红书 UID，系统必须且 SHALL 对输入类型及字符串边界做清洗（`str(uid).strip()`），并利用数据库自带的 `TRIM()` 过滤比对。若已被其他既存记录绑定，在返回数据中抛出冲突警告。
3. **表现层与数据层解耦**：Repository 层的校验逻辑必须且 SHALL 保持纯净，将警告内容作为 `list[str]` 返回，不强依赖 `click` 命令行库。CLI 控制器获取警告列表后，使用 `click.secho(..., err=True)` 将警告高亮输出到系统的标准错误流（stderr）中以避免污染标准输出。
4. **非阻断策略**：校验逻辑仅作为录入提醒，系统绝对禁止因相似警告或 UID 冲突警告而中断或拒绝新增或更新实体入库事务的操作。

#### Scenario: 成功检测到相似名字和 UID 冲突并在 stderr 输出警告但完成注册
- **WHEN** 库中已存在 Coser "桃景三酪"（bilibili_uid="11286045"），用户在命令行执行新增 Coser "桃景三酪_" 且 B站 UID 填为 " 11286045 " 时
- **THEN** 系统的 stderr 管道 SHALL 成功输出相似名称警告与 B站 UID 被 "桃景三酪" 占用的冲突警告，但该新 Coser 依然成功完成注册入库

