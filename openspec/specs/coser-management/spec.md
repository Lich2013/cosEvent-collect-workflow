# coser-management Specification

## Purpose
TBD - created by archiving change cosplay-event-workflow. Update Purpose after archive.
## Requirements
### Requirement: Coser 列表在 SQLite 中的持久化与表结构定义
系统必须在本地 SQLite 数据库中创建 `cosers` 数据表，用于持久化存储 Coser 实体和各社交平台的身份绑定。该表必须严格按照以下 SQL 定义建立：
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
Click 命令行工具必须提供统一的子命令入口 `cosevent coser`，其下支持 `add`, `list`, `update`, `delete` 四个子命令，以实现对 SQLite 数据库中 Coser 数据的完全管理：
- `add` 命令必须接受 `--name`, `--weibo`, `--bili`, `--xhs` 参数并执行数据插入。
- `list` 命令必须以格式化表格（如 Tabulate 风格）输出数据库中所有活跃及禁用的 Coser 及其绑定的各平台 UID。
- `update` 命令必须支持依据 `--name` 更新任意平台 UID，或修改启用状态（`--active 0/1`）。
- `delete` 命令必须支持依据 `--name` 从数据库中物理删除对应记录。
- 所有操作必须在终端给出直观的彩色提示日志。

#### Scenario: 使用命令行新增 Coser 并通过列表查询展示
- **WHEN** 用户在终端中执行命令 `cosevent coser add --name "测试Coser" --weibo "9125039159"` 成功后，再次执行 `cosevent coser list`
- **THEN** 命令行界面中能清晰展示包含 "测试Coser" 及其绑定的微博 UID "9125039159" 的格式化表格记录

