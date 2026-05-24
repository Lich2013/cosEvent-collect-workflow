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
            
            # 使用 expect_response 拦截小红书用户笔记列表 Ajax 接口
            target_url = f"https://www.xiaohongshu.com/user/profile/{uid}"
            async with page.expect_response(
                lambda resp: "api/sns/web/v1/user_posted" in resp.url and resp.status == 200
            ) as resp_info:
                await page.goto(target_url)
                
            response = await resp_info.value
            content = await response.json()
            
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
            return posts

        return await self.scrape_flow_handler(_scrape_xhs, uid, limit)
