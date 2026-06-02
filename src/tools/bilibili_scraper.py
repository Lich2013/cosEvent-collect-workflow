import os
import sys
import time
import random
import string
import base64
import grpc
import hashlib
import datetime
import re
import asyncio
from src.tools.playwright_base import BaseScraper
from src.config import settings

# 动态载入已编译的 gRPC protobuf 相关模块 (已从 scratch/grpc_gen 物理迁移至 src/generated 规范包)
generated_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../generated"))
if generated_path not in sys.path:
    sys.path.insert(0, generated_path)

try:
    import bilibili.app.dynamic.v2_pb2 as v2_pb2
    import bilibili.app.dynamic.v2_pb2_grpc as v2_pb2_grpc
    import bilibili.metadata_pb2 as metadata_pb2
    import bilibili.metadata.device_pb2 as device_pb2
    import bilibili.metadata.network_pb2 as network_pb2
    import bilibili.metadata.restriction_pb2 as restriction_pb2
    import bilibili.metadata.locale_pb2 as locale_pb2
    import bilibili.metadata.fawkes_pb2 as fawkes_pb2
except ImportError as e:
    print(f"\x1b[1;33m[Scraper Warning] gRPC protobuf 模块导入失败: {e}，将强制只能使用网页抓取。\x1b[0m")

