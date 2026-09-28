import asyncio
import io
import re
import json
import html
import os
import httpx
import random
import string
import time
import unicodedata
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest

# ==================== CONFIGURATION SECTION ====================

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(os.getenv("ADMIN_ID"))]

# ডাটা ফাইল নির্দেশিকা
USER_DATA_FILE = "users.json"
PAID_SMS_FILE = "paid_sms.json"
STATS_FILE = "user_stats.json"
BANNED_USERS_FILE = "banned_users.json"
WITHDRAW_DATA_FILE = "withdraw_requests.json"
ACTIVITY_LOGS_FILE = "activity_logs.json"
SETTINGS_FILE = "settings.json"
ACTIVE_NUMBERS_FILE = "active_numbers.json"
MANUAL_RANGES_FILE = "manual_ranges.json"

DEFAULT_SETTINGS = {
    "api_key": os.getenv("API_KEY"),
    "base_url": os.getenv("BASE_URL"),
    "otp_group_id": os.getenv("OTP_GROUP_ID"),
    "otp_group_url": os.getenv("OTP_GROUP_URL"),
    "channel_url": os.getenv("CHANNEL_URL"),
    "support_username": os.getenv("SUPPORT_USERNAME"),

    "maintenance_mode": False,
    "min_withdraw": 0.5,
    "max_withdraw": 100.0,
    "cooldown_time": 1.0,
    "otp_reward": 0.0020,
    "refer_bonus": 0.050,
    "numbers_per_request": 1,
    "force_join_enabled": False,
    "force_join_channels": ["@freeotpoffical"],
    "join_alert_enabled": True,
    "auto_range": True,
    "traffic_enabled": True,
    "leaderboard_enabled": True
}

# ==================== DATA & SETTINGS ENGINE ====================

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = False
        for k, v in DEFAULT_SETTINGS.items():
            if k not in data:
                data[k] = v
                updated = True
        if updated:
            save_settings(data)
        return data
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def load_json(filepath, default_val):
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(default_val, f)
        return default_val
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return default_val

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

# ==================== USER & BALANCE MANAGEMENT ====================

def get_user(uid, username=None, full_name=None):
    uid_str = str(uid)
    data = load_json(USER_DATA_FILE, {})
    if uid_str not in data:
        data[uid_str] = {
            "user_id": uid_str,
            "balance": 0.0,
            "username": username,
            "full_name": full_name,
            "referrals": 0,
            "referral_earnings": 0.0,
            "referred_by": None,
            "withdrawal_method": None
        }
        save_json(USER_DATA_FILE, data)
    else:
        updated = False
        if username and data[uid_str].get("username") != username:
            data[uid_str]["username"] = username
            updated = True
        if full_name and data[uid_str].get("full_name") != full_name:
            data[uid_str]["full_name"] = full_name
            updated = True
        if updated:
            save_json(USER_DATA_FILE, data)
    return data[uid_str]

async def update_db_balance(uid, amount):
    uid_str = str(uid)
    data = load_json(USER_DATA_FILE, {})
    if uid_str in data:
        data[uid_str]["balance"] = round(data[uid_str].get("balance", 0.0) + amount, 4)
        save_json(USER_DATA_FILE, data)
        return data[uid_str]["balance"]
    return 0.0

def is_admin(user_id):
    return user_id in ADMINS

def is_user_banned(uid):
    banned_list = load_json(BANNED_USERS_FILE, [])
    return str(uid) in banned_list

def ban_user(uid):
    banned_list = load_json(BANNED_USERS_FILE, [])
    uid_str = str(uid)
    if uid_str not in banned_list:
        banned_list.append(uid_str)
        save_json(BANNED_USERS_FILE, banned_list)
        return True
    return False

def unban_user(uid):
    banned_list = load_json(BANNED_USERS_FILE, [])
    uid_str = str(uid)
    if uid_str in banned_list:
        banned_list.remove(uid_str)
        save_json(BANNED_USERS_FILE, banned_list)
        return True
    return False

# ==================== UTILITY FUNCTIONS ====================

def strip_html_tags(text: str) -> str:
    return re.sub(r'<[^>]*>', '', str(text))

def unstyle_text(text: str) -> str:
    if not text: return ""
    return unicodedata.normalize('NFKC', str(text))

def normalize_number(num):
    return re.sub(r'\D', '', str(num))

def mask_number(num):
    num_str = str(num).replace('+', '').replace(' ', '').strip()
    if len(num_str) >= 8:
        return f"{num_str[:4]}✦✦✦{num_str[-4:]}"
    return num_str

def format_balance(balance):
    return f"{balance:.4f}"

def generate_payment_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))

def extract_otp(text):
    if not text or text == "No Content": return "N/A"
    text_clean = str(text).strip()

    # 1. ✅ "DIGITS is your verification/code" — TikTok, FB style
    # Example: "[#][TikTok] 047100 is your verification code"
    digits_before = re.search(r'\b(\d{4,8})\s+is\s+your', text_clean, re.IGNORECASE)
    if digits_before: return digits_before.group(1).strip()

    # 2. ✅ "code is DIGITS" or "code: DIGITS" — digits only, NOT words
    code_then_digits = re.search(
        r'(?:code|otp|pin|passcode|verification|verify|token)[:\s]+(\d{4,8})\b',
        text_clean, re.IGNORECASE
    )
    if code_then_digits: return code_then_digits.group(1).strip()

    # 3. ✅ "#DIGITS" — hash prefix style
    hash_code = re.search(r'#(\d{4,8})\b', text_clean)
    if hash_code: return hash_code.group(1).strip()

    # 4. ✅ Spaced OTP "123 456" or "123-456"
    spaced_otp = re.search(r'\b(\d{3}[\s-]\d{3})\b', text_clean)
    if spaced_otp: return spaced_otp.group(1)

    # 5. ✅ Exactly 6-digit code (most common OTP)
    six_digit = re.search(r'\b(\d{6})\b', text_clean)
    if six_digit: return six_digit.group(1)

    # 6. ✅ 4-8 digit fallback
    digit_match = re.search(r'\b(\d{4,8})\b', text_clean)
    if digit_match: return digit_match.group(1)

    return "N/A"


def load_country_map(filename="Country.txt"):
    country_map = {}
    if not os.path.exists(filename):
        return country_map
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("|")
                    if len(parts) >= 3:
                        prefix = parts[0].strip()
                        flag = parts[1].strip()
                        name = parts[2].strip()
                        country_map[prefix] = (flag, name)
    except Exception as e:
        print(f"Error loading Country.txt: {e}")
    return country_map

def get_country_info(number):
    clean_num = normalize_number(number)
    country_map = load_country_map()
    sorted_prefixes = sorted(country_map.keys(), key=len, reverse=True)
    for prefix in sorted_prefixes:
        if clean_num.startswith(prefix):
            return country_map[prefix]
    return "🌐", "Global"

# ==================== ALLOWED SERVICES ====================
# শুধু এই service গুলো GET NUMBER এ দেখাবে এবং OTP group/console এ যাবে
ALLOWED_SERVICES = {
    "facebook",
    "whatsapp",
    "instagram",
    "discord",
    "imo",
    "tiktok",
    "telegram"
}

def is_allowed_service(service_name: str) -> bool:
    """service name ALLOWED_SERVICES এ আছে কিনা check করে (case-insensitive)"""
    if not service_name: return False
    name = service_name.lower().strip()
    return any(allowed in name for allowed in ALLOWED_SERVICES)

def detect_service(full_sms):
    if not full_sms: return "SMS SERVICE"
    sms_lower = full_sms.lower()
    if "facebook" in sms_lower or "fb" in sms_lower: return "FACEBOOK"
    if "instagram" in sms_lower or "insta" in sms_lower: return "INSTAGRAM"
    if "whatsapp" in sms_lower: return "WHATSAPP"
    if "telegram" in sms_lower: return "TELEGRAM"
    if "tiktok" in sms_lower: return "TIKTOK"
    if "discord" in sms_lower: return "DISCORD"
    if "imo" in sms_lower: return "IMO"
    return "SMS SERVICE"

def clean_range_id(range_str: str) -> str:
    if not range_str: return ""
    number_str = str(range_str).split('|')[-1].strip()
    return re.sub(r'[^\w]', '', number_str)

