import os
import sys
import time
import asyncio
from telegram import Bot
from seleniumbase import SB

# 从 GitHub Secrets / 环境变量中读取敏感配置
USERNAME = os.environ.get("LOGIN_USERNAME")
PASSWORD = os.environ.get("LOGIN_PASSWORD")
LOGIN_URL = os.environ.get("LOGIN_URL")
SERVER_URL = os.environ.get("SERVER_URL")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

def send_tg_notification(message: str, image_path: str = None):
    """同步调用 Telegram 消息与截图发送"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] 未配置 Telegram Bot Token 或 Chat ID，跳过 Telegram 推送。")
        return

    async def _send():
        bot = Bot(token=TG_BOT_TOKEN)
        await bot.send_message(chat_id=TG_CHAT_ID, text=message)
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                await bot.send_photo(chat_id=TG_CHAT_ID, photo=photo)

    try:
        asyncio.run(_send())
    except Exception as e:
        print(f"[ERROR] 发送 Telegram 消息失败: {e}")

def handle_cookie_consent(sb):
    """检测并处理各种常见的 Cookie/GDPR 授权同意弹窗"""
    try:
        selectors = [
            "button#onetrust-accept-btn-handler",
            "button.fc-cta-consent",
            "button[aria-label='Accept all']",
            "button[aria-label='Agree']",
            "button.consent-give",
            "//button[contains(translate(text(), 'AGREE', 'agree'), 'agree')]",
            "//button[contains(translate(text(), 'ACCEPT', 'accept'), 'accept')]",
            "//button[contains(text(), '同意')]"
        ]
        
        for selector in selectors:
            if sb.is_element_visible(selector):
                print(f"[INFO] 🍪 检测到个人信息/Cookie使用授权弹窗: {selector}")
                sb.click(selector)
                sb.sleep(2)
                return True
    except Exception as e:
        print(f"[WARN] 处理 Consent 弹窗时捕获非致命错误: {e}")
    return False

def handle_turnstile_exact_replica(sb) -> bool:
    """ Cloudflare Turnstile 穿透处理 """
    try:
        for attempt in range(1, 3):
            print(f"[INFO] ⏱️ [第 {attempt} 轮检测] 预留 5 秒等待 Cloudflare 拦截层加载...")
            sb.sleep(5)
            
            has_turnstile = sb.execute_script(
                'return document.querySelector("input[name=\'cf-turnstile-response\']") !== null'
            )
            
            if has_turnstile: 
                print(f"[INFO] 🛡️ [第 {attempt} 轮] 发现 Cloudflare Turnstile 人机验证框！")
                shot_path = f"cf_detected_attempt_{attempt}.png"
                sb.save_screenshot(shot_path)
                send_tg_notification(f"[第 {attempt} 轮] 发现 Cloudflare 人机验证框，正在尝试穿透...", shot_path)
                
                print(f"[INFO] ⚡ [第 {attempt} 轮] 正在启动物理级 uc_gui_click_captcha() 穿透点击...")
                sb.uc_gui_click_captcha()
                
                print(f"[INFO] ⏳ [第 {attempt} 轮] 物理点击完成，等待 5 秒让状态同步...")
                sb.sleep(5)
            else:
                print(f"[INFO] 🟢 [第 {attempt} 轮] 当前节点未检测到 CF 拦截框。")
        
        return True
    except Exception as e: 
        print(f"[WARN] 穿透 CF 验证时发生非致命异常: {e}")
        return False

def run():
    if not LOGIN_URL or not SERVER_URL or not USERNAME or not PASSWORD:
        print("[CRITICAL] 缺少必要的环境变量，请确保 GitHub Secrets 配置完整。")
        sys.exit(1)

    # 启动 SeleniumBase UC 模式（关闭无头模式，利用 Xvfb 虚拟显示器执行物理点击）
    with SB(uc=True, headless=False) as sb:
        print("[INFO] 🚀 启动浏览器，准备打开登录页面...")
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=6)
        sb.sleep(3)
        
        handle_cookie_consent(sb)
        handle_turnstile_exact_replica(sb)
        
        login_shot = "before_login.png"
        sb.save_screenshot(login_shot)
        send_tg_notification("📍 已加载登录页面，准备输入凭据...", login_shot)

        print("[INFO] 🔑 输入账号与密码...")
        sb.type("input[name='username']", USERNAME)
        sb.type("input[name='password']", PASSWORD)
        
        print("[INFO] 🖱️ 点击 Sign In 按钮...")
        sb.click("button.button-primary.button-full.button-large[type='submit']")
        sb.sleep(8)

        post_login_shot = "post_login.png"
        sb.save_screenshot(post_login_shot)
        send_tg_notification("🔑 登录流程完成，已跳转或等待页面更新。", post_login_shot)

        print("[INFO] 🌐 导航至服务器管理页面...")
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=6)
        sb.sleep(5)

        handle_cookie_consent(sb)
        handle_turnstile_exact_replica(sb)

        server_page_shot = "server_page.png"
        sb.save_screenshot(server_page_shot)

        # 查找 Start 按钮
        start_button_selector = "button[data-power-action='start']"
        if sb.is_element_visible(start_button_selector):
            print("[INFO] ⚡ 找到 Start 按钮，正在点击...")
            sb.click(start_button_selector)
            send_tg_notification("▶️ 已点击 Start 按钮，等待 10 秒等待服务器响应...", server_page_shot)
            sb.sleep(10)
        else:
            print("[INFO] ℹ️ 未找到可点击的 Start 按钮（服务器可能已在运行或处于其他状态）。")

        # 校验服务器状态
        status_selector = "span[data-live-status]"
        current_status = "未知/未检测到状态文本"
        
        if sb.is_element_visible(status_selector):
            current_status = sb.get_text(status_selector).strip()
            print(f"[INFO] 📊 当前服务器状态: {current_status}")
        else:
            print("[WARN] ⚠️ 未能找到 status_selector 元素")

        final_shot = "final_status.png"
        sb.save_screenshot(final_shot)
        send_tg_notification(
            f"✅ 任务执行完毕！\n🖥️ 当前服务器状态：【{current_status}】", 
            final_shot
        )

if __name__ == "__main__":
    run()
