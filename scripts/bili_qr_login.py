import hashlib
import time
import requests
import json

APP_KEY = "4409e2ce8ffd12b8"
APP_SECRET = "59b43e04ad6965f34319062b478f83dd"

def calc_sign(params, secret):
    sorted_params = sorted(params.items())
    query_str = "&".join([f"{k}={v}" for k, v in sorted_params])
    sign_str = query_str + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

def main():
    print("=== Bilibili App/TV 扫码登录凭证获取工具 ===")
    print("本脚本利用 B 站 TV 客户端公开接口获取 access_token 与 refresh_token。")
    print("💡 免验证码风控，免繁琐的抓包过程，只需手机 App 扫码即可。\n")
    
    ts = int(time.time())
    params = {
        "appkey": APP_KEY,
        "local_id": 0,
        "ts": ts
    }
    params["sign"] = calc_sign(params, APP_SECRET)
    
    # 1. 申请二维码
    url_auth = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 BiliTV/1.0.0"
    }
    
    print("正在向 B 站申请扫码授权密钥...")
    try:
        resp = requests.post(url_auth, data=params, headers=headers)
        res_json = resp.json()
        if res_json.get("code") != 0:
            print("❌ 申请失败:", res_json.get("message"))
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
                "appkey": APP_KEY,
                "auth_code": auth_code,
                "local_id": 0,
                "ts": poll_ts
            }
            poll_params["sign"] = calc_sign(poll_params, APP_SECRET)
            
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
                print("\n您可以将获取的 access_token 配置在您项目的 .env 中的 BILIBILI_ACCESS_TOKEN 变量中。")
                print("同时，您可以用拿到的 refresh_token 对已过期的 token 进行平滑更换刷新。")
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
        print("\n💥 网络请求异常:", str(e))

if __name__ == "__main__":
    main()
