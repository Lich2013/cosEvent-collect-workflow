from src.tools.playwright_base import BaseScraper
from src.config import settings

class WeiboScraper(BaseScraper):
    def __init__(self):
        super().__init__("weibo")

    async def fetch_weibo_posts(self, uid: str, limit: int = None) -> list[dict]:
        """抓取指定用户的微博动态列表"""
        if not uid or not str(uid).strip():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] UID 为空，自动跳过抓取。\x1b[0m")
            return []
            
        limit = limit or settings.default_limit
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动抓取用户 UID: {uid}，爬取限制数: {limit}\x1b[0m")
        
        async def _scrape_weibo(context, uid: str, limit: int):
            page = await context.new_page()
            posts = []
            
            # 使用 expect_response 拦截 Ajax 接口，实现极速稳定抓取
            target_url = f"https://weibo.com/u/{uid}"
            async with page.expect_response(
                lambda resp: "weibo.com/ajax/statuses/mymblog" in resp.url and resp.status == 200
            ) as resp_info:
                await page.goto(target_url)
                
            response = await resp_info.value
            content = await response.json()
            
            if "data" in content and "list" in content["data"]:
                for item in content["data"]["list"][:limit]:
                    post_id = str(item.get("id"))
                    content_text = item.get("text_raw", "")
                    
                    # 拦截并合并转发微博内容
                    retweeted_status = item.get("retweeted_status")
                    if retweeted_status:
                        orig_user_dict = retweeted_status.get("user") or {}
                        orig_user = orig_user_dict.get("screen_name") or "原作者"
                        orig_text = retweeted_status.get("text_raw", "")
                        content_text = f"转发了 @{orig_user} 的博文：“{orig_text}”\n说：“{content_text}”"
                        
                    # 优先获取 mblogid（短链短码），降级获取 idstr 或 id（长数字ID），避免 None 空值污染
                    post_id_url = item.get("mblogid") or item.get("idstr") or item.get("id")
                    post_url = f"https://weibo.com/{uid}/{post_id_url}"
                    
                    # 提取微博编辑次数及发表时间，支持二次编辑提取
                    edit_count = int(item.get("edit_count") or 0)
                    if edit_count > 0:
                        post_id = f"{post_id}#v{edit_count}"
                    
                    # 健壮解析微博 HTTP-Date 原始格式并转化为北京时间字符串格式
                    import datetime
                    from email.utils import parsedate_to_datetime
                    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                    
                    published_at = None
                    if edit_count > 0:
                        # 尝试通过 editHistory 接口抓取最新编辑版本的真实时间
                        # 使用 long id 作为 mid
                        history_url = f"https://weibo.com/ajax/statuses/editHistory?mid={item.get('id')}&page=1"
                        headers = {"referer": f"https://weibo.com/u/{uid}"} # 这个接口有较为严格的反爬措施，会额外检查referer
                        try:
                            history_resp = await context.request.get(history_url, headers=headers, timeout=3000)
                            if history_resp.ok:
                                history_json = await history_resp.json()
                                statuses = history_json.get("statuses", [])
                                if statuses and isinstance(statuses, list):
                                    latest_edit_time_raw = statuses[0].get("created_at")
                                    if latest_edit_time_raw:
                                        dt = parsedate_to_datetime(latest_edit_time_raw)
                                        published_at = dt.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception as e:
                            print(f"\x1b[1;33m[Scraper Warning] [weibo] 请求 editHistory 失败 ({e})，将降级使用原始时间。\x1b[0m")
                    
                    # 若没有成功获取到物理编辑时间（包括获取失败或非编辑版），采用原始 created_at 降级兜底锁死年份
                    if not published_at:
                        raw_published_at = item.get("created_at")
                        try:
                            dt = parsedate_to_datetime(raw_published_at)
                            published_at = dt.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                        except (ValueError, TypeError, IndexError, AttributeError):
                            published_at = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                    
                    posts.append({
                        "post_id": post_id,
                        "content": content_text,
                        "post_url": post_url,
                        "edit_count": edit_count,
                        "published_at": published_at
                    })
            return posts
 
        return await self.scrape_flow_handler(_scrape_weibo, uid, limit)
