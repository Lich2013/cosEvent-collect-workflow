from src.tools.playwright_base import BaseScraper, XhsRateLimitError, SessionHealthError
from src.config import settings
from src.utils.logger import log_event
import asyncio
import random

class XhsScraper(BaseScraper):
    def __init__(self):
        super().__init__("xhs")
        self.last_scrape_status = "success"
        self.last_scrape_error = None
        self.prewarm_url = "https://www.xiaohongshu.com/"

    def _set_status(self, status: str, error: str = None):
        self.last_scrape_status = status
        self.last_scrape_error = error

    def _summarize_response(self, payload: dict) -> str:
        if not isinstance(payload, dict):
            return "响应不是 JSON 对象"
        keys = sorted(str(k) for k in payload.keys())
        code = payload.get("code")
        success = payload.get("success")
        msg = str(payload.get("msg") or payload.get("message") or "")[:120]
        return f"keys={keys}, code={code}, success={success}, msg={msg}"

    def classify_otherinfo_response(self, payload: dict) -> tuple[str, str, str]:
        """分类小红书 otherinfo 响应，返回 (status, bio, summary)。"""
        if not isinstance(payload, dict):
            return "unknown_schema", "", "响应不是 JSON 对象"

        data = payload.get("data")
        summary = self._summarize_response(payload)
        msg = str(payload.get("msg") or payload.get("message") or "")
        combined = f"{payload.get('code')} {payload.get('success')} {msg}".lower()

        if isinstance(data, dict):
            desc = data.get("desc")
            if desc is not None:
                bio = str(desc).strip()
                return ("healthy" if bio else "empty_bio"), bio, summary

        rate_tokens = ["captcha", "verify", "滑块", "验证码", "安全", "风控", "频繁", "访问频繁", "risk"]
        auth_tokens = ["login", "登录", "未登录", "auth", "token", "cookie"]
        not_found_tokens = ["not found", "不存在", "注销", "封禁", "私密", "权限", "无权"]
        if any(token.lower() in combined for token in rate_tokens):
            return "rate_limited", "", summary
        if any(token.lower() in combined for token in auth_tokens):
            return "auth_invalid", "", summary
        if any(token.lower() in combined for token in not_found_tokens):
            return "not_found_or_private", "", summary
        code = payload.get("code")
        success = payload.get("success")
        if code not in (None, 0, "0") or success is False:
            return "unknown_schema", "", summary
        return "unknown_schema", "", summary

    async def classify_page_state(self, page) -> tuple[str, str]:
        """基于 URL 和页面文本识别登录、验证、风控、不可访问等状态。"""
        try:
            url = getattr(page, "url", "") or ""
        except Exception:
            url = ""
        url_lower = url.lower()
        if any(token in url_lower for token in ("captcha", "verify", "risk")):
            return "rate_limited", f"url={url}"
        if any(token in url_lower for token in ("login", "passport")):
            return "auth_invalid", f"url={url}"

        text = ""
        try:
            text = (await page.locator("body").inner_text(timeout=1000))[:500]
        except Exception:
            return "unknown_schema", "无法读取页面正文"

        checks = [
            ("rate_limited", ["验证码", "滑块", "安全验证", "访问频繁", "风险", "环境异常"]),
            ("auth_invalid", ["登录", "请先登录", "重新登录"]),
            ("not_found_or_private", ["用户不存在", "内容无法查看", "账号已封禁", "私密"]),
        ]
        for status, tokens in checks:
            if any(token in text for token in tokens):
                return status, f"body_hint={status}"
        return "unknown_schema", "页面未命中已知状态"

    async def prewarm_page(self, page):
        try:
            await page.goto(self.prewarm_url, wait_until="domcontentloaded", timeout=5000)
            await asyncio.sleep(random.uniform(0.8, 1.6))
        except Exception as e:
            print(f"\x1b[1;33m[Scraper Warning] [xhs] 预热页面失败: {e}\x1b[0m")

    async def natural_wait(self, min_seconds: float = 1.2, max_seconds: float = 3.5):
        await asyncio.sleep(random.uniform(min_seconds, max_seconds))

    async def limited_scroll(self, page):
        try:
            await page.mouse.wheel(0, random.randint(180, 420))
            await self.natural_wait(0.4, 1.2)
        except Exception:
            pass

    async def fetch_xhs_posts_with_context(self, context, uid: str, limit: int = None, prewarm: bool = True) -> list[dict]:
        """Use an existing BrowserContext to fetch one XHS profile bio."""
        page = await context.new_page()
        posts = []
        self._set_status("success")
        if prewarm:
            await self.prewarm_page(page)

        # 注册网络响应拦截，提取小红书个人介绍 (Bio)
        bio = ""
        async def on_response(response):
            nonlocal bio
            if "api/sns/web/v1/user/otherinfo" in response.url and response.status == 200:
                try:
                    user_data = await response.json()
                    status, parsed_bio, summary = self.classify_otherinfo_response(user_data)
                    if status == "healthy":
                        bio = parsed_bio
                    elif status == "empty_bio":
                        self._set_status("empty_bio")
                        self.mark_session_healthy()
                    elif status in ("auth_invalid", "rate_limited", "not_found_or_private", "unknown_schema"):
                        log_event("WARNING", "scraper_xhs", f"otherinfo 响应非健康: {status}; {summary}")
                except Exception:
                    pass
        page.on("response", on_response)

        # 使用 expect_response 拦截小红书个人主页信息 Ajax 接口以获取 Bio
        api_failed = False
        target_url = f"https://www.xiaohongshu.com/user/profile/{uid}"
        try:
            async with page.expect_response(
                lambda resp: "api/sns/web/v1/user/otherinfo" in resp.url and resp.status == 200,
                timeout=5000
            ) as resp_info:
                await page.goto(target_url)
                await self.natural_wait()
                await self.limited_scroll(page)
            response = await resp_info.value
            try:
                user_data = await response.json()
                status, parsed_bio, summary = self.classify_otherinfo_response(user_data)
                log_event("INFO", "scraper_xhs", f"otherinfo 健康分类: {status}; {summary}")
                if status == "healthy":
                    bio = parsed_bio
                elif status == "empty_bio":
                    self._set_status("empty_bio")
                    self.mark_session_healthy()
                else:
                    self._set_status(status, summary)
                    self.mark_session_unhealthy(f"小红书 otherinfo 非健康响应: {status}; {summary}")
                    if status == "rate_limited":
                        raise XhsRateLimitError(f"小红书 otherinfo 风控/验证: {summary}")
                    raise SessionHealthError(f"小红书 otherinfo 非健康响应: {status}; {summary}")
            except Exception:
                if self.last_scrape_status not in ("success", "empty_bio"):
                    raise
        except (XhsRateLimitError, SessionHealthError):
            raise
        except Exception as e:
            print(f"\x1b[1;33m[Scraper Warning] [xhs] 拦截 otherinfo 失败 ({e})，尝试直接获取页面渲染\x1b[0m")
            api_failed = True

        # DOM 个人介绍 降级兜底
        dom_failed = False
        if not bio:
            try:
                desc_el = page.locator(".user-desc")
                if await desc_el.is_visible(timeout=3000):
                    bio = (await desc_el.inner_text()).strip()
                else:
                    dom_failed = True
            except Exception as dom_err:
                print(f"\x1b[1;33m[Scraper Warning] [xhs] DOM 兜底解析个人介绍失败: {dom_err}\x1b[0m")
                dom_failed = True

        if not bio and self.last_scrape_status == "success":
            page_status, page_summary = await self.classify_page_state(page)
            if page_status in ("auth_invalid", "rate_limited", "not_found_or_private"):
                self._set_status(page_status, page_summary)
                self.mark_session_unhealthy(f"小红书页面状态非健康: {page_status}; {page_summary}")
                if page_status == "rate_limited":
                    raise XhsRateLimitError(f"小红书页面风控/验证: {page_summary}")
                raise SessionHealthError(f"小红书页面状态非健康: {page_status}; {page_summary}")

        # 判定风控/限流：API 拦截和 DOM 解析同时失效
        if not bio and api_failed and dom_failed:
            self._set_status("rate_limited", "接口拦截与 DOM 解析均失效")
            self.mark_session_unhealthy("小红书接口拦截与 DOM 解析均失效")
            raise XhsRateLimitError("小红书接口拦截与 DOM 解析均失效，判定遭遇 WAF 限流/滑块阻断")

        # 组装虚拟推文注入（执行非空过滤门槛）
        if bio and bio.strip():
            import datetime
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            print(f"\x1b[1;32m[Scraper] [xhs] 成功提取并合成了用户 Bio 虚拟动态: '{bio.strip()}'\x1b[0m")
            posts.append({
                "post_id": f"bio_{uid}",
                "content": f"[个人简介] {bio.strip()}",
                "post_url": f"https://www.xiaohongshu.com/user/profile/{uid}",
                "edit_count": 0,
                "published_at": now_str
            })
            self._set_status("success")
            self.mark_session_healthy()
        return posts

    async def fetch_xhs_posts_batch(self, uid_items: list[dict], limit: int = None) -> list[dict]:
        """Fetch multiple XHS accounts in one Browser/Context and return per-account results."""
        limit = limit or settings.default_limit
        results = []

        async def _scrape_batch(context, items: list[dict], item_limit: int):
            batch_results = []
            success_count = 0
            for idx, item in enumerate(items):
                uid = str(item.get("xhs_uid") or "").strip()
                if not uid or uid == "-":
                    continue
                if idx > 0:
                    await self.natural_wait(7.0, 10.0)
                if (
                    success_count > 0
                    and settings.xhs_long_pause_every_successes > 0
                    and success_count % settings.xhs_long_pause_every_successes == 0
                ):
                    print(
                        "\x1b[1;36m[Scraper] [xhs] "
                        f"已连续成功抓取 {success_count} 个账号，执行长暂停以降低风控概率...\x1b[0m"
                    )
                    await self.natural_wait(
                        settings.xhs_long_pause_min_seconds,
                        settings.xhs_long_pause_max_seconds
                    )
                try:
                    posts = await self.fetch_xhs_posts_with_context(context, uid, item_limit, prewarm=(idx == 0))
                    status = self.last_scrape_status or "success"
                    error = self.last_scrape_error
                except XhsRateLimitError as e:
                    status = "rate_limited"
                    error = str(e)
                    self._set_status(status, error)
                    self.mark_session_unhealthy(error)
                    batch_results.append({"coser": item, "posts": [], "status": status, "error": error})
                    break
                except SessionHealthError as e:
                    status = self.last_scrape_status or "auth_invalid"
                    error = str(e)
                    self.mark_session_unhealthy(error)
                    batch_results.append({"coser": item, "posts": [], "status": status, "error": error})
                    continue
                except Exception as e:
                    status = self.last_scrape_status or "runtime_error"
                    error = str(e)
                    batch_results.append({"coser": item, "posts": [], "status": status, "error": error})
                    await self.natural_wait(3.0, 6.0)
                    continue
                batch_results.append({"coser": item, "posts": posts, "status": status, "error": error})
                if status in ("success", "empty_bio"):
                    success_count += 1
            return batch_results

        results = await self.scrape_batch_flow_handler(_scrape_batch, uid_items, limit)
        return results or []

    async def fetch_xhs_posts(self, uid: str, limit: int = None) -> list[dict]:
        """抓取指定用户的小红书笔记列表"""
        if not uid or not str(uid).strip():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] UID 为空，自动跳过抓取。\x1b[0m")
            return []
            
        limit = limit or settings.default_limit
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动抓取用户 UID: {uid}，爬取限制数: {limit}\x1b[0m")
        
        async def _scrape_xhs(context, uid: str, limit: int):
            return await self.fetch_xhs_posts_with_context(context, uid, limit)

        return await self.scrape_flow_handler(_scrape_xhs, uid, limit)
