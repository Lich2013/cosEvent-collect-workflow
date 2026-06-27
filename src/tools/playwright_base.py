import os
import json
import traceback
import logging
import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from src.config import settings

from src.utils.logger import log_event

class XhsRateLimitError(Exception):
    """小红书遭遇频控/验证码阻断异常"""
    pass

class BaseScraper:
    def __init__(self, platform: str):
        self.platform = platform
        self.state_file = settings.PROJECT_ROOT / "runtime" / platform / "state.json"
        self.seed_file = settings.PROJECT_ROOT / "config" / "cookies" / f"{platform}_cookies.json"
        
        # 确保运行状态目录存在
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def update_seed_cookies(self, cookies: list[dict]):
        """根据当前有效 cookies 同步更新回写到静态种子文件"""
        if not self.seed_file.exists():
            return
        
        try:
            # 1. 读取原种子内容判定格式
            with open(self.seed_file, "r", encoding="utf-8") as f:
                orig_content = f.read().strip()
            
            is_json_list = False
            is_json_str = False
            
            try:
                parsed = json.loads(orig_content)
                if isinstance(parsed, list):
                    is_json_list = True
                elif isinstance(parsed, str):
                    is_json_str = True
            except Exception:
                pass
            
            # 2. 根据格式序列化最新 cookies
            if is_json_list:
                # 格式 A: 标准 JSON List
                new_content = json.dumps(cookies, indent=2, ensure_ascii=False)
            else:
                # 格式 B/C: 拼装成 name=value; 字符串
                cookie_pairs = []
                for c in cookies:
                    cookie_pairs.append(f"{c['name']}={c['value']}")
                raw_str = "; ".join(cookie_pairs)
                
                if is_json_str:
                    # 格式 B: 外部包着 JSON 双引号的字符串
                    new_content = json.dumps(raw_str, ensure_ascii=False)
                else:
                    # 格式 C: 纯文本
                    new_content = raw_str
            
            # 3. 写入文件
            with open(self.seed_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"\x1b[1;32m[Scraper] [{self.platform}] 成功将运行期最新的 {len(cookies)} 条 Cookies 同步回写更新至种子文件 {self.seed_file.name}。\x1b[0m")
        except Exception as e:
            print(f"\x1b[1;31m[Scraper ERROR] [{self.platform}] 同步回写种子 Cookie 失败: {e}\x1b[0m")

    def load_seed_cookies(self) -> list:
        """从本地的静态种子文件中自适应读取 Cookie (支持标准 JSON 列表及单行纯文本/JSON 字符串)"""
        if not self.seed_file.exists():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] 未发现种子 Cookie 文件: {self.seed_file}，将以空白会话冷启动。\x1b[0m")
            return []
            
        content = ""
        try:
            with open(self.seed_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                
            if not content:
                return []
                
            # 1. 尝试解析为 JSON
            try:
                cookies = json.loads(content)
                if isinstance(cookies, list):
                    # 格式 A: 标准 Playwright 字典数组
                    return cookies
                elif isinstance(cookies, str):
                    # 格式 B: JSON 格式包着的单行 Cookie 字符串，继续解析
                    return self._parse_raw_cookie_string(cookies)
            except json.JSONDecodeError:
                # 格式 C: 非合法 JSON (直接是单行纯文本 Cookie 字符串)
                return self._parse_raw_cookie_string(content)
                
            print(f"\x1b[1;31m[Scraper ERROR] [{self.platform}] 种子 Cookie 格式不合法。\x1b[0m")
            return []
        except Exception as e:
            print(f"\x1b[1;31m[Scraper ERROR] [{self.platform}] 读取种子 Cookie 异常: {e}\x1b[0m")
            return []

    def _parse_raw_cookie_string(self, cookie_str: str) -> list[dict]:
        """解析单行 raw Cookie 字符串，并自动注入对应平台 Domain 和 Path"""
        domain_map = {
            "weibo": ".weibo.com",
            "bilibili": ".bilibili.com",
            "xhs": ".xiaohongshu.com"
        }
        target_domain = domain_map.get(self.platform, f".{self.platform}.com")
        
        parsed_cookies = []
        pairs = cookie_str.strip().split(";")
        for pair in pairs:
            if "=" in pair:
                name, value = pair.split("=", 1)
                name = name.strip()
                value = value.strip()
                # 防御性校验去空，跳过无效名称项
                if name:
                    parsed_cookies.append({
                        "name": name,
                        "value": value,
                        "domain": target_domain,
                        "path": "/"
                    })
        return parsed_cookies

    def _check_state_cookies_expired(self) -> bool:
        """检查 state.json 中的关键 cookie 是否已过期，过期则返回 True"""
        if not self.state_file.exists():
            return True
        try:
            if self.state_file.stat().st_size == 0:
                return True
            with open(self.state_file, "r") as f:
                state = json.load(f)
            cookies = state.get("cookies", [])
            now = datetime.datetime.now().timestamp()
            for c in cookies:
                expires = c.get("expires", -1)
                if expires > 0 and expires < now:
                    name = c.get("name", "?")
                    exp_dt = datetime.datetime.fromtimestamp(expires)
                    print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] cookie '{name}' 已于 {exp_dt.strftime('%Y-%m-%d %H:%M')} 过期，降级到种子 Cookie。\x1b[0m")
                    return True
            return False
        except Exception as e:
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] state.json 检查失败({e})，降级到种子 Cookie。\x1b[0m")
            return True

    async def get_browser_context(self, browser: Browser) -> BrowserContext:
        """根据持久化 state.json 或种子 Cookie 获取有状态的浏览器上下文，支持损坏自重构降级与过期检测"""
        context = None
        user_agent_val = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        viewport_val = {"width": 1280, "height": 800}
        
        # 1. 优先尝试从本地 state.json 恢复会话（先检查 cookie 是否过期）
        if self.state_file.exists() and not self._check_state_cookies_expired():
            try:
                context = await browser.new_context(
                    storage_state=str(self.state_file),
                    user_agent=user_agent_val,
                    viewport=viewport_val
                )
                # 设置页面 15s 严格加载超时
                context.set_default_timeout(settings.page_load_timeout_seconds * 1000)
                return context
            except (json.JSONDecodeError, Exception) as e:
                # 本地 state.json 损坏或失效，执行删除恢复并友好降级到种子 Cookie
                print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] 持久化 state.json 损坏或无法读取({e})，正在自动删除并降级冷启动...\x1b[0m")
        else:
            # state.json 不存在或 cookie 已过期，删除以触发种子 Cookie 重建
            if self.state_file.exists():
                print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] state.json 中 cookie 已过期，自动删除并降级到种子 Cookie。\x1b[0m")
                try:
                    self.state_file.unlink()
                except Exception as unlink_err:
                    print(f"\x1b[1;31m[Scraper ERROR] 删除过期会话文件失败: {unlink_err}\x1b[0m")
        
        # 2. 从零冷启动，注入静态种子 Cookie
        context = await browser.new_context(
            user_agent=user_agent_val,
            viewport=viewport_val
        )
        context.set_default_timeout(settings.page_load_timeout_seconds * 1000)
        seed_cookies = self.load_seed_cookies()
        if seed_cookies:
            try:
                await context.add_cookies(seed_cookies)
                print(f"\x1b[1;32m[Scraper] [{self.platform}] 成功注入 {len(seed_cookies)} 条静态种子 Cookie。\x1b[0m")
            except Exception as e:
                print(f"\x1b[1;31m[Scraper ERROR] [{self.platform}] 注入种子 Cookie 失败: {e}\x1b[0m")
        
        return context

    async def scrape_flow_handler(self, work_func, *args, **kwargs):
        """
        通用无头爬虫核心调度器：
        1. 自动以无头模式运行
        2. 拦截并处理 15s 页面超时、浏览器崩溃和网络阻断等异常，确保不拖垮主 CLI 运行
        3. 结束后自动回写覆盖持久化 state.json
        """
        async with async_playwright() as p:
            browser = None
            context = None
            try:
                # 1. 无头模式运行
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                
                # 2. 加载浏览器上下文 (处理 state.json 损坏降级)
                context = await self.get_browser_context(browser)
                
                # 3. 执行真正的具体平台爬取逻辑
                result = await work_func(context, *args, **kwargs)
                
                # 4. 执行成功，回写最新的会话状态到 state.json
                await context.storage_state(path=str(self.state_file))
                
                # 同步回写到静态种子配置文件
                cookies = await context.cookies()
                if cookies:
                    self.update_seed_cookies(cookies)
                
                return result
                
            except XhsRateLimitError as rle:
                err_msg = f"小红书遭遇频控限流/滑块验证，将跳过本轮会话回写以隔离缓存: {rle}"
                print(f"\x1b[1;33m[Scraper RateLimit Warning] [{self.platform}] {err_msg}\x1b[0m")
                log_event("WARNING", f"scraper_{self.platform}", err_msg, str(rle))
                return []
            except (TimeoutError, PlaywrightTimeoutError) as te:
                err_msg = f"页面在 {settings.page_load_timeout_seconds}s 内加载超时！优雅跳过当前爬行任务。"
                print(f"\x1b[1;31m[Scraper Timeout ERROR] [{self.platform}] {err_msg}\x1b[0m")
                log_event("ERROR", f"scraper_{self.platform}", err_msg, str(te))
                return []
            except Exception as e:
                err_msg = f"发生运行时错误，抓取被中断: {e}"
                print(f"\x1b[1;31m[Scraper Runtime ERROR] [{self.platform}] {err_msg}\x1b[0m")
                traceback.print_exc()
                log_event("ERROR", f"scraper_{self.platform}", err_msg, str(e))
                return []
            finally:
                # 5. 优雅关闭并释放浏览器资源
                try:
                    if context:
                        await context.close()
                    if browser:
                        await browser.close()
                except Exception:
                    pass
