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
            
            # 注册网络响应拦截，提取 Weibo Bio
            bio = ""
            async def on_response(response):
                nonlocal bio
                if "weibo.com/ajax/profile/info" in response.url and response.status == 200:
                    try:
                        profile_data = await response.json()
                        if "data" in profile_data and "user" in profile_data["data"]:
                            u_desc = profile_data["data"]["user"].get("description")
                            if u_desc:
                                bio = u_desc.strip()
                    except Exception:
                        pass
            page.on("response", on_response)

            # 使用 expect_response 拦截 Ajax 接口，实现极速稳定抓取
            target_url = f"https://weibo.com/u/{uid}"
            try:
                async with page.expect_response(
                    lambda resp: "weibo.com/ajax/statuses/mymblog" in resp.url and resp.status == 200,
                    timeout=15000
                ) as resp_info:
                    await page.goto(target_url)
                response = await resp_info.value
                content = await response.json()
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [weibo] 拦截 mymblog 失败 ({e})，尝试直接获取页面渲染\x1b[0m")
                content = {}
            
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
            
            # 若 mymblog 中含有 user 对象，作为二次降级尝试提取 Bio
            if not bio and "data" in content and "list" in content["data"] and content["data"]["list"]:
                for item in content["data"]["list"]:
                    u_desc = item.get("user", {}).get("description")
                    if u_desc:
                        bio = u_desc.strip()
                        break

            # DOM / 元数据 meta description 降级兜底
            if not bio:
                try:
                    meta_desc = await page.get_attribute('meta[name="description"]', 'content')
                    if meta_desc:
                        import re
                        m = re.search(r"个人介绍：(.*?)(?:。|$)", meta_desc)
                        if m:
                            bio = m.group(1).strip()
                except Exception as dom_err:
                    print(f"\x1b[1;33m[Scraper Warning] [weibo] DOM 兜底解析失败: {dom_err}\x1b[0m")

            # 组装虚拟推文注入（执行非空过滤门槛）
            if bio and bio.strip():
                import datetime
                beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\x1b[1;32m[Scraper] [weibo] 成功提取并合成了用户 Bio 虚拟动态: '{bio.strip()}'\x1b[0m")
                posts.append({
                    "post_id": f"bio_{uid}",
                    "content": f"[个人简介] {bio.strip()}",
                    "post_url": f"https://weibo.com/u/{uid}",
                    "edit_count": 0,
                    "published_at": now_str
                })
            return posts
 
        return await self.scrape_flow_handler(_scrape_weibo, uid, limit)

    async def resolve_screen_name(self, screen_name: str) -> dict:
        """根据微博昵称查询其用户详细信息（包含 UID、简介等）"""
        res_map = await self.resolve_screen_names_batch([screen_name])
        return res_map.get(screen_name, {})

    async def resolve_screen_names_batch(self, screen_names: list[str]) -> dict[str, dict]:
        """批量解析微博昵称，返回 昵称 -> 用户信息 字典"""
        if not screen_names:
            return {}
            
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动批量解析 {len(screen_names)} 个昵称\x1b[0m")
        
        async def _resolve_batch(context, names: list[str]):
            page = await context.new_page()
            try:
                # 访问 weibo.com 域以确保 cookie 注入
                await page.goto("https://weibo.com/")
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [weibo] 批量解析初始化页面失败: {e}\x1b[0m")
                return {}
                
            results = {}
            import urllib.parse
            import asyncio
            
            for name in names:
                if not name or not str(name).strip():
                    continue
                encoded_name = urllib.parse.quote(name)
                url = f"https://weibo.com/ajax/profile/info?screen_name={encoded_name}"
                try:
                    res = await page.evaluate(f"async () => {{ const res = await fetch('{url}'); return await res.json(); }}")
                    if res and res.get("ok") == 1 and "data" in res:
                        results[name] = res["data"].get("user") or {}
                except Exception as e:
                    print(f"\x1b[1;33m[Scraper Warning] [weibo] 批量解析 [{name}] 失败 ({e})\x1b[0m")
                # 微小的延迟防风控
                await asyncio.sleep(0.3)
            return results
            
        return await self.scrape_flow_handler(_resolve_batch, screen_names)