# ==============================================================================
# B站 移动端 gRPC 凭证指纹和加密算法签名辅助函数
# ==============================================================================
def gen_random_string(length):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def gen_trace_id():
    random_id = gen_random_string(32)
    random_trace_id = random_id[0:24]
    ts = int(time.time())
    b_arr = [0, 0, 0]
    for i in reversed(range(3)):
        ts >>= 8
        val = ts % 256
        if (ts // 128) % 2 == 0:
            b_arr[i] = val
        else:
            b_arr[i] = val - 256
            
    for val in b_arr:
        hex_val = f"{(val & 0xff):02x}"
        random_trace_id += hex_val
        
    random_trace_id += random_id[30:32]
    return f"{random_trace_id}:{random_trace_id[16:32]}:0:0"

def gen_aurora_eid(uid):
    if not uid:
        return ""
    uid_str = str(uid)
    key = b"ad1va46a7lza"
    res = bytearray()
    for i, char in enumerate(uid_str.encode('utf-8')):
        res.append(char ^ key[i % 12])
    b64 = base64.b64encode(res).decode('utf-8')
    return b64.rstrip('=')

def gen_fp(buvid_val, model="Mi 11"):
    raw_str = f"{buvid_val}{model}"
    md5_val = hashlib.md5(raw_str.encode('utf-8')).hexdigest()
    now_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_hex = ''.join(random.choice("0123456789abcdef") for _ in range(16))
    fp_raw = f"{md5_val}{now_str}{random_hex}"
    
    veri_code = 0
    chunks = [fp_raw[i:i+2] for i in range(0, len(fp_raw), 2)]
    for i in range(min(31, len(chunks))):
        try:
            veri_code += int(chunks[i], 16)
        except ValueError:
            pass
    veri_code_hex = f"{(veri_code % 256):02x}"
    return f"{fp_raw}{veri_code_hex}"

def _extract_text_and_author_from_item(item):
    """从 gRPC DynamicItem 中提取发布作者、文本正文、转发原动态等"""
    author_name = "原作者"
    content_text = ""
    ptime_label = ""
    orig_item = None
    
    for mod in item.modules:
        which_item = mod.WhichOneof("module_item")
        if which_item == "module_author":
            if mod.module_author.HasField("author"):
                author_name = mod.module_author.author.name
            ptime_label = mod.module_author.ptime_label_text
        elif which_item == "module_desc":
            content_text = mod.module_desc.text
        elif which_item == "module_opus_summary":
            summary = mod.module_opus_summary.summary
            text_parts = []
            if summary.WhichOneof("content") == "text":
                for node in summary.text.nodes:
                    text_parts.append(node.raw_text)
            content_text = "".join(text_parts)
        elif which_item == "module_dynamic":
            dyn_item = mod.module_dynamic
            which_dyn = dyn_item.WhichOneof("module_item")
            if which_dyn == "dyn_forward":
                orig_item = dyn_item.dyn_forward.item
                
    return author_name, content_text, ptime_label, orig_item

class BilibiliScraper(BaseScraper):
    def __init__(self):
        super().__init__("bilibili")

    @staticmethod
    def _parse_bili_ptime(ptime_str: str) -> tuple[bool, str]:
        """
        解析 B 站 ptime_label_text 时间字符串，识别是否已编辑并补全年份。
        返回 (is_edited, formatted_time_str)
        """
        if not ptime_str or not isinstance(ptime_str, str):
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            return False, datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

        ptime_str = ptime_str.strip()
        is_edited = False
        if "编辑于" in ptime_str:
            is_edited = True
            ptime_str = ptime_str.replace("编辑于", "").strip()

        beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(beijing_tz)
        
        # 1. 尝试匹配完整格式: 2026年5月25日 04:05 或 2026年5月25日 或 2026-05-25 04:05:00 或 2026-05-25
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{1,2})", ptime_str)
        if m:
            year, month, day, hour, minute = map(int, m.groups())
            dt = datetime.datetime(year, month, day, hour, minute, tzinfo=beijing_tz)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", ptime_str)
        if m:
            year, month, day = map(int, m.groups())
            dt = datetime.datetime(year, month, day, 0, 0, tzinfo=beijing_tz)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", ptime_str)
        if m:
            groups = m.groups()
            year, month, day, hour, minute = map(int, groups[:5])
            second = int(groups[5]) if groups[5] else 0
            dt = datetime.datetime(year, month, day, hour, minute, second, tzinfo=beijing_tz)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", ptime_str)
        if m:
            year, month, day = map(int, m.groups())
            dt = datetime.datetime(year, month, day, 0, 0, tzinfo=beijing_tz)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # 2. 尝试匹配无年份格式: 5月25日 04:05 或 5月25日
        m = re.match(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{1,2})", ptime_str)
        if m:
            month, day, hour, minute = map(int, m.groups())
            year = now.year
            dt = datetime.datetime(year, month, day, hour, minute, tzinfo=beijing_tz)
            if dt > now + datetime.timedelta(hours=1):
                dt = dt.replace(year=year - 1)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        m = re.match(r"(\d{1,2})月(\d{1,2})日", ptime_str)
        if m:
            month, day = map(int, m.groups())
            year = now.year
            dt = datetime.datetime(year, month, day, 0, 0, tzinfo=beijing_tz)
            if dt > now + datetime.timedelta(hours=1):
                dt = dt.replace(year=year - 1)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # 3. 尝试匹配无年份日期格式: 05-25
        m = re.match(r"(\d{1,2})-(\d{1,2})", ptime_str)
        if m:
            month, day = map(int, m.groups())
            year = now.year
            dt = datetime.datetime(year, month, day, 0, 0, tzinfo=beijing_tz)
            if dt > now + datetime.timedelta(hours=1):
                dt = dt.replace(year=year - 1)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # 4. 相对时间匹配: "昨天 04:05"
        m = re.match(r"昨天\s*(\d{1,2}):(\d{1,2})", ptime_str)
        if m:
            hour, minute = map(int, m.groups())
            dt = now - datetime.timedelta(days=1)
            dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # "前天 04:05"
        m = re.match(r"前天\s*(\d{1,2}):(\d{1,2})", ptime_str)
        if m:
            hour, minute = map(int, m.groups())
            dt = now - datetime.timedelta(days=2)
            dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # "N天前"
        m = re.match(r"(\d+)天前", ptime_str)
        if m:
            days = int(m.group(1))
            dt = now - datetime.timedelta(days=days)
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # "N小时前"
        m = re.match(r"(\d+)小时前", ptime_str)
        if m:
            hours = int(m.group(1))
            dt = now - datetime.timedelta(hours=hours)
            dt = dt.replace(second=0, microsecond=0)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # "N分钟前"
        m = re.match(r"(\d+)分钟前", ptime_str)
        if m:
            minutes = int(m.group(1))
            dt = now - datetime.timedelta(minutes=minutes)
            dt = dt.replace(second=0, microsecond=0)
            return is_edited, dt.strftime("%Y-%m-%d %H:%M:%S")

        # "刚刚"
        if "刚刚" in ptime_str:
            return is_edited, now.strftime("%Y-%m-%d %H:%M:%S")

        return is_edited, now.strftime("%Y-%m-%d %H:%M:%S")

    async def fetch_bilibili_posts_grpc(self, uid: str, limit: int = None) -> list[dict]:
        """通过 B 站第一方移动端 gRPC 接口抓取空间动态"""
        access_token = settings.bilibili_grpc_access_token
        mid_val = settings.bilibili_grpc_mid
        
        if not access_token or not mid_val:
            raise ValueError("Bilibili gRPC credentials missing in settings.")
            
        host_uid = int(uid)
        limit = limit or settings.default_limit
        print(f"\x1b[1;32m[Scraper] [{self.platform}] 优先启动 gRPC 抓取用户 UID: {host_uid}，限制数: {limit}\x1b[0m")
        
        # 1. 构造请求消息
        req = v2_pb2.DynSpaceReq()
        req.host_uid = host_uid
        req.history_offset = ""
        req.page = 1
        setattr(req, "from", "space")
        
        buvid_val = "XY6CBD464C1BC5767CE40A77F12B89222B6E7"
        
        mobi_app_val = settings.bilibili_grpc_mobi_app
        device_val = settings.bilibili_grpc_device
        build_val = settings.bilibili_grpc_build
        
        if mobi_app_val == "android_hd":
            brand_val = "Huawei"
            model_val = "MatePad"
            version_name_val = "1.41.0"
        else:
            brand_val = "Xiaomi"
            model_val = "Mi 11"
            version_name_val = "8.41.0"
            
        fp_val = gen_fp(buvid_val, model_val)
        
        meta = metadata_pb2.Metadata(
            access_key=access_token,
            mobi_app=mobi_app_val,
            device=device_val,
            build=build_val,
            channel="master",
            platform="android",
            buvid=buvid_val
        )
        
        dev = device_pb2.Device(
            app_id=1,
            build=build_val,
            buvid=buvid_val,
            mobi_app=mobi_app_val,
            platform="android",
            device=device_val,
            brand=brand_val,
            model=model_val,
            osver="12",
            version_name=version_name_val,
            fp=fp_val,
            fp_local=fp_val,
            fp_remote=fp_val,
            fts=int(time.time() - 86400 * 30)
        )
        
        net = network_pb2.Network(
            type=network_pb2.WIFI,
            tf=network_pb2.TF_UNKNOWN
        )
        
        rest = restriction_pb2.Restriction(
            teenagers_mode=False,
            lessons_mode=False,
            mode=restriction_pb2.NORMAL
        )
        
        loc = locale_pb2.Locale(
            timezone="Asia/Shanghai",
            utc_offset="+0800"
        )
        
        fawk = fawkes_pb2.FawkesReq(
            appkey="android",
            env="prod"
        )
        
        ua_val = f'Dalvik/2.1.0 (Linux; U; Android 12; {model_val} Build/SKQ1.211006.001) {version_name_val} os/android model/{model_val} mobi_app/{mobi_app_val} build/{build_val} channel/master innerVer/{build_val} grpc-java-cronet/1.36.1'
        
        metadata = [
            ('user-agent', ua_val),
            ('x-bili-mid', str(mid_val)),
            ('x-bili-aurora-eid', gen_aurora_eid(mid_val)),
            ('x-bili-aurora-zone', ''),
            ('x-bili-trace-id', gen_trace_id()),
            ('authorization', f"identify_v1 {access_token}"),
            ('x-bili-metadata-bin', meta.SerializeToString()),
            ('x-bili-device-bin', dev.SerializeToString()),
            ('x-bili-network-bin', net.SerializeToString()),
            ('x-bili-restriction-bin', rest.SerializeToString()),
            ('x-bili-locale-bin', loc.SerializeToString()),
            ('x-bili-fawkes-req-bin', fawk.SerializeToString())
        ]
        
        host = "grpc.biliapi.net:443"
        credentials = grpc.ssl_channel_credentials()
        
        def _call_grpc():
            with grpc.secure_channel(host, credentials) as channel:
                stub = v2_pb2_grpc.DynamicStub(channel)
                # 1. 获取动态列表
                space_resp = stub.DynSpace(req, metadata=metadata, timeout=10)
                
                # 2. 复用 stub 精准调取每个有效动态的 DynDetail 以获取高精度的最近编辑时间 (例如 '编辑于 2026年5月28日 12:01')
                details = {}
                for item in space_resp.list[:limit]:
                    post_id = str(item.extend.dyn_id_str)
                    if post_id and post_id != "0":
                        try:
                            detail_req = v2_pb2.DynDetailReq()
                            detail_req.uid = mid_val
                            detail_req.dynamic_id = post_id
                            setattr(detail_req, "from", "login")
                            
                            detail_resp = stub.DynDetail(detail_req, metadata=metadata, timeout=5)
                            details[post_id] = detail_resp
                        except Exception as detail_err:
                            print(f"\x1b[1;33m[Scraper Warning] 获取动态 {post_id} 的 DynDetail 失败: {detail_err}\x1b[0m")
                return space_resp, details
                
        response, details_map = await asyncio.to_thread(_call_grpc)
        
        posts = []
        for item in response.list[:limit]:
            post_id = str(item.extend.dyn_id_str)
            if not post_id or post_id == "0":
                continue
            # 提取正文、作者、时间以及转发原博
            author_name, content_text, ptime_label, orig_item = _extract_text_and_author_from_item(item)
            
            # 如果成功拿到了高精度 DynDetail，使用其 module_author 字段的 ptime_label_text 强行覆盖以防时间戳陈旧
            if post_id in details_map:
                detail_item = details_map[post_id].item
                _, _, detail_ptime, _ = _extract_text_and_author_from_item(detail_item)
                if detail_ptime:
                    ptime_label = detail_ptime

            # 合并转发原博
            if orig_item:
                orig_author, orig_content, _, _ = _extract_text_and_author_from_item(orig_item)
                content_text = f"转发了 @{orig_author} 的动态：“{orig_content}”\n说：“{content_text}”"
                
            if not content_text.strip():
                continue
                
            # 解析高精度编辑时间和编辑状态
            is_edited, published_at = self._parse_bili_ptime(ptime_label)
            post_url = f"https://t.bilibili.com/{post_id}"
            
            posts.append({
                "post_id": post_id,
                "content": content_text,
                "post_url": post_url,
                "edit_count": 0,  # 物理版本控制的 edit_count 在数据库层自动合并增长
                "published_at": published_at,
                "is_grpc": True,
                "is_edited": is_edited
            })
            
        # 提取 signature 字段并合成为虚拟动态（执行非空过滤门槛）
        bio = ""
        for item in response.list:
            for mod in item.modules:
                which_item = mod.WhichOneof("module_item")
                if which_item == "module_author":
                    if mod.module_author.HasField("author") and mod.module_author.author.sign:
                        bio = mod.module_author.author.sign.strip()
                        break
            if bio:
                break

        # B站 gRPC 模式个人简介 Card API 联动补爬与自愈
        if not bio:
            try:
                import urllib.request
                import json
                card_url = f"https://api.bilibili.com/x/web-interface/card?mid={uid}"
                req = urllib.request.Request(
                    card_url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
                )
                
                # 嵌套同步请求函数，由 asyncio.to_thread 承载以防死锁事件循环
                def _get_card_bio():
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        card_data = json.loads(resp.read().decode("utf-8"))
                        return card_data.get("data", {}).get("card", {}).get("sign", "").strip()
                        
                bio = await asyncio.to_thread(_get_card_bio)
            except Exception as card_err:
                print(f"\x1b[1;33m[Scraper Warning] [bilibili] [gRPC] 联动补爬 B站 Card API 失败: {card_err}\x1b[0m")

        if bio and bio.strip():
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            print(f"\x1b[1;32m[Scraper] [bilibili] [gRPC] 成功提取并合成了用户 Bio 虚拟动态: '{bio.strip()}'\x1b[0m")
            posts.append({
                "post_id": f"bio_{uid}",
                "content": f"[个人简介] {bio.strip()}",
                "post_url": f"https://space.bilibili.com/{uid}",
                "edit_count": 0,
                "published_at": now_str
            })

        return posts

    async def fetch_bilibili_posts(self, uid: str, limit: int = None) -> list[dict]:
        """抓取指定用户的B站动态列表"""
        if not uid or not str(uid).strip():
            print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] UID 为空，自动跳过抓取。\x1b[0m")
            return []
            
        limit = limit or settings.default_limit
        
        # 1. 尝试使用 gRPC 抓取（若有凭证且未报错）
        access_token = getattr(settings, "bilibili_grpc_access_token", "")
        mid_val = getattr(settings, "bilibili_grpc_mid", 0)
        
        if access_token and mid_val:
            try:
                posts = await self.fetch_bilibili_posts_grpc(uid, limit)
                return posts
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] gRPC 抓取发生异常，将静默降级熔断至 Playwright: {e}\x1b[0m")
                
        # 2. 降级为 Playwright 网页抓取
        return await self._fetch_bilibili_posts_playwright(uid, limit)

    async def _fetch_bilibili_posts_playwright(self, uid: str, limit: int = None) -> list[dict]:
        """[降级网页抓取] 抓取指定用户的B站动态列表"""
        limit = limit or settings.default_limit
        print(f"\x1b[1;33m[Scraper] [{self.platform}] [Playwright 降级网页] 启动抓取用户 UID: {uid}，爬取限制数: {limit}\x1b[0m")
        
        async def _scrape_bili(context, uid: str, limit: int):
            page = await context.new_page()
            posts = []
            
            # 注册网络响应拦截，提取 B站 签名 (Bio)
            bio = ""
            async def on_response(response):
                nonlocal bio
                if "api.bilibili.com/x/space/wbi/acc/info" in response.url and response.status == 200:
                    try:
                        acc_data = await response.json()
                        if "data" in acc_data and acc_data["data"].get("sign"):
                            bio = acc_data["data"]["sign"].strip()
                    except Exception:
                        pass
            page.on("response", on_response)

            # 使用 expect_response 拦截 B站 动态列表 Ajax 接口
            target_url = f"https://space.bilibili.com/{uid}/dynamic"
            try:
                async with page.expect_response(
                    lambda resp: "api.bilibili.com/x/polymer/web-dynamic/v1/feed" in resp.url and resp.status == 200,
                    timeout=15000
                ) as resp_info:
                    await page.goto(target_url)
                response = await resp_info.value
                content = await response.json()
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [bilibili] 拦截 feed 失败 ({e})，尝试直接获取页面渲染\x1b[0m")
                content = {}
            
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
            
            # DOM 签名 (Bio) 降级兜底
            if not bio:
                try:
                    sign_el = page.locator(".h-sign")
                    if await sign_el.is_visible(timeout=3000):
                        bio = (await sign_el.inner_text()).strip()
                except Exception as dom_err:
                    print(f"\x1b[1;33m[Scraper Warning] [bilibili] DOM 兜底解析签名失败: {dom_err}\x1b[0m")

            # 组装虚拟推文注入（执行非空过滤门槛）
            if bio and bio.strip():
                import datetime
                beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\x1b[1;32m[Scraper] [bilibili] [Playwright] 成功提取并合成了用户 Bio 虚拟动态: '{bio.strip()}'\x1b[0m")
                posts.append({
                    "post_id": f"bio_{uid}",
                    "content": f"[个人简介] {bio.strip()}",
                    "post_url": f"https://space.bilibili.com/{uid}",
                    "edit_count": 0,
                    "published_at": now_str
                })
            return posts

        return await self.scrape_flow_handler(_scrape_bili, uid, limit)

    async def search_bilibili_user(self, keyword: str) -> list[dict]:
        """通过 Playwright 网页搜索并拦截 B站 用户检索接口，返回 UP 主候选人列表"""
        if not keyword or not str(keyword).strip():
            return []
            
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动用户检索，关键字: {keyword}\x1b[0m")
        
        async def _search_bili(context, keyword: str):
            page = await context.new_page()
            await page.set_extra_http_headers({
                "Referer": "https://www.bilibili.com",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            candidates = []
            target_url = f"https://search.bilibili.com/upuser?keyword={keyword}"
            
            try:
                # 拦截包含 search/type 或 search/all 且含有 bili_user 且状态为 200 的接口
                async with page.expect_response(
                    lambda resp: ("search/type" in resp.url or "search/all" in resp.url or "search" in resp.url) 
                                 and "bili_user" in resp.url 
                                 and resp.status == 200,
                    timeout=10000
                ) as resp_info:
                    await page.goto(target_url)
                
                response = await resp_info.value
                content = await response.json()
                
                results = []
                if "data" in content and "result" in content["data"]:
                    results = content["data"]["result"]
                elif "result" in content:
                    results = content["result"]
                    
                if results and isinstance(results, list):
                    for item in results:
                        uname = item.get("uname") or item.get("title")
                        if uname and "<em" in uname:
                            import re
                            uname = re.sub(r"<[^>]+>", "", uname)
                            
                        mid = str(item.get("mid") or item.get("id") or "")
                        fans = int(item.get("fans", 0))
                        
                        official_verify = item.get("official_verify") or {}
                        verify_type = official_verify.get("type", -1)
                        verify_desc = official_verify.get("desc", "")
                        
                        if uname and mid:
                            candidates.append({
                                "uname": uname,
                                "mid": mid,
                                "fans": fans,
                                "official_verify": {
                                    "type": verify_type,
                                    "desc": verify_desc
                                }
                            })
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] 拦截 B站 搜索接口超时或失败，尝试解析页面 DOM 兜底: {e}\x1b[0m")
                try:
                    # 自适应选择链：定位用户卡片容器
                    await page.wait_for_selector(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']", timeout=5000)
                    up_items = await page.query_selector_all(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']")
                    
                    for item in up_items[:5]:
                        # 1. 提取昵称与 UID：基于 space.bilibili.com 硬主页超链接锚点
                        link_el = await item.query_selector("a[href*='space.bilibili.com']")
                        if not link_el:
                            # 备选：读取卡片中的任何包含 /space/ 的 <a>
                            link_el = await item.query_selector("a[href*='/space/']")
                        
                        if not link_el:
                            continue
                            
                        uname = (await link_el.inner_text()).strip()
                        href = await link_el.get_attribute("href") or ""
                        
                        mid = ""
                        if "space.bilibili.com/" in href:
                            mid = href.split("space.bilibili.com/")[-1].split("?")[0].strip("/")
                        elif href:
                            import re
                            m = re.search(r"\d+", href)
                            if m:
                                mid = m.group()
                                
                        # 2. 提取粉丝数与个人简介：基于文本关键字特征解析
                        fans = 0
                        usign = ""
                        
                        # 查找包含“粉丝”字样的段落
                        p_el = await item.query_selector("p:has-text('粉丝')")
                        if not p_el:
                            # 备选类名定位
                            p_el = await item.query_selector(".fans, .text2, p.b_text, [class*='fans']")
                            
                        if p_el:
                            # 优先读取 title 属性，防字符截断；若无则读取 inner_text
                            text = (await p_el.get_attribute("title") or await p_el.inner_text() or "").strip()
                            
                            # 匹配粉丝数（支持 "5.8万粉丝" 或 "128粉丝"）
                            import re
                            fans_match = re.search(r"([\d\.]+)(万)?\s*粉丝", text)
                            if fans_match:
                                try:
                                    val = float(fans_match.group(1))
                                    is_wan = fans_match.group(2) is not None
                                    fans = int(val * 10000) if is_wan else int(val)
                                except ValueError:
                                    pass
                                    
                            # 提取个人简介 (usign)
                            # 优先查找内层 <span>，若没有，则提取 “视频” 字样之后的所有文本作为简介
                            span_el = await p_el.query_selector("span")
                            if span_el:
                                usign = (await span_el.inner_text()).strip()
                            else:
                                sig_match = re.search(r"视频\s*·?\s*(.*)", text)
                                if sig_match:
                                    usign = sig_match.group(1).strip()
                                    
                        # 备选个人简介定位
                        if not usign:
                            desc_el = await item.query_selector(".desc, [class*='desc']")
                            if desc_el:
                                usign = (await desc_el.inner_text()).strip()
                                
                        # 3. 提取 B站 官方认证信息 (仅当存在 B站 官方认证标识选择器时)
                        verify_desc = ""
                        auth_el = await item.query_selector(".auth-desc, .personal-auth, .official-auth, [class*='auth-desc'], [class*='personal-auth']")
                        if auth_el:
                            verify_desc = (await auth_el.inner_text()).strip()
                                
                        if uname and mid:
                            candidates.append({
                                "uname": uname,
                                "mid": mid,
                                "fans": fans,
                                "usign": usign,
                                "official_verify": {
                                    "type": 0 if verify_desc else -1,
                                    "desc": verify_desc
                                }
                            })
                except Exception as dom_err:
                    print(f"\x1b[1;31m[Scraper ERROR] DOM 兜底解析也失败: {dom_err}\x1b[0m")
            finally:
                await page.close()
                
            return candidates

        return await self.scrape_flow_handler(_search_bili, keyword)

    async def search_bilibili_users_batch(self, keywords: list[str]) -> dict[str, list[dict]]:
        """批量检索 B站 UP 主，仅启动一个浏览器生命周期以极大地提升运行效率"""
        if not keywords:
            return {}
            
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动批量用户检索，共 {len(keywords)} 个关键字\x1b[0m")
        
        async def _search_batch(context, keywords: list[str]):
            page = await context.new_page()
            await page.set_extra_http_headers({
                "Referer": "https://www.bilibili.com",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            results_map = {}
            import time
            import random
            
            for i, kw in enumerate(keywords):
                if not kw or not str(kw).strip():
                    results_map[kw] = []
                    continue
                    
                if i > 0:
                    delay = random.uniform(1.5, 3.0)
                    time.sleep(delay)
                    
                candidates = []
                target_url = f"https://search.bilibili.com/upuser?keyword={kw}"
                
                try:
                    # 拦截并提取 Ajax 接口（缩短超时为 2.5s，秒级风控响应）
                    async with page.expect_response(
                        lambda resp: ("search/type" in resp.url or "search/all" in resp.url or "search" in resp.url) 
                                     and "bili_user" in resp.url 
                                     and resp.status == 200,
                        timeout=2500
                    ) as resp_info:
                        await page.goto(target_url)
                    
                    response = await resp_info.value
                    content = await response.json()
                    
                    results = []
                    if "data" in content and "result" in content["data"]:
                        results = content["data"]["result"]
                    elif "result" in content:
                        results = content["result"]
                        
                    if results and isinstance(results, list):
                        for item in results:
                            uname = item.get("uname") or item.get("title")
                            if uname and "<em" in uname:
                                import re
                                uname = re.sub(r"<[^>]+>", "", uname)
                                
                            mid = str(item.get("mid") or item.get("id") or "")
                            fans = int(item.get("fans", 0))
                            
                            official_verify = item.get("official_verify") or {}
                            verify_type = official_verify.get("type", -1)
                            verify_desc = official_verify.get("desc", "")
                            
                            # 提取用户签名进行社交媒体交叉验证
                            usign = item.get("usign") or ""
                            
                            if uname and mid:
                                candidates.append({
                                    "uname": uname,
                                    "mid": mid,
                                    "fans": fans,
                                    "usign": usign,
                                    "official_verify": {
                                        "type": verify_type,
                                        "desc": verify_desc
                                    }
                                })
                except Exception as e:
                    print(f"\x1b[1;33m[Scraper Warning] 检索 [{kw}] 接口超时(2.5s)或风控，降级至 DOM 兜底: {e}\x1b[0m")
                    try:
                        # 自适应选择链：定位用户卡片容器
                        await page.wait_for_selector(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']", timeout=3000)
                        up_items = await page.query_selector_all(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']")
                        
                        for item in up_items[:5]:
                            # 1. 提取昵称与 UID：基于 space.bilibili.com 硬主页超链接锚点
                            link_el = await item.query_selector("a[href*='space.bilibili.com']")
                            if not link_el:
                                # 备选：读取卡片中的任何包含 /space/ 的 <a>
                                link_el = await item.query_selector("a[href*='/space/']")
                                
                            if not link_el:
                                continue
                                
                            uname = (await link_el.inner_text()).strip()
                            href = await link_el.get_attribute("href") or ""
                            
                            mid = ""
                            if "space.bilibili.com/" in href:
                                mid = href.split("space.bilibili.com/")[-1].split("?")[0].strip("/")
                            elif href:
                                import re
                                m = re.search(r"\d+", href)
                                if m:
                                    mid = m.group()
                                    
                            # 2. 提取粉丝数与个人简介：基于文本关键字特征解析
                            fans = 0
                            usign = ""
                            
                            # 查找包含“粉丝”字样的段落
                            p_el = await item.query_selector("p:has-text('粉丝')")
                            if not p_el:
                                # 备选类名定位
                                p_el = await item.query_selector(".fans, .text2, p.b_text, [class*='fans']")
                                
                            if p_el:
                                # 优先读取 title 属性，防字符截断；若无则读取 inner_text
                                text = (await p_el.get_attribute("title") or await p_el.inner_text() or "").strip()
                                
                                # 匹配粉丝数（支持 "5.8万粉丝" 或 "128粉丝"）
                                import re
                                fans_match = re.search(r"([\d\.]+)(万)?\s*粉丝", text)
                                if fans_match:
                                    try:
                                        val = float(fans_match.group(1))
                                        is_wan = fans_match.group(2) is not None
                                        fans = int(val * 10000) if is_wan else int(val)
                                    except ValueError:
                                        pass
                                        
                                # 提取个人简介 (usign)
                                # 优先查找内层 <span>，若没有，则提取 “视频” 字样之后的所有文本作为简介
                                span_el = await p_el.query_selector("span")
                                if span_el:
                                    usign = (await span_el.inner_text()).strip()
                                else:
                                    sig_match = re.search(r"视频\s*·?\s*(.*)", text)
                                    if sig_match:
                                        usign = sig_match.group(1).strip()
                                        
                            # 备选个人简介定位
                            if not usign:
                                desc_el = await item.query_selector(".desc, [class*='desc']")
                                if desc_el:
                                    usign = (await desc_el.inner_text()).strip()
                                    
                            # 3. 提取 B站 官方认证信息 (仅当存在 B站 官方认证标识选择器时)
                            verify_desc = ""
                            auth_el = await item.query_selector(".auth-desc, .personal-auth, .official-auth, [class*='auth-desc'], [class*='personal-auth']")
                            if auth_el:
                                verify_desc = (await auth_el.inner_text()).strip()
                                    
                            if uname and mid:
                                candidates.append({
                                    "uname": uname,
                                    "mid": mid,
                                    "fans": fans,
                                    "usign": usign,
                                    "official_verify": {
                                        "type": 0 if verify_desc else -1,
                                        "desc": verify_desc
                                    }
                                })
                    except Exception as dom_err:
                        print(f"\x1b[1;31m[Scraper ERROR] DOM 兜底解析 [{kw}] 也失败: {dom_err}\x1b[0m")
                
                results_map[kw] = candidates
                
            await page.close()
            return results_map

        return await self.scrape_flow_handler(_search_batch, keywords)
