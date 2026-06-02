from src.tools.playwright_base import BaseScraper
from src.config import settings

class XhsScraper(BaseScraper):
    def __init__(self):
        super().__init__("xhs")

    async def fetch_xhs_posts(self, uid: str, limit: int = None) -> list[dict]:
        """抓取指定用户的小红书笔记列表"""
        if not uid or not str(uid).strip():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] UID 为空，自动跳过抓取。\x1b[0m")
            return []
            
        limit = limit or settings.default_limit
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动抓取用户 UID: {uid}，爬取限制数: {limit}\x1b[0m")
        
        async def _scrape_xhs(context, uid: str, limit: int):
            page = await context.new_page()
            posts = []
            
            # 注册网络响应拦截，提取小红书个人介绍 (Bio)
            bio = ""
            async def on_response(response):
                nonlocal bio
                if "api/sns/web/v1/user/otherinfo" in response.url and response.status == 200:
                    try:
                        user_data = await response.json()
                        if "data" in user_data and user_data["data"].get("desc"):
                            bio = user_data["data"]["desc"].strip()
                    except Exception:
                        pass
            page.on("response", on_response)

            # 使用 expect_response 拦截小红书用户笔记列表 Ajax 接口
            target_url = f"https://www.xiaohongshu.com/user/profile/{uid}"
            try:
                async with page.expect_response(
                    lambda resp: "api/sns/web/v1/user_posted" in resp.url and resp.status == 200,
                    timeout=15000
                ) as resp_info:
                    await page.goto(target_url)
                response = await resp_info.value
                content = await response.json()
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [xhs] 拦截 user_posted 失败 ({e})，尝试直接获取页面渲染\x1b[0m")
                content = {}
            
            if "data" in content and "notes" in content["data"]:
                for item in content["data"]["notes"][:limit]:
                    post_id = str(item.get("note_id"))
                    title = item.get("title", "")
                    desc = item.get("desc", "")
                    content_text = f"【{title}】{desc}".strip()
                    
                    post_url = f"https://www.xiaohongshu.com/explore/{post_id}"
                    
                    posts.append({
                        "post_id": post_id,
                        "content": content_text,
                        "post_url": post_url
                    })
            
            # DOM 个人介绍 降级兜底
            if not bio:
                try:
                    desc_el = page.locator(".user-desc")
                    if await desc_el.is_visible(timeout=3000):
                        bio = (await desc_el.inner_text()).strip()
                except Exception as dom_err:
                    print(f"\x1b[1;33m[Scraper Warning] [xhs] DOM 兜底解析个人介绍失败: {dom_err}\x1b[0m")

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
            return posts

        return await self.scrape_flow_handler(_scrape_xhs, uid, limit)
