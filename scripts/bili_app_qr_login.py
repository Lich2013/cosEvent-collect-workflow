import hashlib
import time
import requests
import json

# Bilibili AppKeys and Secrets
CLIENT_PRESETS = {
    "1": {
        "name": "云视听小电视 (TV版) [默认]",
        "appkey": "4409e2ce8ffd12b8",
        "appsec": "59b43e04ad6965f34319062b478f83dd"
    },
    "2": {
        "name": "Bilibili HD (安卓平板版) [强烈推荐对齐 gRPC]",
        "appkey": "dfca71928277209b",
        "appsec": "b5475a8825547a4fc26c7d518eaaa02e"
    },
    "3": {
        "name": "Bilibili 手机端粉版 (可能受限于TV登录通道)",
        "appkey": "783bbb7264451d82",
        "appsec": "2653583c8873dea268ab9386918b1d65"
    }
}

def calc_sign(params, secret):
    sorted_params = sorted(params.items())
    query_str = "&".join([f"{k}={v}" for k, v in sorted_params])
    sign_str = query_str + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

def main():
    print("==================================================")
    print("   Bilibili App / HD / TV 扫码登录凭证获取工具 v2")
    print("==================================================")
    print("请选择要模拟的客户端 Key，以获取对应的 gRPC 授权 Token：\n")
    
    for k, v in CLIENT_PRESETS.items():
        print(f"  [{k}] {v['name']}")
        print(f"      AppKey: {v['appkey']}\n")
        
    choice = input("请输入序号选择 (默认 2): ").strip()
    if not choice:
        choice = "2"
        
    if choice not in CLIENT_PRESETS:
        print("❌ 序号选择错误，将自动回退到 [2] Bilibili HD 版。")
        choice = "2"
        
    preset = CLIENT_PRESETS[choice]
    appkey = preset["appkey"]
    appsec = preset["appsec"]
    client_name = preset["name"]
    
    print(f"\n🚀 已选择模拟客户端: {client_name}")
    print("正在向 B 站申请扫码授权密钥...")
    
    ts = int(time.time())
    params = {
        "appkey": appkey,
        "local_id": 0,
        "ts": ts
    }
    params["sign"] = calc_sign(params, appsec)
    
    url_auth = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BiliTV/1.0.0"
    }
    
    try:
        resp = requests.post(url_auth, data=params, headers=headers)
        res_json = resp.json()
        if res_json.get("code") != 0:
            print(f"❌ 申请授权失败 (请确认该 AppKey 是否被 TV 登录通道屏蔽): {res_json.get('message')} (code: {res_json.get('code')})")
            return
        
        data = res_json["data"]
        auth_code = data["auth_code"]
        qr_url = data["url"]
        
        print("\n==================================================================")
        print("请在手机浏览器中打开以下链接，或者使用手机 B 站 App 扫描此二维码进行授权登录：")
        print(f"👉 授权链接：{qr_url}")
        
        # 尝试使用 qrcode 库在终端渲染 ASCII 二维码以方便扫码
        try:
            import qrcode
            qr = qrcode.QRCode()
            qr.add_data(qr_url)
            qr.make()
            print("\n")
            qr.print_ascii(invert=True)
        except ImportError:
            print("\n💡 提示：在终端执行 'pip install qrcode' 后重新运行，可在终端直接显示二维码图形。")
            
        print("==================================================================\n")
        print("正在等待您在手机端（B 站 App）扫码并点击【确认登录】（密钥有效期为 180 秒）...")
        
        # 2. 轮询扫码确认状态
        url_poll = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
        start_time = time.time()
        while time.time() - start_time < 180:
            time.sleep(3)
            poll_ts = int(time.time())
            poll_params = {
                "appkey": appkey,
                "auth_code": auth_code,
                "local_id": 0,
                "ts": poll_ts
            }
            poll_params["sign"] = calc_sign(poll_params, appsec)
            
            poll_resp = requests.post(url_poll, data=poll_params, headers=headers)
            poll_json = poll_resp.json()
            code = poll_json.get("code")
            
            if code == 0:
                print("\n🎉 扫码成功，授权登录已确认！")
                token_data = poll_json["data"]
                access_token = token_data["access_token"]
                refresh_token = token_data["refresh_token"]
                mid = token_data["mid"]
                
                print("==================================================")
                print(f"用户 UID (mid)  : {mid}")
                print(f"access_token   : {access_token}")
                print(f"refresh_token  : {refresh_token}")
                print("==================================================")
                print("\n✅ 配置指引：")
                print("1. 请复制上方完整的 access_token 并配置到您项目的 `.env` 文件中的 `BILIBILI_ACCESS_TOKEN` 变量。")
                print(f"2. 请将 `BILIBILI_MID` 设置为: {mid}")
                
                if choice == "2":
                    print("\n💡 特别提示：由于您使用了 HD (安卓平板版) AppKey，为了保证 gRPC 请求头部信息完美契合该 Token，")
                    print("建议在 B 站 gRPC 接口请求中将 metadata 里的 mobi_app 设置为 'android_hd' 进行匹配。")
                elif choice == "3":
                    print("\n💡 特别提示：由于您使用了 手机端粉版 AppKey，请求 gRPC 接口时 metadata 里的 mobi_app 设为 'android' 即可契合。")
                break
            elif code == 86038:
                print("❌ 二维码已失效，请重新运行脚本。")
                break
            elif code == 86090:
                # 已扫码未确认，静默等待
                pass
            elif code == 86101:
                # 未扫码，静默等待
                pass
            else:
                print(f"⚠️ 接口返回异常状态码: {code}, 错误信息: {poll_json.get('message')}")
                
        else:
            print("\n❌ 扫码超时，请重新运行脚本。")
            
    except Exception as e:
        print("\n💥 网络请求发生异常:", str(e))

if __name__ == "__main__":
    main()
