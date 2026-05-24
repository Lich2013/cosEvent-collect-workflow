from src.tools.playwright_base import BaseScraper
from src.config import settings

class BilibiliScraper(BaseScraper):
    def __init__(self):
        super().__init__("bilibili")

    async def fetch_bilibili_posts(self, uid: str, limit: int = None) -> list[dict]:
        """抓取指定用户的B站动态列表"""
        if not uid or not str(uid).strip():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] UID 为空，自动跳过抓取。\x1b[0m")
            return []
            
        limit = limit or settings.default_limit
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动抓取用户 UID: {uid}，爬取限制数: {limit}\x1b[0m")
        
        async def _scrape_bili(context, uid: str, limit: int):
            page = await context.new_page()
            posts = []
            
            # 使用 expect_response 拦截 B站 动态列表 Ajax 接口
            target_url = f"https://space.bilibili.com/{uid}/dynamic"
            async with page.expect_response(
                lambda resp: "api.bilibili.com/x/polymer/web-dynamic/v1/feed" in resp.url and resp.status == 200
            ) as resp_info:
                await page.goto(target_url)
                
            response = await resp_info.value
            content = await response.json()
            
            if "data" in content and "items" in content["data"]:
                for item in content["data"]["items"][:limit]:
                    post_id = str(item.get("id_str"))
                    try:
                        content_text = item["modules"]["module_dynamic"]["desc"]["text"]
                    except (KeyError, TypeError):
                        if "orig" in item:
                            content_text = ""
                        else:
                            continue
                        
                    # 拦截并合并转发动态内容
                    orig = item.get("orig")
                    if orig:
                        orig_user = "原作者"
                        try:
                            orig_user = orig["modules"]["module_author"]["name"]
                        except (KeyError, TypeError):
                            pass
                        
                        orig_text = ""
                        try:
                            orig_text = orig["modules"]["module_dynamic"]["desc"]["text"]
                        except (KeyError, TypeError):
                            pass
                            
                        content_text = f"转发了 @{orig_user} 的动态：“{orig_text}”\n说：“{content_text}”"
                        
                    post_url = f"https://t.bilibili.com/{post_id}"
                    
                    # 提取发布时间戳并转化为北京时区标准时间字符串格式
                    import datetime
                    try:
                        pub_ts = item["modules"]["module_author"]["pub_ts"]
                        beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                        published_at = datetime.datetime.fromtimestamp(pub_ts, tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                    except (KeyError, TypeError, ValueError):
                        published_at = None
                        
                    # 过滤纯多媒体（视频/图片等投稿）且无任何文本附言的动态记录，防范空数据入库
                    if not content_text.strip():
                        continue

                    posts.append({
                        "post_id": post_id,
                        "content": content_text,
                        "post_url": post_url,
                        "edit_count": 0,
                        "published_at": published_at
                    })
            return posts

        return await self.scrape_flow_handler(_scrape_bili, uid, limit)
