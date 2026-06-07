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
    """从 gRPC DynamicItem 中提取发布作者、文本正文、转发原动态等，以及 @提及列表"""
    author_name = "原作者"
    content_text = ""
    ptime_label = ""
    orig_item = None
    mentions = []
    
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
                    if node.link:
                        biz_id_str = str(node.link.biz_id or "").strip()
                        link_url = node.link.link or ""
                        is_user_link = False
                        if "space.bilibili.com/" in link_url or biz_id_str:
                            is_user_link = True
                            
                        if is_user_link:
                            uname = node.link.show_text.strip().lstrip("@").strip()
                            uid = biz_id_str
                            if not uid and "space.bilibili.com/" in link_url:
                                import re
                                m = re.search(r"space\.bilibili\.com/(\d+)", link_url)
                                if m:
                                    uid = m.group(1)
                            if uname and uid and uid != "0":
                                mentions.append({"name": uname, "uid": uid})
            content_text = "".join(text_parts)
        elif which_item == "module_dynamic":
            dyn_item = mod.module_dynamic
            which_dyn = dyn_item.WhichOneof("module_item")
            if which_dyn == "dyn_forward":
                orig_item = dyn_item.dyn_forward.item
                
    return author_name, content_text, ptime_label, orig_item, mentions

# Bilibili 已知的各客户端 AppKey 与 AppSecret，用于刷新 Token 时自动匹配签名算法
APP_CREDENTIALS = {
    "android_hd": {
        "appkey": "dfca71928277209b",
        "appsec": "b5475a8825547a4fc26c7d518eaaa02e"
    },
    "android": {
        "appkey": "783bbb7264451d82",
        "appsec": "2653583c8873dea268ab9386918b1d65"
    },
    "tv": {
        "appkey": "4409e2ce8ffd12b8",
        "appsec": "59b43e04ad6965f34319062b478f83dd"
    }
}