def get_service_icon(app_name):
    name = str(app_name).lower().strip()
    if "whatsapp" in name: return "🟢"
    if "facebook" in name or "fb" in name: return "📘"
    if "telegram" in name or "tg" in name: return "✈️"
    if "instagram" in name or "insta" in name: return "📸"
    if "tiktok" in name: return "🎵"
    if "twitter" in name or name == "x": return "🐦"
    if "snapchat" in name: return "👻"
    if "viber" in name: return "💜"
    if "imo" in name: return "📱"
    if "discord" in name: return "🎮"
    if "line" in name: return "💚"
    if "wechat" in name: return "💬"
    if "kakaotalk" in name or "kakao" in name: return "🟡"
    if "vkontakte" in name or "vk" in name: return "🔵"
    if "signal" in name: return "🔒"
    if "linkedin" in name: return "💼"
    if "threads" in name: return "🧵"
    if "tinder" in name: return "🔥"
    if "bumble" in name: return "🐝"
    if "badoo" in name: return "💜"
    if "okcupid" in name: return "💘"
    if "bigo" in name: return "🎥"
    if "twitch" in name: return "👾"
    if "google" in name or "gmail" in name or "youtube" in name: return "🔴"
    if "microsoft" in name or "outlook" in name or "hotmail" in name: return "🪟"
    if "apple" in name or "icloud" in name: return "🍎"
    if "openai" in name or "chatgpt" in name or "gpt" in name: return "🤖"
    if "claude" in name: return "🧠"
    if "yahoo" in name: return "🟣"
    if "naver" in name: return "🟢"
    if "binance" in name: return "🪙"
    if "paypal" in name: return "💳"
    if "coinbase" in name: return "🏦"
    if "crypto" in name: return "💎"
    if "wise" in name or "revolut" in name: return "💸"
    if "uber" in name: return "🚗"
    if "grab" in name: return "🚘"
    if "gojek" in name: return "🛵"
    if "foodpanda" in name or "deliveroo" in name: return "🍔"
    if "indrive" in name or "indriver" in name: return "🚕"
    if "amazon" in name: return "📦"
    if "shopee" in name: return "🛍️"
    if "lazada" in name: return "🛒"
    if "ebay" in name: return "🏷️"
    if "daraz" in name: return "🏬"
    if "ali" in name or "aliexpress" in name: return "🛒"
    if "netflix" in name: return "🍿"
    if "spotify" in name: return "🎧"
    if "steam" in name: return "🕹️"
    if "pubg" in name: return "🔫"
    if "roblox" in name: return "🧱"
    return "📱"

def get_service_percentage(app_name):
    name = str(app_name).lower().strip()
    if "whatsapp" in name: return "95%"
    if "facebook" in name or "fb" in name: return "90%"
    if "telegram" in name: return "88%"
    if "instagram" in name or "insta" in name: return "90%"
    if "imo" in name: return "92%"
    if "discord" in name: return "85%"
    if "tiktok" in name: return "90%"
    return "90%"

# ==================== STATS & LOGS ENGINE ====================

def add_number_taken(uid, count=1):
    uid = str(uid)
    stats = load_json(STATS_FILE, {})
    if uid not in stats: stats[uid] = {"numbers_taken": [], "otps_received": []}
    now = datetime.now().isoformat()
    for _ in range(count): stats[uid]["numbers_taken"].append(now)
    save_json(STATS_FILE, stats)

def add_otp_received(uid):
    uid = str(uid)
    stats = load_json(STATS_FILE, {})
    if uid not in stats: stats[uid] = {"numbers_taken": [], "otps_received": []}
    stats[uid]["otps_received"].append(datetime.now().isoformat())
    save_json(STATS_FILE, stats)

def log_global_activity(uid, action, details):
    logs = load_json(ACTIVITY_LOGS_FILE, [])
    now = datetime.now()
    log_entry = {
        "uid": str(uid),
        "action": action,
        "details": details,
        "timestamp": now.isoformat()
    }
    logs.append(log_entry)
    save_json(ACTIVITY_LOGS_FILE, logs)

# ==================== KEYBOARDS ====================

def rkbtn(text: str, style: str = None): return KeyboardButton(text=text, api_kwargs={"style": style}) if style else KeyboardButton(text=text)

def rbtn(text: str, style: str = None, callback_data: str = None, url: str = None): return InlineKeyboardButton(**{k: v for k, v in [("text", text), ("callback_data", callback_data), ("url", url), ("api_kwargs", {"style": style} if style else None)] if v is not None})

