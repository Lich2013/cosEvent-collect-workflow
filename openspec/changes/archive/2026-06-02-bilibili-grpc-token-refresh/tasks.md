## 1. 基础环境与配置支撑

- [x] 1.1 修改 `.env` 添加并配置注释占位符 `BILIBILI_REFRESH_TOKEN`
- [x] 1.2 修改 `config/settings.yaml.example` 和 `config/settings.yaml` 增加 `refresh_token` 支持
- [x] 1.3 修改 `src/config.py` 增加 `bilibili_grpc_refresh_token` 加载与插值注入支持

## 2. B站移动端 App 扫码登录脚本重构

- [x] 2.1 修改 `scripts/bili_app_qr_login.py` 控制台输出以包含 `refresh_token` 配置指引
- [x] 2.2 增加交互式一键保存功能，并在用户确认后，使用多行正则自动写入/更新项目物理 `.env` 文件

## 3. B站 Scraper 自动刷新与自愈重试逻辑实现

- [x] 3.1 在 `src/tools/bilibili_scraper.py` 中定义 `APP_CREDENTIALS` 静态常量映射表
- [x] 3.2 增加 `_is_bili_grpc_auth_error` 辅助方法：精准判定 gRPC 异常是否为鉴权失效/Token过期
- [x] 3.3 增加 `refresh_bilibili_grpc_token` 异步方法：调用刷新 API 获取新 Token 并更新 settings 内存值
- [x] 3.4 增加 `_update_dotenv` 同步方法：支持在成功刷新后通过正则表达式动态重写根目录的 `.env`
- [x] 3.5 拆分并重构 `fetch_bilibili_posts_grpc`：引入自愈刷新拦截和单次重试机制，保护异常降级

## 4. 单元测试与回归校验

- [x] 4.1 在 `tests/test_coser_bio_scraping.py` 编写 `test_bilibili_grpc_token_auto_refresh` 等自愈刷新与持久化写入测试用例
- [x] 4.2 运行回归测试套件 `uv run pytest tests/` 确保 100% 通过