class BilibiliScraper(BaseScraper):
    def __init__(self):
        super().__init__("bilibili")
        self._ticket_lock = asyncio.Lock()

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

    async def _fetch_bilibili_posts_grpc_internal(self, uid: str, limit: int = None) -> list[dict]:
        """通过 B 站第一方移动端 gRPC 接口抓取空间动态（底层执行逻辑）"""
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
        
        ticket = await self._get_valid_bili_ticket()
        
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
        if ticket:
            metadata.append(('x-bili-ticket', ticket))
        
        host = "grpc.biliapi.net:443"
        credentials = grpc.ssl_channel_credentials()
        
        # 1. 获取动态列表 (with retry on -352)
        def _call_space():
            with grpc.secure_channel(host, credentials) as channel:
                stub = v2_pb2_grpc.DynamicStub(channel)
                return stub.DynSpace(req, metadata=metadata, timeout=10)
                
        try:
            response = await asyncio.to_thread(_call_space)
        except Exception as space_err:
            if self._is_bili_grpc_risk_error(space_err):
                print(f"\x1b[1;33m[Scraper Warning] DynSpace 触发 -352 风控拦截，尝试刷新 Ticket 后重试...\x1b[0m")
                new_ticket = await self._get_valid_bili_ticket(force_refresh=True)
                metadata = [t for t in metadata if t[0] != 'x-bili-ticket']
                if new_ticket:
                    metadata.append(('x-bili-ticket', new_ticket))
                
                def _call_space_retry():
                    with grpc.secure_channel(host, credentials) as channel:
                        stub = v2_pb2_grpc.DynamicStub(channel)
                        return stub.DynSpace(req, metadata=metadata, timeout=10)
                try:
                    response = await asyncio.to_thread(_call_space_retry)
                except Exception as retry_err:
                    print(f"\x1b[1;31m[Scraper Error] DynSpace 重试依旧遭到 -352 风控拦截: {retry_err}\x1b[0m")
                    raise retry_err
            else:
                raise space_err

        # 2. 复用 stub 精准调取每个有效动态的 DynDetail 以获取高精度的最近编辑时间
        details_map = {}
        for item in response.list[:limit]:
            post_id = str(item.extend.dyn_id_str)
            if post_id and post_id != "0":
                async def _get_detail_with_retry(pid, metadata_list):
                    detail_req = v2_pb2.DynDetailReq()
                    detail_req.uid = mid_val
                    detail_req.dynamic_id = pid
                    setattr(detail_req, "from", "login")
                    
                    def _call_detail():
                        with grpc.secure_channel(host, credentials) as channel:
                            stub = v2_pb2_grpc.DynamicStub(channel)
                            return stub.DynDetail(detail_req, metadata=metadata_list, timeout=5)
                            
                    try:
                        return await asyncio.to_thread(_call_detail)
                    except Exception as err:
                        if self._is_bili_grpc_risk_error(err):
                            print(f"\x1b[1;33m[Scraper Warning] DynDetail 获取 {pid} 触发 -352 风控，尝试刷新 Ticket 后重试...\x1b[0m")
                            new_t = await self._get_valid_bili_ticket(force_refresh=True)
                            new_m = [t for t in metadata_list if t[0] != 'x-bili-ticket']
                            if new_t:
                                new_m.append(('x-bili-ticket', new_t))
                            
                            # 更新外部 metadata 供后续的详情请求直接使用新 Ticket
                            nonlocal metadata
                            metadata = new_m
                            
                            def _call_detail_retry():
                                with grpc.secure_channel(host, credentials) as channel:
                                    stub = v2_pb2_grpc.DynamicStub(channel)
                                    return stub.DynDetail(detail_req, metadata=new_m, timeout=5)
                            try:
                                return await asyncio.to_thread(_call_detail_retry)
                            except Exception as retry_err:
                                print(f"\x1b[1;31m[Scraper Error] DynDetail 重试获取 {pid} 依然失败: {retry_err}\x1b[0m")
                                raise retry_err
                        else:
                            raise err
                            
                try:
                    detail_resp = await _get_detail_with_retry(post_id, metadata)
                    details_map[post_id] = detail_resp
                except Exception as detail_err:
                    print(f"\x1b[1;33m[Scraper Warning] 获取动态 {post_id} 的 DynDetail 最终失败: {detail_err}\x1b[0m")
        
        posts = []
        for item in response.list[:limit]:
            post_id = str(item.extend.dyn_id_str)
            if not post_id or post_id == "0":
                continue
            # 提取正文、作者、时间以及转发原博，还有 mentions
            author_name, content_text, ptime_label, orig_item, mentions = _extract_text_and_author_from_item(item)
            
            # 如果成功拿到了高精度 DynDetail，使用其 module_author 字段的 ptime_label_text 强行覆盖以防时间戳陈旧，也合并 mentions
            if post_id in details_map:
                detail_item = details_map[post_id].item
                _, _, detail_ptime, _, detail_mentions = _extract_text_and_author_from_item(detail_item)
                if detail_ptime:
                    ptime_label = detail_ptime
                if detail_mentions:
                    seen_uids = {m["uid"] for m in mentions}
                    for dm in detail_mentions:
                        if dm["uid"] not in seen_uids:
                            mentions.append(dm)

            # 合并转发原博
            if orig_item:
                orig_author, orig_content, _, _, orig_mentions = _extract_text_and_author_from_item(orig_item)
                content_text = f"转发了 @{orig_author} 的动态：“{orig_content}”\n说：“{content_text}”"
                if orig_mentions:
                    seen_uids = {m["uid"] for m in mentions}
                    for om in orig_mentions:
                        if om["uid"] not in seen_uids:
                            mentions.append(om)
                
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
                "is_edited": is_edited,
                "mentions": mentions
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
                "published_at": now_str,
                "mentions": []
            })

        return posts

    async def fetch_bilibili_posts_grpc(self, uid: str, limit: int = None) -> list[dict]:
        """通过 B 站第一方移动端 gRPC 接口抓取空间动态（支持自愈式 Token/Ticket 自动刷新与重试）"""
        try:
            return await self._fetch_bilibili_posts_grpc_internal(uid, limit)
        except Exception as e:
            # 1. 如果是 -352 风控，且可能本地 Ticket 已失效，尝试刷新 Ticket 后重试
            if self._is_bili_grpc_risk_error(e):
                print(f"\x1b[1;33m[Scraper Warning] 检测到 B站 gRPC -352 风控拦截: {e}，正在尝试刷新 Ticket 自愈...\x1b[0m")
                ticket = await self._get_valid_bili_ticket(force_refresh=True)
                if ticket:
                    print("\x1b[1;32m[Scraper] B站 Ticket 自动更新成功，正在重试 gRPC 抓取...\x1b[0m")
                    return await self._fetch_bilibili_posts_grpc_internal(uid, limit)
            
            # 2. 如果是 -101 等鉴权失效，且有 refresh_token，尝试刷新 token 后重试
            refresh_token = getattr(settings, "bilibili_grpc_refresh_token", "")
            if self._is_bili_grpc_auth_error(e) and refresh_token:
                print(f"\x1b[1;33m[Scraper Warning] 检测到 B站 gRPC 凭证失效/过期: {e}，正在尝试使用 refresh_token 自愈刷新...\x1b[0m")
                success = await self.refresh_bilibili_grpc_token()
                if success:
                    print("\x1b[1;32m[Scraper] B站 Token 自动置换成功，正在重试 gRPC 抓取...\x1b[0m")
                    return await self._fetch_bilibili_posts_grpc_internal(uid, limit)
            raise e

    def _is_bili_grpc_risk_error(self, e: Exception) -> bool:
        """判定异常是否为 B站 gRPC -352 风控拦截"""
        err_str = str(e).lower()
        if "-352" in err_str:
            return True
        return False

    def _is_bili_grpc_auth_error(self, e: Exception) -> bool:
        """精准判定异常是否为 B站 gRPC 鉴权失败或 Token 过期"""
        if not isinstance(e, grpc.RpcError):
            err_str = str(e).lower()
            if "identify_v1" in err_str or "-101" in err_str or "unauthenticated" in err_str or "signature" in err_str:
                return True
            return False
            
        err_str = str(e).lower()
        if "identify_v1" in err_str or "-101" in err_str or "unauthenticated" in err_str or "signature" in err_str:
            return True
            
        try:
            if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                return True
        except AttributeError:
            pass
            
        return False

    async def refresh_bilibili_grpc_token(self) -> bool:
        """调用 B站 接口使用 refresh_token 刷新 access_token"""
        access_token = getattr(settings, "bilibili_grpc_access_token", "")
        refresh_token = getattr(settings, "bilibili_grpc_refresh_token", "")
        mobi_app = getattr(settings, "bilibili_grpc_mobi_app", "android_hd")
        
        if not refresh_token:
            print("\x1b[1;31m[Scraper Error] refresh_token 为空，无法自动刷新 Token。\x1b[0m")
            return False
            
        cred = APP_CREDENTIALS.get(mobi_app, APP_CREDENTIALS["android_hd"])
        appkey = cred["appkey"]
        appsec = cred["appsec"]
        
        ts = int(time.time())
        params = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "appkey": appkey,
            "ts": ts
        }
        
        sorted_params = sorted(params.items())
        query_str = "&".join([f"{k}={v}" for k, v in sorted_params])
        sign_str = query_str + appsec
        params["sign"] = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        
        url = "https://passport.bilibili.com/api/v2/oauth2/refresh_token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 BiliTV/1.0.0"
        }
        
        try:
            import requests
            def _post_refresh():
                r = requests.post(url, data=params, headers=headers, timeout=10)
                return r.status_code, r.json()
                
            status_code, res_json = await asyncio.to_thread(_post_refresh)
            
            if status_code != 200:
                print(f"\x1b[1;31m[Scraper Error] 刷新 Token 失败，HTTP 状态码: {status_code}\x1b[0m")
                return False
                
            if res_json.get("code") != 0:
                print(f"\x1b[1;31m[Scraper Error] 刷新 Token 接口返回错误: {res_json.get('message')} (code: {res_json.get('code')})\x1b[0m")
                return False
                
            token_data = res_json["data"]
            new_access = token_data["access_token"]
            new_refresh = token_data["refresh_token"]
            
            print(f"\x1b[1;32m[Scraper] B站 Token 刷新成功！新 Access Token: {new_access[:6]}..., 新 Refresh Token: {new_refresh[:6]}...\x1b[0m")
            
            settings.bilibili_grpc_access_token = new_access
            settings.bilibili_grpc_refresh_token = new_refresh
            
            self._update_dotenv(new_access, new_refresh)
            return True
        except Exception as e:
            print(f"\x1b[1;31m[Scraper Error] 刷新 B站 Token 发生异常: {e}\x1b[0m")
            return False

    def _update_dotenv(self, access_token: str, refresh_token: str):
        """将新获取的 Access Token 和 Refresh Token 物理更新写入根目录下的 .env 文件中"""
        try:
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            dotenv_path = project_root / ".env"
            
            if not dotenv_path.exists():
                print(f"\x1b[1;33m[Scraper Warning] 未找到 .env 配置文件，无法执行持久化写入 (路径: {dotenv_path})\x1b[0m")
                return
                
            content = dotenv_path.read_text(encoding="utf-8")
            
            if "BILIBILI_ACCESS_TOKEN" in content:
                content = re.sub(
                    r"^BILIBILI_ACCESS_TOKEN\s*=.*$",
                    f"BILIBILI_ACCESS_TOKEN={access_token}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f"\nBILIBILI_ACCESS_TOKEN={access_token}"
                
            if "BILIBILI_REFRESH_TOKEN" in content:
                content = re.sub(
                    r"^#?\s*BILIBILI_REFRESH_TOKEN\s*=.*$",
                    f"BILIBILI_REFRESH_TOKEN={refresh_token}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f"\nBILIBILI_REFRESH_TOKEN={refresh_token}"
                
            dotenv_path.write_text(content, encoding="utf-8")
            print("\x1b[1;32m[Scraper] 成功将最新凭据持久化写入至项目 .env 文件！\x1b[0m")
        except Exception as e:
            print(f"\x1b[1;31m[Scraper Error] 持久化更新 .env 配置文件失败: {e}\x1b[0m")

    async def _get_valid_bili_ticket(self, force_refresh: bool = False) -> str:
        """获取有效的 B站 ticket，如果过期或者强制刷新则重新获取并缓存"""
        ticket = getattr(settings, "bilibili_grpc_ticket", "")
        expires_at = getattr(settings, "bilibili_grpc_ticket_expires_at", 0)
        
        now = int(time.time())
        # 留出 10 分钟 (600 秒) 的缓冲余量
        if not force_refresh and ticket and (expires_at - now > 600):
            return ticket
            
        async with self._ticket_lock:
            # 双重检查锁：在锁定后，重新获取当前的缓存状态
            ticket = getattr(settings, "bilibili_grpc_ticket", "")
            expires_at = getattr(settings, "bilibili_grpc_ticket_expires_at", 0)
            now = int(time.time())
            
            # 如果不是强制刷新，且当前有有效的 ticket（留有 10 分钟缓冲），直接复用
            if not force_refresh and ticket and (expires_at - now > 600):
                return ticket
                
            # 如果是强制刷新（如发生 -352 报错），但有另一个协程在极近期（如 15 秒内）刚刚更新过，则无需二次网络调用，直接复用
            if force_refresh and ticket and (expires_at - now > 259200 - 15):
                return ticket
                
            print(f"\x1b[1;32m[Scraper] B站 ticket 不存在、已过期或触发强制刷新，正在申请新 ticket...\x1b[0m")
            try:
                import hmac
                import hashlib
                import urllib.request
                import urllib.parse
                import json
                
                def hmac_sha256(key, message):
                    key = key.encode('utf-8')
                    message = message.encode('utf-8')
                    return hmac.new(key, message, hashlib.sha256).digest().hex()
                    
                ts = int(time.time())
                hexsign = hmac_sha256("XgwSnGZ1p", f"ts{ts}")
                url = "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"
                params = {
                    "key_id": "ec02",
                    "hexsign": hexsign,
                    "context[ts]": str(ts),
                    "csrf": ""
                }
                
                # 修复 POST 参：以标准的 application/x-www-form-urlencoded 体形式发送
                data = urllib.parse.urlencode(params).encode("utf-8")
                
                req = urllib.request.Request(
                    url,
                    data=data,
                    method="POST",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Content-Type": "application/x-www-form-urlencoded"
                    }
                )
                
                def _post_ticket():
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                        
                res_json = await asyncio.to_thread(_post_ticket)
                
                if res_json.get("code") != 0:
                    print(f"\x1b[1;31m[Scraper Error] 申请 ticket 失败: {res_json.get('message')} (code: {res_json.get('code')})\x1b[0m")
                    return ""
                    
                data = res_json.get("data", {})
                new_ticket = data.get("ticket", "")
                ttl = data.get("ttl", 259200)
                new_expires_at = int(time.time()) + ttl
                
                if new_ticket:
                    print(f"\x1b[1;32m[Scraper] B站 ticket 申请成功！有效期 {ttl} 秒。\x1b[0m")
                    settings.bilibili_grpc_ticket = new_ticket
                    settings.bilibili_grpc_ticket_expires_at = new_expires_at
                    self._update_dotenv_ticket(new_ticket, new_expires_at)
                    return new_ticket
                    
            except Exception as e:
                print(f"\x1b[1;31m[Scraper Error] 申请 B站 ticket 发生异常: {e}\x1b[0m")
                
            return ""

    def _update_dotenv_ticket(self, ticket: str, expires_at: int):
        """将新获取的 B站 ticket 及其过期时间物理更新写入项目根目录下的 .env 文件中"""
        try:
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            dotenv_path = project_root / ".env"
            
            if not dotenv_path.exists():
                print(f"\x1b[1;33m[Scraper Warning] 未找到 .env 配置文件，无法执行 Ticket 持久化写入 (路径: {dotenv_path})\x1b[0m")
                return
                
            content = dotenv_path.read_text(encoding="utf-8")
            
            if "BILIBILI_TICKET" in content:
                content = re.sub(
                    r"^BILIBILI_TICKET\s*=.*$",
                    f"BILIBILI_TICKET={ticket}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f"\nBILIBILI_TICKET={ticket}"
                
            if "BILIBILI_TICKET_EXPIRES_AT" in content:
                content = re.sub(
                    r"^BILIBILI_TICKET_EXPIRES_AT\s*=.*$",
                    f"BILIBILI_TICKET_EXPIRES_AT={expires_at}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f"\nBILIBILI_TICKET_EXPIRES_AT={expires_at}"
                
            dotenv_path.write_text(content, encoding="utf-8")
            print("\x1b[1;32m[Scraper] 成功将最新 Ticket 及其过期时间持久化写入至项目 .env 文件！\x1b[0m")
        except Exception as e:
            print(f"\x1b[1;31m[Scraper Error] 持久化更新 .env Ticket 失败: {e}\x1b[0m")

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
                        "published_at": published_at,
                        "mentions": []
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
                    "published_at": now_str,
                    "mentions": []
                })
            return posts

        return await self.scrape_flow_handler(_scrape_bili, uid, limit)

    async def search_bilibili_user(self, keyword: str) -> list[dict]:
        """通过 Playwright 网页直接检索 B站 用户，返回 UP 主候选人列表"""
        if not keyword or not str(keyword).strip():
            return []
            
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动用户检索，关键字: {keyword}\x1b[0m")
        
        async def _search_bili(context, keyword: str):
            page = await context.new_page()
            await page.set_extra_http_headers({
                "Referer": "https://search.bilibili.com/upuser",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            candidates = []
            import urllib.parse
            import re
            target_url = f"https://search.bilibili.com/upuser?keyword={urllib.parse.quote(str(keyword))}"
            
            try:
                # 直接导航，等待网络空闲以加载 SSR 数据
                await page.goto(target_url, wait_until="networkidle", timeout=12000)
                
                # 兼容性选择：定位用户卡片容器 (优先新版, 其次旧版)
                up_items = await page.query_selector_all(".b-user-info-card")
                if not up_items:
                    up_items = await page.query_selector_all(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']")
                
                for item in up_items[:8]:
                    # 1. 提取昵称与 UID
                    link_el = await item.query_selector(".i_card_title a[href*='space.bilibili.com']")
                    if not link_el:
                        link_el = await item.query_selector("a[href*='space.bilibili.com']")
                    
                    if not link_el:
                        continue
                        
                    uname = (await link_el.inner_text()).strip()
                    href = await link_el.get_attribute("href") or ""
                    
                    # 防御：如果 uname 为空，尝试从 link_el 的 title 属性，或者其他 name 选择器提取
                    if not uname:
                        uname = (await link_el.get_attribute("title") or "").strip()
                    if not uname:
                        name_el = await item.query_selector(".i_card_title, h2, a.text1")
                        if name_el:
                            uname = (await name_el.inner_text()).strip()
                            
                    mid = ""
                    if "space.bilibili.com/" in href:
                        mid = href.split("space.bilibili.com/")[-1].split("?")[0].strip("/")
                    elif href:
                        m = re.search(r"\d+", href)
                        if m:
                            mid = m.group()
                            
                    # 2. 提取粉丝数与个人简介
                    fans = 0
                    usign = ""
                    
                    p_el = await item.query_selector("p:has-text('粉丝')")
                    if not p_el:
                        p_el = await item.query_selector(".fans, .text2, p.b_text, [class*='fans']")
                        
                    if p_el:
                        text = (await p_el.get_attribute("title") or await p_el.inner_text() or "").strip()
                        fans_match = re.search(r"([\d\.]+)(万)?\s*粉丝", text)
                        if fans_match:
                            try:
                                val = float(fans_match.group(1))
                                is_wan = fans_match.group(2) is not None
                                fans = int(val * 10000) if is_wan else int(val)
                            except ValueError:
                                pass
                                
                        span_el = await p_el.query_selector("span")
                        if span_el:
                            span_text = (await span_el.inner_text()).strip()
                            if span_text and span_text != "无":
                                usign = span_text
                        else:
                            sig_match = re.search(r"视频\s*·?\s*(.*)", text)
                            if sig_match:
                                usign = sig_match.group(1).strip()
                                if usign == "无":
                                    usign = ""
                                    
                    if not usign:
                        desc_el = await item.query_selector(".desc, [class*='desc']")
                        if desc_el:
                            usign = (await desc_el.inner_text()).strip()
                            if usign == "无":
                                usign = ""
                                
                    # 3. 提取 B站 官方认证信息
                    verify_desc = ""
                    auth_el = await item.query_selector(".auth-desc, .personal-auth, .official-auth, [class*='auth-desc'], [class*='personal-auth']")
                    if auth_el:
                        verify_desc = (await auth_el.inner_text()).strip()
                    
                    # 自适应：如果在 usign 中检测到认证特征，且 verify_desc 为空，则补充 verify_desc
                    if usign and not verify_desc:
                        is_verify = False
                        verify_keywords = ["知名", "认证", "官方", "优质", "首发", "主播", "代表", "工作室", "企业", "歌手", "演员", "公司"]
                        for vkw in verify_keywords:
                            if vkw in usign:
                                is_verify = True
                                break
                        if is_verify:
                            verify_desc = usign
                            
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
            except Exception as e:
                print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] 检索 [{keyword}] 页面加载失败: {e}\x1b[0m")
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
                "Referer": "https://search.bilibili.com/upuser",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            results_map = {}
            import random
            import urllib.parse
            import re
            
            for i, kw in enumerate(keywords):
                if not kw or not str(kw).strip():
                    results_map[kw] = []
                    continue
                    
                if i > 0:
                    delay = random.uniform(1.5, 3.0)
                    await asyncio.sleep(delay)
                    
                candidates = []
                target_url = f"https://search.bilibili.com/upuser?keyword={urllib.parse.quote(str(kw))}"
                
                try:
                    await page.goto(target_url, wait_until="networkidle", timeout=12000)
                    
                    up_items = await page.query_selector_all(".b-user-info-card")
                    if not up_items:
                        up_items = await page.query_selector_all(".up-item, .user-item, .user-content, [class*='user-item'], [class*='user-content']")
                        
                    for item in up_items[:8]:
                        # 1. 提取昵称与 UID
                        link_el = await item.query_selector(".i_card_title a[href*='space.bilibili.com']")
                        if not link_el:
                            link_el = await item.query_selector("a[href*='space.bilibili.com']")
                        
                        if not link_el:
                            continue
                            
                        uname = (await link_el.inner_text()).strip()
                        href = await link_el.get_attribute("href") or ""
                        
                        # 防御：如果 uname 为空，尝试从 link_el 的 title 属性，或者其他 name 选择器提取
                        if not uname:
                            uname = (await link_el.get_attribute("title") or "").strip()
                        if not uname:
                            name_el = await item.query_selector(".i_card_title, h2, a.text1")
                            if name_el:
                                uname = (await name_el.inner_text()).strip()
                                
                        mid = ""
                        if "space.bilibili.com/" in href:
                            mid = href.split("space.bilibili.com/")[-1].split("?")[0].strip("/")
                        elif href:
                            m = re.search(r"\d+", href)
                            if m:
                                mid = m.group()
                                
                        # 2. 提取粉丝数与个人简介
                        fans = 0
                        usign = ""
                        
                        p_el = await item.query_selector("p:has-text('粉丝')")
                        if not p_el:
                            p_el = await item.query_selector(".fans, .text2, p.b_text, [class*='fans']")
                            
                        if p_el:
                            text = (await p_el.get_attribute("title") or await p_el.inner_text() or "").strip()
                            fans_match = re.search(r"([\d\.]+)(万)?\s*粉丝", text)
                            if fans_match:
                                try:
                                    val = float(fans_match.group(1))
                                    is_wan = fans_match.group(2) is not None
                                    fans = int(val * 10000) if is_wan else int(val)
                                except ValueError:
                                    pass
                                    
                            span_el = await p_el.query_selector("span")
                            if span_el:
                                span_text = (await span_el.inner_text()).strip()
                                if span_text and span_text != "无":
                                    usign = span_text
                            else:
                                sig_match = re.search(r"视频\s*·?\s*(.*)", text)
                                if sig_match:
                                    usign = sig_match.group(1).strip()
                                    if usign == "无":
                                        usign = ""
                                        
                        if not usign:
                            desc_el = await item.query_selector(".desc, [class*='desc']")
                            if desc_el:
                                usign = (await desc_el.inner_text()).strip()
                                if usign == "无":
                                    usign = ""
                                    
                        # 3. 提取 B站 官方认证信息
                        verify_desc = ""
                        auth_el = await item.query_selector(".auth-desc, .personal-auth, .official-auth, [class*='auth-desc'], [class*='personal-auth']")
                        if auth_el:
                            verify_desc = (await auth_el.inner_text()).strip()
                        
                        # 自适应：如果在 usign 中检测到认证特征，且 verify_desc 为空，则补充 verify_desc
                        if usign and not verify_desc:
                            is_verify = False
                            verify_keywords = ["知名", "认证", "官方", "优质", "首发", "主播", "代表", "工作室", "企业", "歌手", "演员", "公司"]
                            for vkw in verify_keywords:
                                if vkw in usign:
                                    is_verify = True
                                    break
                            if is_verify:
                                verify_desc = usign
                                
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
                except Exception as e:
                    print(f"\x1b[1;33m[Scraper Warning] [{self.platform}] 检索 [{kw}] 页面加载失败: {e}\x1b[0m")
                
                results_map[kw] = candidates
                
            await page.close()
            return results_map

        res = await self.scrape_flow_handler(_search_batch, keywords)
        if isinstance(res, list):
            return {}
        return res

    async def resolve_uids_batch(self, uids: list[str]) -> dict[str, dict]:
        """批量解析 B站 UIDs，通过导航到个人空间主页并拦截 acc/info 接口来提取完整签名与官方认证"""
        if not uids:
            return {}
            
        print(f"\x1b[1;33m[Scraper] [{self.platform}] 启动批量用户空间解析，共 {len(uids)} 个 UID\x1b[0m")
        
        async def _resolve_batch(context, uids_list: list[str]):
            page = await context.new_page()
            results = {}
            import asyncio
            import random
            
            for i, uid in enumerate(uids_list):
                if not uid or not str(uid).strip():
                    continue
                    
                if i > 0:
                    delay = random.uniform(1.5, 3.0)
                    await asyncio.sleep(delay)
                    
                bio = ""
                uname = ""
                verify_desc = ""
                
                async def on_response(response):
                    nonlocal bio, uname, verify_desc
                    if "api.bilibili.com/x/space/wbi/acc/info" in response.url and response.status == 200:
                        try:
                            acc_data = await response.json()
                            if "data" in acc_data:
                                data = acc_data["data"]
                                if data.get("sign"):
                                    bio = data["sign"].strip()
                                if data.get("name"):
                                    uname = data["name"].strip()
                                if data.get("official") and data["official"].get("title"):
                                    verify_desc = data["official"]["title"].strip()
                        except Exception:
                            pass
                            
                page.on("response", on_response)
                
                target_url = f"https://space.bilibili.com/{uid}"
                try:
                    await page.goto(target_url, wait_until="networkidle", timeout=12000)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"\x1b[1;33m[Scraper Warning] [bilibili] 访问空间 {uid} 页面加载失败/超时: {e}\x1b[0m")
                    
                page.remove_listener("response", on_response)
                
                # DOM 签名 (Bio) 降级兜底
                if not bio:
                    try:
                        sign_el = page.locator(".h-sign")
                        if await sign_el.is_visible(timeout=2000):
                            bio = (await sign_el.inner_text()).strip()
                    except Exception:
                        pass
                        
                results[uid] = {
                    "uname": uname,
                    "bio": bio,
                    "verify_desc": verify_desc
                }
            await page.close()
            return results
            
        return await self.scrape_flow_handler(_resolve_batch, uids)