def main_keyboard(user_id):
    settings = load_settings()
    traffic_on = settings.get("traffic_enabled", True)
    lb_on = settings.get("leaderboard_enabled", True)
    live_on = settings.get("live_console_enabled", True)

    keyboard = [
        [rkbtn("🔴 GET NUMBER", style="danger")],
    ]

    # Traffic ও Leaderboard row — নীল
    mid_row = []
    if traffic_on:
        mid_row.append(rkbtn("📊 TRAFFIC", style="primary"))
    if lb_on:
        mid_row.append(rkbtn("🏆 LEADERBOARD", style="primary"))
    if mid_row:
        keyboard.append(mid_row)

    # Live Console — নীল, আলাদা row
    if live_on:
        keyboard.append([rkbtn("📡 LIVE CONSOLE", style="primary")])

    # Balance ও Refer — সবুজ
    keyboard.append([rkbtn("💵 BALANCE", style="success"), rkbtn("🎁 REFER & EARN", style="success")])

    # Support — নীল
    keyboard.append([rkbtn("💬 SUPPORT", style="primary")])

    if is_admin(user_id):
        keyboard.append([rkbtn("⚙️ ADMIN PANEL", style="primary")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_main_keyboard():
    keyboard = [
        [KeyboardButton("⚙️ SYSTEM CONFIG"), KeyboardButton("💵 USER & BALANCE")],
        [KeyboardButton("🔒 SECURITY & JOIN"), KeyboardButton("📢 NOTICE & B-CAST")],
        [KeyboardButton("🔙 BACK TO MAIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_system_config_keyboard():
    settings = load_settings()
    live_on = settings.get("live_console_enabled", True)
    live_btn = "🟢 LIVE CONSOLE: ON" if live_on else "🔴 LIVE CONSOLE: OFF"

    traffic_on = settings.get("traffic_enabled", True)
    traffic_btn = "🟢 TRAFFIC: ON" if traffic_on else "🔴 TRAFFIC: OFF"

    lb_on = settings.get("leaderboard_enabled", True)
    lb_btn = "🟢 LEADERBOARD: ON" if lb_on else "🔴 LEADERBOARD: OFF"

    keyboard = [
        [KeyboardButton("🔑 SET API KEY"), KeyboardButton("🌐 SET API BASE URL")],
        [KeyboardButton("📢 SET OTP CHANNEL ID"), KeyboardButton("💰 SET WITHDRAW LIMITS")],
        [KeyboardButton("🎁 SET REFER BONUS"), KeyboardButton("⏱ SET COOLDOWN")],
        [KeyboardButton(live_btn)],
        [KeyboardButton(traffic_btn), KeyboardButton(lb_btn)],
        [KeyboardButton("🚫 TOGGLE MAINTENANCE"), KeyboardButton("🔙 BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_user_balance_keyboard():
    keyboard = [
        [KeyboardButton("➕ ADD BALANCE"), KeyboardButton("➖ REMOVE BALANCE")],
        [KeyboardButton("💬 DIRECT MSG USER"), KeyboardButton("🔍 SEARCH BY USERNAME")],
        [KeyboardButton("📜 ALL USER BALANCE"), KeyboardButton("🔙 BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_security_join_keyboard():
    keyboard = [
        [KeyboardButton("🚫 BAN USER"), KeyboardButton("✅ UNBAN USER")],
        [KeyboardButton("📢 FORCE CHANNELS"), KeyboardButton("📜 BAN USER LIST")],
        [KeyboardButton("🔙 BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_force_channel_keyboard():
    keyboard = [
        [KeyboardButton("➕ ADD CHANNEL"), KeyboardButton("➖ DELETE CHANNEL")],
        [KeyboardButton("🔙 BACK TO SECURITY")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_notice_bcast_keyboard():
    keyboard = [
        [KeyboardButton("📢 BROADCAST NOTICE"), KeyboardButton("📝 SET WELCOME MSG")],
        [KeyboardButton("💬 SET SUPPORT USERNAME"), KeyboardButton("🔗 SET CHANNEL LINK")],
        [KeyboardButton("🔙 BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ CANCEL")]], resize_keyboard=True)

# ==================== ASYNC CLIENT & QUEUE ====================

client_async = httpx.AsyncClient(timeout=10.0, verify=False, headers={"User-Agent": "Mozilla/5.0"})
request_queue = asyncio.Queue()
active_numbers = load_json(ACTIVE_NUMBERS_FILE, {})
last_range = {}
last_request_time = {}
seen_skipped = set()  # same number baar baar SKIP log না করার জন্য
seen_group = set()    # group-এ already posted OTP track করার জন্য

# ==================== API TYPE DETECTION ====================

def is_new_api(base_url: str) -> bool:
    """
    base_url দেখে API type detect করে।
    - নতুন (2oo9.cloud):  mauthapi header + /liveaccess, POST /getnum, /console, /success-otp
    - পুরানো (legacy):    ?key=...&action=numbers, GET /getnumber, /console?api_key=, ?action=sms
    """
    if not base_url:
        return False
    markers = ["2oo9.cloud", "@public/api", "mauthapi"]
    return any(m in base_url for m in markers)

# ==================== API FUNCTIONS ====================

async def fetch_top_ranges():
    settings = load_settings()
    api_key = settings.get("api_key")
    base_url = settings.get("base_url").rstrip('/')

    try:
        if is_new_api(base_url):
            # ✅ নতুন API (2oo9.cloud): GET /liveaccess — mauthapi header
            url = f"{base_url}/liveaccess"
            headers = {
                "mauthapi": api_key,
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
            r = await client_async.get(url, headers=headers, timeout=10.0)

            if r.status_code != 200:
                return None, f"HTTP {r.status_code}: Server error"
            try:
                data = r.json()
            except Exception:
                return None, f"JSON parse failed: {r.text[:100]}"

            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            if meta.get("code") != 200:
                return None, f"API Error: {data.get('message', data)}"

            top_ranges = {}
            inner_data = data.get("data", {})
            services_list = inner_data.get("services", []) if isinstance(inner_data, dict) else (inner_data if isinstance(inner_data, list) else [])

            for s_item in services_list:
                if isinstance(s_item, dict):
                    app_raw = s_item.get("sid") or s_item.get("service") or s_item.get("app") or "Unknown"
                    rng_list = s_item.get("ranges", [])
                    app_name = app_raw.strip().title()
                    top_ranges.setdefault(app_name, [])
                    for rng in rng_list:
                        if rng and rng not in top_ranges[app_name]:
                            top_ranges[app_name].append(rng)

            return top_ranges, None

        else:
            # ✅ পুরানো API (legacy): GET ?key=...&action=numbers
            url = f"{base_url}?key={api_key}&action=numbers"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
            r = await client_async.get(url, headers=headers, timeout=10.0)

            if r.status_code != 200:
                return None, f"HTTP {r.status_code}: Server error"
            try:
                data = r.json()
            except Exception:
                return None, f"HTML received instead of JSON: {r.text[:100]}"

            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            top_status = data.get("status") if isinstance(data, dict) else None
            is_ok = (
                top_status in ("success", "ok", True, 1)
                or meta.get("status") in ("success", "ok")
                or meta.get("code") == 200
            )
            if not is_ok and "data" not in data and "services" not in data:
                return None, f"API Error: {data}"

            top_ranges = {}
            inner_data = data.get("data")
            services_list = []

            if isinstance(inner_data, dict):
                services_list = inner_data.get("services") or inner_data.get("ranges") or []
            elif isinstance(inner_data, list):
                services_list = inner_data
            else:
                services_list = data.get("services") or data.get("ranges") or []

            if isinstance(services_list, list):
                for s_item in services_list:
                    if isinstance(s_item, dict):
                        app_raw = s_item.get("sid") or s_item.get("service") or s_item.get("app") or "Unknown"
                        rng_list = s_item.get("ranges", [])
                        app_name = app_raw.strip().title()
                        top_ranges.setdefault(app_name, [])
                        for rng in rng_list:
                            if rng and rng not in top_ranges[app_name]:
                                top_ranges[app_name].append(rng)
            elif isinstance(services_list, dict):
                for app_raw, rng_list in services_list.items():
                    app_name = app_raw.strip().title()
                    top_ranges.setdefault(app_name, [])
                    for rng in rng_list:
                        if rng and rng not in top_ranges[app_name]:
                            top_ranges[app_name].append(rng)

            return top_ranges, None

    except Exception as e:
        return None, str(e)

async def fetch_number_async(range_str):
    try:
        settings = load_settings()
        api_key = settings.get("api_key")
        base_url = settings.get("base_url").rstrip('/')
        clean_rid = clean_range_id(range_str)

        if is_new_api(base_url):
            # ✅ নতুন API (2oo9.cloud): POST /getnum — mauthapi header + JSON body
            url = f"{base_url}/getnum"
            headers = {
                "mauthapi": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
            payload = {"rid": clean_rid}
            r = await client_async.post(url, json=payload, headers=headers, timeout=10.0)

            try:
                data = r.json()
            except:
                return None

            # Envelope: { meta:{code,status}, data:{full_number, national_number, no_plus_number, ...} }
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            if meta.get("code") == 200:
                num_data = data.get("data", {})
                if isinstance(num_data, dict):
                    return (
                        num_data.get("no_plus_number")
                        or num_data.get("national_number")
                        or num_data.get("full_number", "").lstrip("+")
                    )
        else:
            # ✅ পুরানো API (legacy): GET /getnumber?key=...&rid=...
            url = f"{base_url}/getnumber"
            params = {
                "key": api_key,
                "rid": clean_rid,
                "national": 1,
                "remove_plus": 1
            }
            headers = {
                "User-Agent": "Mozilla/5.0"
            }
            r = await client_async.get(url, params=params, headers=headers, timeout=10.0)

            try:
                data = r.json()
            except:
                return None

            if isinstance(data, dict) and data.get("status") == "success":
                return data.get("number") or data.get("phone")

    except Exception as e:
        print(f"[DEBUG] Fetch number error: {e}")
    return None

# ==================== WORKER TASK ====================

async def worker():
    while True:
        task = await request_queue.get()
        try:
            uid = task['uid']
            chat_id = task['chat_id']
            context = task['context']
            range_text = task['range_text']
            app_name = task.get('app_name', 'Facebook')
            del_msg_id  = task.get('delete_msg_id')
            del_chat_id = task.get('delete_chat_id', chat_id)

            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ <b>SEARCHING NUMBER...</b>",
                parse_mode="HTML"
            )

            numbers = []

            # 🔥 3টা unique number fetch (new API: 1 allocation per call)
            seen_nums = set()
            for i in range(3):
                num = await fetch_number_async(range_text)
                if num and num not in seen_nums:
                    seen_nums.add(num)
                    numbers.append(num)

            # ❌ jodi number na pao
            if not numbers:
                await status_msg.edit_text(
                    "❌ <b>NO NUMBER FOUND. TRY AGAIN LATER.</b>",
                    parse_mode="HTML"
                )
                if del_msg_id:
                    try: await context.bot.delete_message(chat_id=del_chat_id, message_id=del_msg_id)
                    except: pass
                continue

            buttons = []

            # 👉 first number diye country info
            first_num = normalize_number(numbers[0])
            flag, c_name = get_country_info(first_num)

            # ✅ HEADER
            icon = get_service_icon(app_name)
            txt = (
                "⏳ These numbers are activated and ready to receive SMS.\n\n"
                f"• <b>Service:</b> {app_name} {icon}\n"
                f"• <b>Country:</b> {flag} {c_name}\n\n"
            )

            # 🔥 NUMBER BUTTONS
            for num in numbers:
                clean_num = normalize_number(num)

                # save number
                active_numbers[clean_num] = {
                    "uid": uid,
                    "range": range_text,
                    "timestamp": datetime.now().isoformat()
                }

                # number button — 1 click copy
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📋 {flag} +{clean_num}",
                        copy_text=CopyTextButton(text=f"+{clean_num}")
                    )
                ])

            save_json(ACTIVE_NUMBERS_FILE, active_numbers)
            add_number_taken(uid, len(numbers))

            settings = load_settings()

            # ✅ Change Country & Change Number buttons
            buttons.append([
                rbtn("🌍 Change Country", callback_data="change_country"),
                rbtn("🔄 Change Number", callback_data="same_range")
            ])

            buttons.append([
                rbtn("📢 OTP Group", url=settings.get("channel_url"))
            ])

            kb = InlineKeyboardMarkup(buttons)

            await status_msg.edit_text(
                txt,
                parse_mode="HTML",
                reply_markup=kb
            )

            # ✅ Intermediate "Searching.../Requesting..." msg auto-delete
            if del_msg_id:
                try: await context.bot.delete_message(chat_id=del_chat_id, message_id=del_msg_id)
                except: pass

        except Exception as e:
            print(f"Worker Exception: {e}")

        finally:
            request_queue.task_done()


# ==================== AUTO MONITOR LOOP ====================

async def monitor_loop(app):
    while True:
        try:
            settings = load_settings()
            api_key = settings.get("api_key")
            base_url = settings.get("base_url").rstrip('/')
            otp_target_raw = settings.get("otp_group_id", "")
            otp_reward = settings.get("otp_reward", 0.0020)

            # otp_group_id কে সঠিক format-এ convert করা (int বা @username)
            try:
                otp_target = int(str(otp_target_raw).strip())
            except:
                otp_target = str(otp_target_raw).strip()


            if api_key:
                if is_new_api(base_url):
                    # ✅ নতুন API (2oo9.cloud): mauthapi header
                    api_headers = {
                        "mauthapi": api_key,
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    }

                    # ── PART 1: GET /console — Global live feed (last 15 min) ──
                    console_otps = []
                    try:
                        rc = await client_async.get(
                            f"{base_url}/console", headers=api_headers, timeout=8.0
                        )
                        rc_data = rc.json()
                        inner = rc_data.get("data", {})
                        if isinstance(inner, dict):
                            console_otps = inner.get("hits") or inner.get("otps") or []
                        elif isinstance(inner, list):
                            console_otps = inner
                    except Exception as ce:
                        print(f"[CONSOLE ERROR] {ce}")

                    # ── PART 2: GET /success-otp — User-এর নিজের last 50 OTP ──
                    otps = []
                    try:
                        rs = await client_async.get(
                            f"{base_url}/success-otp", headers=api_headers, timeout=8.0
                        )
                        res = rs.json()
                        s_meta = res.get("meta", {}) if isinstance(res, dict) else {}
                        if s_meta.get("code") == 200:
                            inner_s = res.get("data", {})
                            if isinstance(inner_s, dict):
                                otps = inner_s.get("otps") or []
                            elif isinstance(inner_s, list):
                                otps = inner_s
                    except Exception as se:
                        print(f"[SUCCESS-OTP ERROR] {se}")

                else:
                    # ✅ পুরানো API (legacy): query params দিয়ে
                    legacy_headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json"
                    }

                    # ── PART 1: GET ?key=...&action=sms — Free global OTP feed ──
                    # (পুরানো API তে dedicated /console নেই, ?action=sms ই global feed)
                    console_otps = []
                    try:
                        rc = await client_async.get(
                            f"{base_url}?key={api_key}&action=sms",
                            headers=legacy_headers, timeout=8.0
                        )
                        rc_data = rc.json()
                        if isinstance(rc_data, dict) and rc_data.get("status") in ("success", "ok", True, 1):
                            console_otps = rc_data.get("otps") or rc_data.get("data") or []
                        elif isinstance(rc_data, list):
                            console_otps = rc_data
                    except Exception as ce:
                        print(f"[CONSOLE ERROR] {ce}")

                    # ── PART 2: same feed — number দিয়ে user match করে reward দেবে ──
                    otps = console_otps  # same data, user match করবে নিচে

                # console OTPs → group only (admin ON/OFF দিয়ে control)
                live_console_enabled = settings.get("live_console_enabled", True)
                if otp_target and console_otps and live_console_enabled:
                    channel_url = settings.get("channel_url", "")
                    for hit in console_otps:
                        if not isinstance(hit, dict): continue
                        full_sms  = (hit.get("message") or "").strip()
                        # new API: sid field | old API: service field
                        service   = (hit.get("sid") or hit.get("service") or "").strip()
                        # new API: range field | old API: number field
                        range_id  = (hit.get("range") or hit.get("number") or "").strip()
                        hit_time  = str(hit.get("time", ""))
                        if not full_sms or not service: continue

                        # ✅ শুধু ALLOWED_SERVICES OTP group-এ যাবে
                        if not is_allowed_service(service):
                            continue

                        otp_code = extract_otp(full_sms)
                        if not otp_code or otp_code == "N/A": continue

                        # unique dedup key — range/number + otp + time
                        c_otp_id = f"console_{range_id}_{otp_code}_{hit_time}"
                        if c_otp_id in seen_group: continue
                        seen_group.add(c_otp_id)

                        svc_icon      = get_service_icon(service)
                        service_title = service.title()
                        # country: range এর XXX সরিয়ে বা number থেকে বের করো
                        lookup_num    = range_id.replace("X", "").replace("x", "")
                        flag, c_name  = get_country_info(lookup_num)

                        # display label — range (22501XXX) বা masked number
                        display_id = range_id if "X" in range_id.upper() else mask_number(range_id)

                        group_msg = (
                            f"{svc_icon} <b>{service_title}</b> • {flag} {c_name}\n"
                            f"📞 <code>{display_id}</code>\n\n"
                            f"🔔 {html.escape(full_sms)}"
                        )
                        group_kb_buttons = [
                            InlineKeyboardButton(
                                text=f"📋 {otp_code}",
                                copy_text=CopyTextButton(text=otp_code)
                            )
                        ]
                        if channel_url:
                            group_kb_buttons.append(
                                InlineKeyboardButton("🤖 OTP Group", url=channel_url)
                            )
                        kb = InlineKeyboardMarkup([group_kb_buttons])
                        try:
                            await app.bot.send_message(
                                otp_target, group_msg,
                                parse_mode="HTML", reply_markup=kb
                            )
                        except Exception as e:
                            print(f"[ERROR] Console→Group: {e}")

                if otps:
                    paid_data = load_json(PAID_SMS_FILE, {})
                    for otp in otps:
                        if not isinstance(otp, dict): continue

                        num = normalize_number(
                            otp.get("number") or otp.get("phone") or ""
                        )
                        if not num:
                            continue

                        full_sms = (
                            otp.get("message") or otp.get("sms") or
                            otp.get("text") or otp.get("body") or otp.get("content") or ""
                        ).strip()

                        otp_code = (otp.get("code") or otp.get("otp_code") or "").strip()
                        if not otp_code and full_sms:
                            otp_code = extract_otp(full_sms)

                        # time-based unique ID (API-এর time field ব্যবহার)
                        otp_time = str(otp.get("time", ""))
                        otp_id = str(otp.get("otp_id", f"{num}_{otp_code}_{otp_time}"))

                        if not full_sms or not otp_code or otp_code == "N/A":
                            if otp_id not in seen_skipped:
                                seen_skipped.add(otp_id)
                                print(f"[SKIP] num={num} | no real OTP content.")
                            continue

                        flag, c_name = get_country_info(num)
                        service = detect_service(full_sms)

                        # ✅ শুধু ALLOWED_SERVICES process হবে
                        if not is_allowed_service(service):
                            if otp_id not in seen_skipped:
                                seen_skipped.add(otp_id)
                            continue

                        svc_icon = get_service_icon(service)
                        service_title = service.title()
                        masked_num = mask_number(num)
                        channel_url = settings.get("channel_url", "")

                        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        # ✅ সব OTP → OTP Group-এ post (seen_group দিয়ে duplicate avoid)
                        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        if otp_target and otp_id not in seen_group:
                            seen_group.add(otp_id)
                            group_msg = (
                                f"{svc_icon} <b>{service_title}</b> • 🌐 English\n"
                                f"{flag} {c_name} • <code>{masked_num}</code>\n\n"
                                f"🔔 {html.escape(full_sms)}"
                            )
                            group_kb_buttons = [
                                InlineKeyboardButton(
                                    text=f"📋 {otp_code}",
                                    copy_text=CopyTextButton(text=otp_code)
                                )
                            ]
                            if channel_url:
                                group_kb_buttons.append(
                                    InlineKeyboardButton("🤖 OTP Group", url=channel_url)
                                )
                            kb = InlineKeyboardMarkup([group_kb_buttons])
                            try:
                                await app.bot.send_message(
                                    otp_target, group_msg,
                                    parse_mode="HTML", reply_markup=kb
                                )
                                print(f"[GROUP] {service_title} | {num} | otp={otp_code}")
                            except Exception as e:
                                print(f"[ERROR] Group post failed ({otp_target}): {e}")

                        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        # ✅ User-এর number হলে → reward + personal notification
                        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        if num in active_numbers and otp_id not in paid_data:
                            details = active_numbers[num]
                            user_id = details["uid"]
                            paid_data[otp_id] = True
                            save_json(PAID_SMS_FILE, paid_data)

                            await update_db_balance(user_id, otp_reward)
                            add_otp_received(user_id)
                            log_global_activity(user_id, "OTP_RECEIVED", {
                                "number": num, "otp": otp_code, "sms": full_sms
                            })

                            user_msg = (
                                f"{svc_icon} <b>{service_title}</b> • 🌐 OTP\n"
                                f"{flag} {c_name} • <code>+{num}</code>\n\n"
                                f"🔔 <b>{html.escape(full_sms)}</b>\n\n"
                                f"💰 <b>Bonus:</b> <code>+{otp_reward:.4f}$ Credited</code>"
                            )
                            user_kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    text=f"📋 {otp_code}",
                                    copy_text=CopyTextButton(text=otp_code)
                                )
                            ]])
                            try:
                                await app.bot.send_message(
                                    int(user_id), user_msg,
                                    parse_mode="HTML", reply_markup=user_kb
                                )
                                print(f"[USER] Sent to {user_id} | num=+{num} | otp={otp_code}")
                            except Exception as e:
                                print(f"[ERROR] User notify failed ({user_id}): {e}")

        except Exception as e:
            print(f"[monitor_loop ERROR] {e}")
        await asyncio.sleep(1.0)

# ==================== MAIN HANDLER ====================
async def is_user_member(bot, user_id, channel):
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception:
        return False

async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if is_admin(uid):
        return True  # অ্যাডমিনদের চেক করবে না

    settings = load_settings()
    if not settings.get("force_join_enabled", False):
        return True

    channels = settings.get("force_join_channels", [])
    if not channels:
        return True

    not_joined = []
    for ch in channels:
        joined = await is_user_member(context.bot, uid, ch)
        if not joined:
            not_joined.append(ch)

    if not_joined:
        buttons = []
        for ch in not_joined:
            clean_ch = ch.replace("@", "")
            buttons.append([rbtn(f"📢 Join {ch}", style="primary", url=f"https://t.me/{clean_ch}")])
        buttons.append([rbtn("🔄 Verify / Check", style="success", callback_data="check_join")])

        msg = (
            "⚠️ <b>বটটি ব্যবহার করতে আমাদের চ্যানেলে জয়েন করুন!</b>\n\n"
            "দয়া করে নিচের চ্যানেলে জয়েন হয়ে <b>Verify / Check</b> বাটনে ক্লিক করুন:"
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return False

    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    uid = update.effective_user.id
    username = update.effective_user.username
    full_name = update.effective_user.full_name
    
    users_db = load_json(USER_DATA_FILE, {})
    is_new = str(uid) not in users_db
    user_data = get_user(uid, username, full_name)
    
    # Referral Tracking
    if context.args and is_new:
        referrer_id = str(context.args[0])
        if referrer_id != str(uid) and referrer_id in users_db:
            settings = load_settings()
            bonus = settings.get("refer_bonus", 0.05)
            
            user_data["referred_by"] = referrer_id
            save_json(USER_DATA_FILE, users_db)
            
            # Reward Referrer
            await update_db_balance(referrer_id, bonus)
            ref_user = users_db[referrer_id]
            ref_user["referrals"] = ref_user.get("referrals", 0) + 1
            ref_user["referral_earnings"] = round(ref_user.get("referral_earnings", 0.0) + bonus, 4)
            save_json(USER_DATA_FILE, users_db)
            
            try:
                await context.bot.send_message(
                    int(referrer_id),
                    f"🎁 <b>New Referral Bonus!</b>\n\nUser: {html.escape(full_name or 'N/A')}\nEarned: <code>+{bonus}$</code>",
                    parse_mode="HTML"
                )
            except: pass

    settings = load_settings()
    text = settings.get("welcome_message") or "👋 Welcome to AutoSyncX Bot!"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(uid)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    uid = update.effective_user.id
    raw_text = update.message.text.strip()
    text = unstyle_text(raw_text)

    if is_user_banned(uid):
        await update.message.reply_text("🚫 <b>YOU ARE BANNED FROM USING THIS BOT!</b>", parse_mode="HTML")
        return
    if not await check_force_sub(update, context):
        return

    if text == "❌ CANCEL":
        context.user_data.clear()
        await update.message.reply_text("Action cancelled.", reply_markup=main_keyboard(uid))
        return

    # --- WITHDRAW INPUT MODE ---
    w_mode = context.user_data.get("withdraw_mode")
    if w_mode == "amount":
        try:
            amount = float(text)
            settings = load_settings()
            min_w, max_w = settings.get("min_withdraw", 0.5), settings.get("max_withdraw", 100.0)
            u_bal = get_user(uid)["balance"]
            
            if amount < min_w or amount > max_w:
                await update.message.reply_text(f"❌ Invalid amount! Limit: {min_w}$ - {max_w}$", reply_markup=cancel_keyboard())
                return
            if amount > u_bal:
                await update.message.reply_text("❌ Insufficient balance!", reply_markup=cancel_keyboard())
                return
                
            context.user_data["withdraw_amount"] = amount
            context.user_data["withdraw_mode"] = "number"
            await update.message.reply_text("📱 Enter your Account Number (e.g., 017XXXXXXXX):", reply_markup=cancel_keyboard())
            return
        except:
            await update.message.reply_text("❌ Send a valid numeric amount!", reply_markup=cancel_keyboard())
            return

    if w_mode == "number":
        method = context.user_data.get("withdraw_method")
        amount = context.user_data.get("withdraw_amount")
        payment_num = text
        pid = generate_payment_id()
        
        # Deduct Balance
        await update_db_balance(uid, -amount)
        
        w_requests = load_json(WITHDRAW_DATA_FILE, {})
        w_requests[pid] = {
            "user_id": uid, "method": method, "amount": amount,
            "number": payment_num, "payment_id": pid, "status": "pending",
            "timestamp": datetime.now().isoformat()
        }
        save_json(WITHDRAW_DATA_FILE, w_requests)
        
        context.user_data.clear()
        await update.message.reply_text("✅ <b>Withdrawal Request Submitted to Admin!</b>", parse_mode="HTML", reply_markup=main_keyboard(uid))
        
        # Notify Admins
        admin_msg = (
            f"💰 <b>NEW WITHDRAWAL REQUEST</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
            f"⚙️ <b>Method:</b> {method}\n"
            f"📞 <b>Number:</b> <code>{payment_num}</code>\n"
            f"💵 <b>Amount:</b> <code>{amount}$</code>\n"
            f"🆔 <b>PID:</b> <code>{pid}</code>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{pid}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{pid}")]
        ])
        for a_id in ADMINS:
            try: await context.bot.send_message(a_id, admin_msg, parse_mode="HTML", reply_markup=kb)
            except: pass
        return

    # --- ADMIN EDIT MODES ---
    edit_mode = context.user_data.get("admin_edit_mode")
    if edit_mode and is_admin(uid):
        settings = load_settings()
        context.user_data["admin_edit_mode"] = None
        
        if edit_mode == "api_key":
            settings["api_key"] = raw_text
            save_settings(settings)
            await update.message.reply_text("✅ API Key updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "base_url":
            settings["base_url"] = raw_text
            save_settings(settings)
            await update.message.reply_text("✅ API Base URL updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "otp_channel":
            settings["otp_group_id"] = raw_text
            save_settings(settings)
            await update.message.reply_text(f"✅ OTP Channel ID set to: <code>{raw_text}</code>", parse_mode="HTML", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "withdraw_limits":
            parts = raw_text.split()
            if len(parts) == 2:
                settings["min_withdraw"] = float(parts[0])
                settings["max_withdraw"] = float(parts[1])
                save_settings(settings)
                await update.message.reply_text(f"✅ Limits set: Min {parts[0]}$ | Max {parts[1]}$", reply_markup=admin_system_config_keyboard())
            else:
                await update.message.reply_text("❌ Invalid format! Example: 0.5 100")
        elif edit_mode == "refer_bonus":
            settings["refer_bonus"] = float(raw_text)
            save_settings(settings)
            await update.message.reply_text("✅ Referral bonus updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "cooldown":
            settings["cooldown_time"] = float(raw_text)
            save_settings(settings)
            await update.message.reply_text("✅ Cooldown updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "welcome":
            settings["welcome_message"] = raw_text
            save_settings(settings)
            await update.message.reply_text("✅ Welcome Message updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "support":
            settings["support_username"] = raw_text.replace("@", "")
            save_settings(settings)
            await update.message.reply_text("✅ Support username updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "channel_link":
            settings["channel_url"] = raw_text
            save_settings(settings)
            await update.message.reply_text("✅ Channel link updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "add_balance":
            parts = raw_text.split()
            if len(parts) == 2 and parts[0].isdigit():
                t_uid, amt = parts[0], float(parts[1])
                new_b = await update_db_balance(t_uid, amt)
                await update.message.reply_text(f"✅ Added {amt}$ to User {t_uid}. New Balance: {new_b}$", reply_markup=admin_user_balance_keyboard())
            else:
                await update.message.reply_text("❌ Format: USER_ID AMOUNT", reply_markup=admin_user_balance_keyboard())
        elif edit_mode == "remove_balance":
            parts = raw_text.split()
            if len(parts) == 2 and parts[0].isdigit():
                t_uid, amt = parts[0], float(parts[1])
                new_b = await update_db_balance(t_uid, -amt)
                await update.message.reply_text(f"✅ Removed {amt}$ from User {t_uid}. New Balance: {new_b}$", reply_markup=admin_user_balance_keyboard())
            else:
                await update.message.reply_text("❌ Format: USER_ID AMOUNT", reply_markup=admin_user_balance_keyboard())
        elif edit_mode == "ban_user":
            if ban_user(raw_text):
                await update.message.reply_text(f"✅ User {raw_text} banned!", reply_markup=admin_security_join_keyboard())
            else:
                await update.message.reply_text("❌ User already banned!")
        elif edit_mode == "add_force_channel":
            ch = raw_text.strip()
            channels = settings.get("force_join_channels", [])
            if ch not in channels:
                channels.append(ch)
                settings["force_join_channels"] = channels
                settings["force_join_enabled"] = True
                save_settings(settings)
                await update.message.reply_text(f"✅ Channel <code>{ch}</code> যোগ করা হয়েছে!", parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
            else:
                await update.message.reply_text("❌ এই চ্যানেলটি আগেই তালিকায় রয়েছে!", reply_markup=admin_force_channel_keyboard())
        elif edit_mode == "del_force_channel":
            ch = raw_text.strip()
            channels = settings.get("force_join_channels", [])
            if ch in channels:
                channels.remove(ch)
                settings["force_join_channels"] = channels
                save_settings(settings)
                await update.message.reply_text(f"✅ Channel <code>{ch}</code> তালিকা থেকে মুছে ফেলা হয়েছে!", parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
            else:
                await update.message.reply_text("❌ চ্যানেলটি তালিকায় পাওয়া যায়নি!", reply_markup=admin_force_channel_keyboard())
                
        elif edit_mode == "direct_msg":
            parts = raw_text.split(maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit():
                try:
                    await context.bot.send_message(int(parts[0]), f"💬 <b>MESSAGE FROM ADMIN:</b>\n\n{parts[1]}", parse_mode="HTML")
                    await update.message.reply_text("✅ Message sent!")
                except Exception as e:
                    await update.message.reply_text(f"❌ Failed: {e}")
            else:
                await update.message.reply_text("❌ Format: USER_ID MESSAGE")
        elif edit_mode == "broadcast":
            users = load_json(USER_DATA_FILE, {})
            succ, fail = 0, 0
            msg = await update.message.reply_text("📢 Broadcasting started...")
            for u_id in users.keys():
                try:
                    await context.bot.send_message(int(u_id), f"📢 <b>ANNOUNCEMENT:</b>\n\n{raw_text}", parse_mode="HTML")
                    succ += 1
                except: fail += 1
                await asyncio.sleep(0.04)
            await msg.edit_text(f"✅ Broadcast complete!\nSuccess: {succ} | Failed: {fail}")
        return

    # --- USER BUTTON COMMANDS ---
    if "GET NUMBER" in raw_text.upper():
        status = await update.message.reply_text("⏳ Loading Services...")
        top_ranges, err = await fetch_top_ranges()
        if err or not top_ranges:
            err_msg = err if err else "No active services returned from API"
            await status.edit_text(f"❌ Could not fetch ranges from server.\n\n🔍 <b>Reason:</b> <code>{err_msg}</code>", parse_mode="HTML")
            return

        # ✅ শুধু ALLOWED_SERVICES দেখাবে
        filtered_ranges = {
            app: ranges
            for app, ranges in top_ranges.items()
            if is_allowed_service(app)
        }

        if not filtered_ranges:
            await status.edit_text("❌ <b>No active services available right now.</b>\n<i>Try again later.</i>", parse_mode="HTML")
            return

        context.user_data["top_ranges"] = filtered_ranges
        buttons = []
        row = []
        for app_name in filtered_ranges.keys():
            icon = get_service_icon(app_name)
            pct = get_service_percentage(app_name)
            button_label = f"{icon} {app_name} ({pct})"
            row.append(rbtn(button_label, style="primary", callback_data=f"sel_app_{app_name}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await status.edit_text("<b>Select Service:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if text == "💵 BALANCE" or text == "BALANCE":
        u_info = get_user(uid)
        settings = load_settings()
        m_method = u_info.get("withdrawal_method") or "Not Set"
        
        bal_text = (
            f"💵 <b>YOUR ACCOUNT BALANCE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Balance:</b> <code>{u_info['balance']:.4f}$</code>\n"
            f"⚙️ <b>Withdraw Method:</b> <code>{m_method}</code>\n"
            f"📉 <b>Min Withdraw:</b> <code>{settings['min_withdraw']}$</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([
            [rbtn("💳 Set Payment Method", style="primary", callback_data="set_method")],
            [rbtn("💸 Withdraw Money", style="success", callback_data="init_withdraw")]
        ])
        await update.message.reply_text(bal_text, parse_mode="HTML", reply_markup=kb)
        return

    if text == "🎁 REFER & EARN" or text == "REFER & EARN":
        settings = load_settings()
        b_info = await context.bot.get_me()
        ref_link = f"https://t.me/{b_info.username}?start={uid}"
        u_info = get_user(uid)
        
        ref_msg = (
            f"🎁 <b>REFER & EARN PROGRAM</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Your Referral Link:</b>\n<code>{ref_link}</code>\n\n"
            f"👥 <b>Total Referrals:</b> {u_info.get('referrals', 0)}\n"
            f"💰 <b>Referral Earnings:</b> {u_info.get('referral_earnings', 0.0):.4f}$\n"
            f"🎁 <b>Per Referral Bonus:</b> {settings['refer_bonus']:.4f}$\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(ref_msg, parse_mode="HTML")
        return

    if text == "📡 LIVE CONSOLE" or text == "LIVE CONSOLE":
        settings = load_settings()
        if not settings.get("live_console_enabled", True):
            await update.message.reply_text(
                "🔴 <b>LIVE CONSOLE is currently disabled.</b>\n<i>Contact admin for more info.</i>",
                parse_mode="HTML"
            )
            return

        api_key = settings.get("api_key")
        base_url = settings.get("base_url", "").rstrip('/')

        if not api_key:
            await update.message.reply_text("❌ <b>API key not configured.</b>", parse_mode="HTML")
            return

        wait_msg = await update.message.reply_text("📡 <b>Fetching Live Console...</b>", parse_mode="HTML")

        try:
            if is_new_api(base_url):
                headers = {"mauthapi": api_key, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
                r = await client_async.get(f"{base_url}/console", headers=headers, timeout=8.0)
            else:
                r = await client_async.get(f"{base_url}/console?api_key={api_key}", timeout=8.0)

            data = r.json()
            inner = data.get("data", {})
            hits = []
            if isinstance(inner, dict):
                hits = inner.get("hits") or inner.get("otps") or []
            elif isinstance(inner, list):
                hits = inner

            if not hits:
                await wait_msg.edit_text("📡 <b>Live Console</b>\n\n<i>No recent hits in the last 15 minutes.</i>", parse_mode="HTML")
                return

            lines = ["📡 <b>Live Console</b> • Last 15 Min\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]
            for hit in hits[:15]:  # max 15 দেখাবে
                if not isinstance(hit, dict): continue
                full_sms  = (hit.get("message") or "").strip()
                service   = (hit.get("sid") or hit.get("service") or "Unknown").strip()
                range_id  = (hit.get("range") or hit.get("number") or "").strip()

                if not full_sms: continue

                otp_code  = extract_otp(full_sms)
                svc_icon  = get_service_icon(service)
                flag, c_name = get_country_info(range_id.replace("X", ""))

                otp_part = f"  🔑 <code>{otp_code}</code>" if otp_code and otp_code != "N/A" else ""
                lines.append(
                    f"{svc_icon} <b>{html.escape(service.title())}</b> • {flag} {c_name}\n"
                    f"  📩 {html.escape(full_sms[:80])}{'…' if len(full_sms) > 80 else ''}"
                    f"{otp_part}"
                )
                lines.append("─────────────────────")

            channel_url = settings.get("channel_url", "")
            kb = None
            if channel_url:
                kb = InlineKeyboardMarkup([[rbtn("📢 OTP Group", url=channel_url)]])

            await wait_msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)

        except Exception as e:
            await wait_msg.edit_text(f"❌ <b>Error fetching console:</b> <code>{e}</code>", parse_mode="HTML")
        return


    if text == "📊 TRAFFIC" or text == "TRAFFIC":
        settings = load_settings()
        if not settings.get("traffic_enabled", True):
            await update.message.reply_text(
                "🔴 <b>TRAFFIC feature is currently disabled.</b>\n<i>Contact admin for more info.</i>",
                parse_mode="HTML"
            )
            return

        logs = load_json(ACTIVITY_LOGS_FILE, [])
        one_h_ago = datetime.now() - timedelta(hours=1)
        
        counts = {}
        total = 0
        for log in logs:
            if log.get("action") == "OTP_RECEIVED":
                try:
                    ts = datetime.fromisoformat(log.get("timestamp"))
                    if ts >= one_h_ago:
                        dtls = log.get("details", {})
                        num, sms = dtls.get("number"), dtls.get("sms")
                        srv = detect_service(sms)
                        flag, cname = get_country_info(num)
                        key = (srv, flag, cname)
                        counts[key] = counts.get(key, 0) + 1
                        total += 1
                except: pass
                
        if total == 0:
            await update.message.reply_text("📊 <b>Live Traffic (Last 1 Hour)</b>\n\n<i>No OTP transactions in the last hour.</i>", parse_mode="HTML")
            return
            
        lines = ["📊 <b>Live Traffic (Last 1 Hour)</b>\n"]
        for (srv, flag, cname), count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total) * 100
            lines.append(f"📱 <b>{srv}</b> | {flag} {cname} | {pct:.1f}%")
            
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if text == "🏆 LEADERBOARD" or text == "LEADERBOARD":
        settings = load_settings()
        if not settings.get("leaderboard_enabled", True):
            await update.message.reply_text(
                "🔴 <b>LEADERBOARD feature is currently disabled.</b>\n<i>Contact admin for more info.</i>",
                parse_mode="HTML"
            )
            return

        stats = load_json(STATS_FILE, {})
        users = load_json(USER_DATA_FILE, {})
        
        ranked = []
        for u_id, s_data in stats.items():
            cnt = len(s_data.get("otps_received", []))
            if cnt > 0: ranked.append((u_id, cnt))
            
        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)[:10]
        
        lines = ["🏆 <b>OTP LEADERBOARD TOP 10</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        if ranked:
            for idx, (r_uid, count) in enumerate(ranked, 1):
                u_name = users.get(str(r_uid), {}).get("full_name") or f"User ({r_uid[-4:]})"
                lines.append(f"<b>#{idx}</b> {html.escape(u_name)} - <code>{count} OTPs</code>")
        else:
            lines.append("<i>No OTP record available yet.</i>")
            
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if text == "💬 SUPPORT" or text == "SUPPORT":
        settings = load_settings()
        sup = settings.get("support_username")
        kb = InlineKeyboardMarkup([[rbtn("📩 Contact Support", style="primary", url=f"https://t.me/{sup}")]])
        await update.message.reply_text("💬 Need help? Click below to contact support:", reply_markup=kb)
        return

    # --- ADMIN MAIN MENU CATEGORIES ---
    if (text == "⚙️ ADMIN PANEL" or text == "ADMIN PANEL") and is_admin(uid):
        await update.message.reply_text("⚙️ <b>ADMIN CONTROL PANEL</b>", parse_mode="HTML", reply_markup=admin_main_keyboard())
        return

    if text == "⚙️ SYSTEM CONFIG" and is_admin(uid):
        await update.message.reply_text("⚙️ <b>SYSTEM CONFIGURATION</b>", parse_mode="HTML", reply_markup=admin_system_config_keyboard())
        return

    if text == "💵 USER & BALANCE" and is_admin(uid):
        await update.message.reply_text("💵 <b>USER & BALANCE MANAGEMENT</b>", parse_mode="HTML", reply_markup=admin_user_balance_keyboard())
        return

    if "SECURITY & JOIN" in text and is_admin(uid):
        await update.message.reply_text("🔒 <b>SECURITY & JOIN CONTROLS</b>", parse_mode="HTML", reply_markup=admin_security_join_keyboard())
        return

    if "FORCE CHANNELS" in text and is_admin(uid):
        settings = load_settings()
        ch_list = settings.get("force_join_channels", [])
        channels_text = "\n".join([f"• <code>{c}</code>" for c in ch_list]) if ch_list else "<i>কোনো চ্যানেল সেট করা নেই</i>"
        msg = f"📢 <b>FORCE JOIN CHANNELS:</b>\n\n<b>বর্তমান চ্যানেলসমূহ:</b>\n{channels_text}"
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
        return

    if "ADD CHANNEL" in text and is_admin(uid):
        context.user_data["admin_edit_mode"] = "add_force_channel"
        await update.message.reply_text("চ্যানেলের ইউজারনেম দিন (যেমন: <code>@yourchannel</code>):", parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    if "DELETE CHANNEL" in text and is_admin(uid):
        context.user_data["admin_edit_mode"] = "del_force_channel"
        settings = load_settings()
        ch_list = settings.get("force_join_channels", [])
        channels_text = "\n".join([f"• <code>{c}</code>" for c in ch_list]) if ch_list else "<i>কোনো চ্যানেল নেই</i>"
        await update.message.reply_text(f"যে চ্যানেলটি বাদ দিতে চান তার ইউজারনেম লিখুন:\n\n{channels_text}", parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    if "BACK TO SECURITY" in text and is_admin(uid):
        await update.message.reply_text("🔒 <b>SECURITY & JOIN CONTROLS</b>", parse_mode="HTML", reply_markup=admin_security_join_keyboard())
        return
    if text == "📢 NOTICE & B-CAST" and is_admin(uid):
        await update.message.reply_text("📢 <b>NOTICE & BROADCASTING</b>", parse_mode="HTML", reply_markup=admin_notice_bcast_keyboard())
        return

    # --- ADMIN SYSTEM CONFIG ---
    if text == "🔑 SET API KEY" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "api_key"
        await update.message.reply_text("Enter new API Key:", reply_markup=cancel_keyboard())
        return

    if text == "🌐 SET API BASE URL" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "base_url"
        await update.message.reply_text("Enter new API Base URL:", reply_markup=cancel_keyboard())
        return

    if text == "📢 SET OTP CHANNEL ID" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "otp_channel"
        await update.message.reply_text("Enter OTP Channel ID (e.g. -100xxxxxxxxxx or @channel):", reply_markup=cancel_keyboard())
        return

    if text == "💰 SET WITHDRAW LIMITS" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "withdraw_limits"
        await update.message.reply_text("Enter MIN and MAX withdraw limit separated by space (e.g. 0.5 100):", reply_markup=cancel_keyboard())
        return

    if text == "🎁 SET REFER BONUS" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "refer_bonus"
        await update.message.reply_text("Enter Referral Bonus Amount (e.g. 0.05):", reply_markup=cancel_keyboard())
        return

    if text == "⏱ SET COOLDOWN" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "cooldown"
        await update.message.reply_text("Enter Number Request Cooldown (in seconds):", reply_markup=cancel_keyboard())
        return

    if text == "🚫 TOGGLE MAINTENANCE" and is_admin(uid):
        settings = load_settings()
        settings["maintenance_mode"] = not settings.get("maintenance_mode", False)
        save_settings(settings)
        status = "ENABLED" if settings["maintenance_mode"] else "DISABLED"
        await update.message.reply_text(f"🛠 Maintenance Mode is now: <b>{status}</b>", parse_mode="HTML")
        return

    # ✅ Live Console ON/OFF toggle (শুধু Admin)
    if ("LIVE CONSOLE" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("live_console_enabled", True)
        settings["live_console_enabled"] = not current
        save_settings(settings)
        new_state = settings["live_console_enabled"]
        icon = "🟢" if new_state else "🔴"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>Live Console Facebook OTP:</b> <b>{state_text}</b>\n\n"
            f"{'✅ এখন Facebook OTP group-এ আসবে।' if new_state else '⛔ Facebook OTP group-এ আসবে না।'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    # ✅ Traffic ON/OFF toggle (শুধু Admin)
    if ("TRAFFIC:" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("traffic_enabled", True)
        settings["traffic_enabled"] = not current
        save_settings(settings)
        new_state = settings["traffic_enabled"]
        icon = "🟢" if new_state else "🔴"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>TRAFFIC Feature:</b> <b>{state_text}</b>\n\n"
            f"{'✅ Users can now see Traffic.' if new_state else '⛔ Traffic is hidden from users.'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    # ✅ Leaderboard ON/OFF toggle (শুধু Admin)
    if ("LEADERBOARD:" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("leaderboard_enabled", True)
        settings["leaderboard_enabled"] = not current
        save_settings(settings)
        new_state = settings["leaderboard_enabled"]
        icon = "🟢" if new_state else "🔴"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>LEADERBOARD Feature:</b> <b>{state_text}</b>\n\n"
            f"{'✅ Users can now see Leaderboard.' if new_state else '⛔ Leaderboard is hidden from users.'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    # --- ADMIN USER & BALANCE ---
    if text == "➕ ADD BALANCE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "add_balance"
        await update.message.reply_text("Enter USER_ID and AMOUNT (e.g. 123456789 5.0):", reply_markup=cancel_keyboard())
        return

    if text == "➖ REMOVE BALANCE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "remove_balance"
        await update.message.reply_text("Enter USER_ID and AMOUNT (e.g. 123456789 2.0):", reply_markup=cancel_keyboard())
        return

    if text == "💬 DIRECT MSG USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "direct_msg"
        await update.message.reply_text("Enter USER_ID and MESSAGE (e.g. 123456789 Hello):", reply_markup=cancel_keyboard())
        return

    if text == "🔍 SEARCH BY USERNAME" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "search_username"
        await update.message.reply_text("Enter Telegram Username (without @):", reply_markup=cancel_keyboard())
        return

    if text == "📜 ALL USER BALANCE" and is_admin(uid):
        users = load_json(USER_DATA_FILE, {})
        tot_bal = sum(u.get("balance", 0.0) for u in users.values())
        lines = [f"Total Users: {len(users)} | Total Balance: {tot_bal:.4f}$\n"]
        for idx, (u_id, u_data) in enumerate(users.items(), 1):
            lines.append(f"{idx}. ID: {u_id} | Bal: {u_data.get('balance', 0.0):.4f}$")
        
        file_io = io.BytesIO("\n".join(lines).encode('utf-8'))
        file_io.name = "All_Users_Balance.txt"
        await update.message.reply_document(file_io, caption=f"📊 Total System Balance: {tot_bal:.4f}$")
        return

    # --- ADMIN SECURITY & NOTICE ---
    if text == "🚫 BAN USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "ban_user"
        await update.message.reply_text("Enter USER_ID to ban:", reply_markup=cancel_keyboard())
        return

    if text == "✅ UNBAN USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "unban_user"
        await update.message.reply_text("Enter USER_ID to unban:", reply_markup=cancel_keyboard())
        return

    if text == "📜 BAN USER LIST" and is_admin(uid):
        banned = load_json(BANNED_USERS_FILE, [])
        await update.message.reply_text(f"🚫 <b>Banned Users ({len(banned)}):</b>\n\n" + "\n".join(banned), parse_mode="HTML")
        return

    if text == "📢 BROADCAST NOTICE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "broadcast"
        await update.message.reply_text("Enter text to broadcast to all users:", reply_markup=cancel_keyboard())
        return

    if text == "📝 SET WELCOME MSG" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "welcome"
        await update.message.reply_text("Enter Welcome Text (HTML Supported):", reply_markup=cancel_keyboard())
        return

    if text == "💬 SET SUPPORT USERNAME" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "support"
        await update.message.reply_text("Enter Support Telegram Username:", reply_markup=cancel_keyboard())
        return

    if text == "🔗 SET CHANNEL LINK" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "channel_link"
        await update.message.reply_text("Enter Channel Link:", reply_markup=cancel_keyboard())
        return

    if text in ["🔙 BACK TO ADMIN", "BACK TO ADMIN", "🔙 BACK TO MAIN", "BACK TO MAIN"]:
        await update.message.reply_text("Main Menu.", reply_markup=main_keyboard(uid))
        return

# ==================== CALLBACK QUERY HANDLER ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    if data == "check_join":
        if await check_force_sub(update, context):
            try:
                await query.message.delete()
            except:
                pass
            await query.message.reply_text("✅ ধন্যবাদ! সফলভাবে যাচাই করা হয়েছে।", reply_markup=main_keyboard(uid))
        else:
            await query.answer("❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
        return

    # ১. সার্ভিস সিলেক্ট করলে -> দেশের তালিকা (পতাকা সহ) দেখাবে
    if data.startswith("sel_app_"):
        app_name = data.replace("sel_app_", "")
        top_ranges = context.user_data.get("top_ranges", {})
        ranges = top_ranges.get(app_name, [])
        if not ranges:
            await query.edit_message_text("❌ No ranges available for this service.")
            return

        # দেশের নাম ও পতাকা অনুযায়ী রেঞ্জগুলো ভাগ করা
        country_map_data = {}
        for rng in ranges:
            flag, cname = get_country_info(rng)
            c_key = f"{flag} {cname}"
            if c_key not in country_map_data:
                country_map_data[c_key] = []
            country_map_data[c_key].append(rng)

        if "country_ranges" not in context.user_data:
            context.user_data["country_ranges"] = {}

        # Save current app for change_country later
        context.user_data["current_app"] = app_name

        buttons = []
        row = []
        for c_label, rng_list in country_map_data.items():
            c_idx = str(len(context.user_data["country_ranges"]) + 1)
            context.user_data["country_ranges"][c_idx] = {
                "app": app_name,
                "label": c_label,
                "ranges": rng_list
            }
            row.append(rbtn(c_label, style="primary", callback_data=f"sel_cty_{c_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)

        buttons.append([rbtn("🔙 Back to Services", style="danger", callback_data="back_to_services")])
        await query.edit_message_text(f"🌐 <b>Select Country for {app_name}:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ২. দেশ সিলেক্ট করলে -> ওই দেশের নম্বর রিকোয়েস্ট করবে
    if data.startswith("sel_cty_"):
        c_idx = data.replace("sel_cty_", "")
        c_info = context.user_data.get("country_ranges", {}).get(c_idx)
        if not c_info:
            await query.edit_message_text("❌ Session expired. Please click GET NUMBER again.")
            return

        app_name = c_info["app"]
        country_label = c_info["label"]
        ranges = c_info["ranges"]

        selected_range = random.choice(ranges)
        last_range[uid] = selected_range
        context.user_data["current_app"] = app_name

        await query.edit_message_text(f"⏳ <b>Searching number for {app_name} ({country_label})...</b>", parse_mode="HTML")
        await request_queue.put({
            'uid': uid,
            'chat_id': query.message.chat_id,
            'context': context,
            'range_text': selected_range,
            'app_name': app_name,
            'delete_msg_id': query.message.message_id,
            'delete_chat_id': query.message.chat_id
        })
        return

    # ৩. ব্যাক বাটনে ক্লিক করলে -> সার্ভিসের তালিকা দেখাবে
    if data == "back_to_services":
        top_ranges = context.user_data.get("top_ranges", {})
        if not top_ranges:
            await query.edit_message_text("❌ Session expired. Please click GET NUMBER again.")
            return
        buttons = []
        row = []
        for app_name in top_ranges.keys():
            icon = get_service_icon(app_name)
            pct = get_service_percentage(app_name)
            button_label = f"{icon} {app_name} ({pct})"
            row.append(rbtn(button_label, style="primary", callback_data=f"sel_app_{app_name}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await query.edit_message_text("<b>Select Service:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ৪. Change Country বাটন -> দেশের তালিকা দেখাবে (API থেকে)
    if data == "change_country":
        app_name = context.user_data.get("current_app", "")
        top_ranges = context.user_data.get("top_ranges", {})
        
        # যদি top_ranges না থাকে, API থেকে নতুন করে আনবে
        if not top_ranges:
            top_ranges, err = await fetch_top_ranges()
            if err or not top_ranges:
                await query.answer("❌ Could not load services. Try again.", show_alert=True)
                return
            context.user_data["top_ranges"] = top_ranges

        # যদি current app না থাকে, সার্ভিস সিলেক্ট করতে বলবে
        if not app_name or app_name not in top_ranges:
            # Show service selection
            buttons = []
            row = []
            for a_name in top_ranges.keys():
                icon = get_service_icon(a_name)
                pct = get_service_percentage(a_name)
                button_label = f"{icon} {a_name} ({pct})"
                row.append(rbtn(button_label, style="primary", callback_data=f"sel_app_{a_name}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
            await query.edit_message_text("<b>Select Service:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
            return

        ranges = top_ranges.get(app_name, [])
        if not ranges:
            await query.answer("❌ No ranges available.", show_alert=True)
            return

        # দেশের তালিকা তৈরি করবে
        country_map_data = {}
        for rng in ranges:
            flag, cname = get_country_info(rng)
            c_key = f"{flag} {cname}"
            if c_key not in country_map_data:
                country_map_data[c_key] = []
            country_map_data[c_key].append(rng)

        if "country_ranges" not in context.user_data:
            context.user_data["country_ranges"] = {}

        buttons = []
        row = []
        for c_label, rng_list in country_map_data.items():
            c_idx = str(len(context.user_data["country_ranges"]) + 1)
            context.user_data["country_ranges"][c_idx] = {
                "app": app_name,
                "label": c_label,
                "ranges": rng_list
            }
            row.append(rbtn(c_label, style="primary", callback_data=f"sel_cty_{c_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)

        buttons.append([rbtn("🔙 Back to Services", style="danger", callback_data="back_to_services")])
        await query.edit_message_text(
            f"🌍 <b>Change Country for {app_name}:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # ৫. নম্বর চেঞ্জ করা (Same Range)
    if data == "same_range":
        r_text = last_range.get(uid)
        if r_text:
            app_name = context.user_data.get("current_app", "Facebook")
            await query.edit_message_text("🔄 Requesting new number...")
            await request_queue.put({
                'uid': uid,
                'chat_id': query.message.chat_id,
                'context': context,
                'range_text': r_text,
                'app_name': app_name,
                'delete_msg_id': query.message.message_id,
                'delete_chat_id': query.message.chat_id
            })
        else:
            await query.answer("No previous range found!", show_alert=True)
        return

    # ৬. উইথড্র মেথড সিলেক্ট
    if data == "set_method":
        kb = InlineKeyboardMarkup([
            [rbtn("Bkash", style="primary", callback_data="m_Bkash"), rbtn("Nagad", style="primary", callback_data="m_Nagad")],
            [rbtn("Rocket", style="primary", callback_data="m_Rocket"), rbtn("Binance", style="primary", callback_data="m_Binance")]
        ])
        await query.edit_message_text("💳 <b>Select Withdrawal Method:</b>", parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("m_"):
        method_name = data.replace("m_", "")
        users = load_json(USER_DATA_FILE, {})
        if str(uid) in users:
            users[str(uid)]["withdrawal_method"] = method_name
            save_json(USER_DATA_FILE, users)
            await query.edit_message_text(f"✅ Withdrawal Method set to <b>{method_name}</b>!", parse_mode="HTML")
        return

    if data == "init_withdraw":
        u_info = get_user(uid)
        m_method = u_info.get("withdrawal_method")
        if not m_method:
            await query.answer("❌ Set withdrawal method first!", show_alert=True)
            return
            
        settings = load_settings()
        if u_info["balance"] < settings["min_withdraw"]:
            await query.answer(f"❌ Minimum withdrawal is {settings['min_withdraw']}$", show_alert=True)
            return
            
        context.user_data["withdraw_method"] = m_method
        context.user_data["withdraw_mode"] = "amount"
        await query.message.reply_text(f"💵 <b>Enter Amount to Withdraw (Min: {settings['min_withdraw']}$):</b>", parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    # ৭. অ্যাডমিন উইথড্র অ্যাকশন
    if data.startswith("adm_app_"):
        pid = data.replace("adm_app_", "")
        w_reqs = load_json(WITHDRAW_DATA_FILE, {})
        if pid in w_reqs and w_reqs[pid]["status"] == "pending":
            w_reqs[pid]["status"] = "approved"
            save_json(WITHDRAW_DATA_FILE, w_reqs)
            
            u_id = w_reqs[pid]["user_id"]
            amt = w_reqs[pid]["amount"]
            try:
                await context.bot.send_message(u_id, f"✅ <b>WITHDRAWAL APPROVED!</b>\nAmount: {amt}$\nPID: <code>{pid}</code>", parse_mode="HTML")
            except: pass
            
            await query.edit_message_text(f"✅ Approved Request {pid}")
        return

    if data.startswith("adm_rej_"):
        pid = data.replace("adm_rej_", "")
        w_reqs = load_json(WITHDRAW_DATA_FILE, {})
        if pid in w_reqs and w_reqs[pid]["status"] == "pending":
            w_reqs[pid]["status"] = "rejected"
            save_json(WITHDRAW_DATA_FILE, w_reqs)
            
            u_id = w_reqs[pid]["user_id"]
            amt = w_reqs[pid]["amount"]
            
            # রিফান্ড ব্যালেন্স
            await update_db_balance(u_id, amt)
            
            try:
                await context.bot.send_message(u_id, f"❌ <b>WITHDRAWAL REJECTED & REFUNDED!</b>\nAmount: {amt}$\nPID: <code>{pid}</code>", parse_mode="HTML")
            except: pass
            
            await query.edit_message_text(f"❌ Rejected Request {pid}")
        return

# ==================== MAIN APPLICATION START ====================

async def post_init(application):
    asyncio.create_task(worker())
    asyncio.create_task(monitor_loop(application))

def main():
    request_config = HTTPXRequest(connect_timeout=15.0, read_timeout=15.0)
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request_config)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 BOT RUNNING WITH FULL FEATURES...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
