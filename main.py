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
import hmac
import base64
import hashlib
import struct
import unicodedata
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# ==================== CONFIGURATION SECTION ====================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(os.getenv("ADMIN_ID"))]

# à¦¡à¦¾à¦Ÿà¦¾ à¦«à¦¾à¦‡à¦² à¦¨à¦¿à¦°à§à¦¦à§‡à¦¶à¦¿à¦•à¦¾
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
        return f"{num_str[:4]}âœ¦âœ¦âœ¦{num_str[-4:]}"
    return num_str

def format_balance(balance):
    return f"{balance:.4f}"

def generate_payment_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))

def extract_otp(text):
    if not text or text == "No Content": return "N/A"
    text_clean = str(text).strip()

    # 1. âœ… "DIGITS is your verification/code" â€” TikTok, FB style
    digits_before = re.search(r'\b(\d{4,8})\s+is\s+your', text_clean, re.IGNORECASE)
    if digits_before: return digits_before.group(1).strip()

    # 2. âœ… "code is DIGITS" or "code: DIGITS"
    code_then_digits = re.search(
        r'(?:code|otp|pin|passcode|verification|verify|token)[:\s]+(\d{4,8})\b',
        text_clean, re.IGNORECASE
    )
    if code_then_digits: return code_then_digits.group(1).strip()

    # 3. âœ… "#DIGITS" â€” hash prefix style
    hash_code = re.search(r'#(\d{4,8})\b', text_clean)
    if hash_code: return hash_code.group(1).strip()

    # 4. âœ… Spaced OTP "123 456" or "123-456"
    spaced_otp = re.search(r'\b(\d{3}[\s-]\d{3})\b', text_clean)
    if spaced_otp: return spaced_otp.group(1)

    # 5. âœ… Exactly 6-digit code (most common OTP)
    six_digit = re.search(r'\b(\d{6})\b', text_clean)
    if six_digit: return six_digit.group(1)

    # 6. âœ… 4-8 digit fallback
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
    return "ðŸŒ", "Global"

# ==================== ALLOWED SERVICES ====================
# âœ… FIX: Telegram à¦¯à§‹à¦— à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡ à¦à¦¬à¦‚ à¦¸à¦¬ à¦¸à¦¾à¦°à§à¦­à¦¿à¦¸ à¦¨à¦¿à¦¶à§à¦šà¦¿à¦¤ à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡
ALLOWED_SERVICES = {
    "facebook",
    "whatsapp",
    "instagram",
    "discord",
    "imo",
    "tiktok",
    "telegram",
    "tg"  # âœ… "tg" shortname à¦“ support à¦•à¦°à¦¬à§‡
}

def is_allowed_service(service_name: str) -> bool:
    """service name ALLOWED_SERVICES à¦ à¦†à¦›à§‡ à¦•à¦¿à¦¨à¦¾ check à¦•à¦°à§‡ (case-insensitive)"""
    if not service_name: return False
    name = service_name.lower().strip()
    return any(allowed in name for allowed in ALLOWED_SERVICES)

def detect_service(full_sms):
    if not full_sms: return "SMS SERVICE"
    sms_lower = full_sms.lower()
    if "facebook" in sms_lower or "fb" in sms_lower: return "FACEBOOK"
    if "instagram" in sms_lower or "insta" in sms_lower: return "INSTAGRAM"
    if "whatsapp" in sms_lower: return "WHATSAPP"
    if "telegram" in sms_lower or "telgram" in sms_lower: return "TELEGRAM"  # âœ… typo handle
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
    if "whatsapp" in name: return "ðŸŸ¢"
    if "facebook" in name or "fb" in name: return "ðŸ“˜"
    if "telegram" in name or name == "tg": return "âœˆï¸"  # âœ… "tg" handle
    if "instagram" in name or "insta" in name: return "ðŸ“¸"
    if "tiktok" in name: return "ðŸŽµ"
    if "twitter" in name or name == "x": return "ðŸ¦"
    if "snapchat" in name: return "ðŸ‘»"
    if "viber" in name: return "ðŸ’œ"
    if "imo" in name: return "ðŸ“±"
    if "discord" in name: return "ðŸŽ®"
    if "line" in name: return "ðŸ’š"
    if "wechat" in name: return "ðŸ’¬"
    if "kakaotalk" in name or "kakao" in name: return "ðŸŸ¡"
    if "vkontakte" in name or "vk" in name: return "ðŸ”µ"
    if "signal" in name: return "ðŸ”’"
    if "linkedin" in name: return "ðŸ’¼"
    if "threads" in name: return "ðŸ§µ"
    if "tinder" in name: return "ðŸ”¥"
    if "bumble" in name: return "ðŸ"
    if "badoo" in name: return "ðŸ’œ"
    if "okcupid" in name: return "ðŸ’˜"
    if "bigo" in name: return "ðŸŽ¥"
    if "twitch" in name: return "ðŸ‘¾"
    if "google" in name or "gmail" in name or "youtube" in name: return "ðŸ”´"
    if "microsoft" in name or "outlook" in name or "hotmail" in name: return "ðŸªŸ"
    if "apple" in name or "icloud" in name: return "ðŸŽ"
    if "openai" in name or "chatgpt" in name or "gpt" in name: return "ðŸ¤–"
    if "claude" in name: return "ðŸ§ "
    if "yahoo" in name: return "ðŸŸ£"
    if "naver" in name: return "ðŸŸ¢"
    if "binance" in name: return "ðŸª™"
    if "paypal" in name: return "ðŸ’³"
    if "coinbase" in name: return "ðŸ¦"
    if "crypto" in name: return "ðŸ’Ž"
    if "wise" in name or "revolut" in name: return "ðŸ’¸"
    if "uber" in name: return "ðŸš—"
    if "grab" in name: return "ðŸš˜"
    if "gojek" in name: return "ðŸ›µ"
    if "foodpanda" in name or "deliveroo" in name: return "ðŸ”"
    if "indrive" in name or "indriver" in name: return "ðŸš•"
    if "amazon" in name: return "ðŸ“¦"
    if "shopee" in name: return "ðŸ›ï¸"
    if "lazada" in name: return "ðŸ›’"
    if "ebay" in name: return "ðŸ·ï¸"
    if "daraz" in name: return "ðŸ¬"
    if "ali" in name or "aliexpress" in name: return "ðŸ›’"
    if "netflix" in name: return "ðŸ¿"
    if "spotify" in name: return "ðŸŽ§"
    if "steam" in name: return "ðŸ•¹ï¸"
    if "pubg" in name: return "ðŸ”«"
    if "roblox" in name: return "ðŸ§±"
    return "ðŸ“±"

def get_service_percentage(app_name):
    name = str(app_name).lower().strip()
    if "whatsapp" in name: return "95%"
    if "facebook" in name or "fb" in name: return "90%"
    if "telegram" in name or name == "tg": return "88%"
    if "instagram" in name or "insta" in name: return "90%"
    if "imo" in name: return "92%"
    if "discord" in name: return "85%"
    if "tiktok" in name: return "90%"
    return "90%"

# ==================== 2FA TOTP ENGINE ====================

def generate_totp(secret: str) -> tuple[str, int]:
    """
    Standard TOTP (RFC 6238) generate à¦•à¦°à§‡à¥¤
    Returns: (6-digit code, seconds remaining)
    """
    try:
        # Secret clean à¦•à¦°à¦¾ â€” uppercase + padding
        secret_clean = secret.upper().strip().replace(" ", "")
        # Base32 padding à¦ à¦¿à¦• à¦•à¦°à¦¾
        padding = (8 - len(secret_clean) % 8) % 8
        secret_padded = secret_clean + "=" * padding

        # Key decode
        key = base64.b32decode(secret_padded)

        # Time step (30 seconds)
        now = int(time.time())
        time_step = now // 30
        remaining = 30 - (now % 30)

        # HMAC-SHA1
        msg = struct.pack(">Q", time_step)
        h = hmac.new(key, msg, hashlib.sha1).digest()

        # Dynamic truncation
        offset = h[-1] & 0x0F
        code_int = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
        code = str(code_int % 1_000_000).zfill(6)

        return code, remaining
    except Exception as e:
        return None, 0

def format_2fa_message(secret: str, code: str, remaining: int) -> str:
    """2FA result message format à¦•à¦°à§‡"""
    bar_filled = int(remaining / 30 * 10)
    progress = "ðŸŸ©" * bar_filled + "â¬œ" * (10 - bar_filled)
    return (
        f"ðŸ” <b>2FA CODE GENERATED</b>\n"
        f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        f"ðŸ”‘ <b>Secret:</b> <code>{secret.upper()}</code>\n\n"
        f"âœ… <b>Code:</b> <code>{code}</code>\n"
        f"â± <i>(This code is valid for {remaining} seconds)</i>\n\n"
        f"{progress} <code>{remaining}s</code>"
    )

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
        [rkbtn("ðŸ“² GET NUMBER", style="danger")],
    ]

    mid_row = []
    if traffic_on:
        mid_row.append(KeyboardButton("ðŸ“Š TRAFFIC"))
    if lb_on:
        mid_row.append(KeyboardButton("ðŸ† LEADERBOARD"))
    if mid_row:
        keyboard.append(mid_row)

    if live_on:
        keyboard.append([KeyboardButton("ðŸ“¡ LIVE OTP FEED")])

    keyboard.append([KeyboardButton("ðŸ” 2FA GENERATOR")])
    keyboard.append([rkbtn("ðŸ’° MY WALLET", style="success"), rkbtn("ðŸŽ REFER & EARN", style="success")])
    keyboard.append([KeyboardButton("ðŸ†˜ SUPPORT")])

    if is_admin(user_id):
        keyboard.append([KeyboardButton("âš™ï¸ ADMIN PANEL")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_main_keyboard():
    keyboard = [
        [KeyboardButton("âš™ï¸ SYSTEM CONFIG"), KeyboardButton("ðŸ’µ USER & BALANCE")],
        [KeyboardButton("ðŸ”’ SECURITY & JOIN"), KeyboardButton("ðŸ“¢ NOTICE & B-CAST")],
        [KeyboardButton("ðŸ”™ BACK TO MAIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_system_config_keyboard():
    settings = load_settings()
    live_on = settings.get("live_console_enabled", True)
    live_btn = "ðŸŸ¢ LIVE CONSOLE: ON" if live_on else "ðŸ”´ LIVE CONSOLE: OFF"

    traffic_on = settings.get("traffic_enabled", True)
    traffic_btn = "ðŸŸ¢ TRAFFIC: ON" if traffic_on else "ðŸ”´ TRAFFIC: OFF"

    lb_on = settings.get("leaderboard_enabled", True)
    lb_btn = "ðŸŸ¢ LEADERBOARD: ON" if lb_on else "ðŸ”´ LEADERBOARD: OFF"

    keyboard = [
        [KeyboardButton("ðŸ”‘ SET API KEY"), KeyboardButton("ðŸŒ SET API BASE URL")],
        [KeyboardButton("ðŸ“¢ SET OTP CHANNEL ID"), KeyboardButton("ðŸ’° SET WITHDRAW LIMITS")],
        [KeyboardButton("ðŸŽ SET REFER BONUS"), KeyboardButton("â± SET COOLDOWN")],
        [KeyboardButton(live_btn)],
        [KeyboardButton(traffic_btn), KeyboardButton(lb_btn)],
        [KeyboardButton("ðŸš« TOGGLE MAINTENANCE"), KeyboardButton("ðŸ”™ BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_user_balance_keyboard():
    keyboard = [
        [KeyboardButton("âž• ADD BALANCE"), KeyboardButton("âž– REMOVE BALANCE")],
        [KeyboardButton("ðŸ’¬ DIRECT MSG USER"), KeyboardButton("ðŸ” SEARCH BY USERNAME")],
        [KeyboardButton("ðŸ“œ ALL USER BALANCE"), KeyboardButton("ðŸ”™ BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_security_join_keyboard():
    keyboard = [
        [KeyboardButton("ðŸš« BAN USER"), KeyboardButton("âœ… UNBAN USER")],
        [KeyboardButton("ðŸ“¢ FORCE CHANNELS"), KeyboardButton("ðŸ“œ BAN USER LIST")],
        [KeyboardButton("ðŸ”™ BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_force_channel_keyboard():
    keyboard = [
        [KeyboardButton("âž• ADD CHANNEL"), KeyboardButton("âž– DELETE CHANNEL")],
        [KeyboardButton("ðŸ”™ BACK TO SECURITY")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_notice_bcast_keyboard():
    keyboard = [
        [KeyboardButton("ðŸ“¢ BROADCAST NOTICE"), KeyboardButton("ðŸ“ SET WELCOME MSG")],
        [KeyboardButton("ðŸ’¬ SET SUPPORT USERNAME"), KeyboardButton("ðŸ”— SET CHANNEL LINK")],
        [KeyboardButton("ðŸ”™ BACK TO ADMIN")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("âŒ CANCEL")]], resize_keyboard=True)

# ==================== ASYNC CLIENT & QUEUE ====================

client_async = httpx.AsyncClient(timeout=10.0, verify=False, headers={"User-Agent": "Mozilla/5.0"})
request_queue = asyncio.Queue()
active_numbers = load_json(ACTIVE_NUMBERS_FILE, {})
last_range = {}
last_request_time = {}
seen_skipped = set()
seen_group = set()

# ==================== API TYPE DETECTION ====================

def is_new_api(base_url: str) -> bool:
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
                text="â³ <b>SEARCHING NUMBER...</b>",
                parse_mode="HTML"
            )

            numbers = []

            seen_nums = set()
            for i in range(3):
                num = await fetch_number_async(range_text)
                if num and num not in seen_nums:
                    seen_nums.add(num)
                    numbers.append(num)

            if not numbers:
                await status_msg.edit_text(
                    "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                    "     âŒ <b>NO NUMBER FOUND</b>\n"
                    "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                    "ðŸ˜” No available numbers right now.\n\n"
                    "ðŸ’¡ <i>Please try again in a few seconds\nor select a different country.</i>",
                    parse_mode="HTML"
                )
                if del_msg_id:
                    try: await context.bot.delete_message(chat_id=del_chat_id, message_id=del_msg_id)
                    except: pass
                continue

            buttons = []

            first_num = normalize_number(numbers[0])
            flag, c_name = get_country_info(first_num)

            icon = get_service_icon(app_name)
            pct = get_service_percentage(app_name)
            now_str = datetime.now().strftime("%H:%M:%S")
            txt = (
                f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                f"   ðŸ“² <b>VIRTUAL NUMBER READY</b>\n"
                f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                f"ðŸ”¸ <b>Service :</b>  {icon} {app_name}\n"
                f"ðŸ”¸ <b>Country :</b>  {flag} {c_name}\n"
                f"ðŸ”¸ <b>Success :</b>  {pct}\n"
                f"ðŸ”¸ <b>Time    :</b>  <code>{now_str}</code>\n\n"
                f"ðŸ“‹ <b>Tap a number below to copy:</b>"
            )

            for num in numbers:
                clean_num = normalize_number(num)

                active_numbers[clean_num] = {
                    "uid": uid,
                    "range": range_text,
                    "timestamp": datetime.now().isoformat()
                }

                buttons.append([
                    InlineKeyboardButton(
                        text=f"ðŸ“± {flag}  +{clean_num}  Â·  TAP TO COPY",
                        copy_text=CopyTextButton(text=f"+{clean_num}")
                    )
                ])

            save_json(ACTIVE_NUMBERS_FILE, active_numbers)
            add_number_taken(uid, len(numbers))

            settings = load_settings()

            buttons.append([
                rbtn("ðŸŒ Change Country", style="primary", callback_data="change_country"),
                rbtn("ðŸ”„ New Number", style="primary", callback_data="same_range")
            ])

            buttons.append([
                rbtn("ðŸ“¢ Join OTP Channel", style="success", url=settings.get("channel_url"))
            ])

            kb = InlineKeyboardMarkup(buttons)

            await status_msg.edit_text(
                txt,
                parse_mode="HTML",
                reply_markup=kb
            )

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

            try:
                otp_target = int(str(otp_target_raw).strip())
            except:
                otp_target = str(otp_target_raw).strip()


            if api_key:
                if is_new_api(base_url):
                    api_headers = {
                        "mauthapi": api_key,
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    }

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
                    legacy_headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json"
                    }

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

                    otps = console_otps

                live_console_enabled = settings.get("live_console_enabled", True)
                if otp_target and console_otps and live_console_enabled:
                    channel_url = settings.get("channel_url", "")
                    for hit in console_otps:
                        if not isinstance(hit, dict): continue
                        full_sms  = (hit.get("message") or "").strip()
                        service   = (hit.get("sid") or hit.get("service") or "").strip()
                        range_id  = (hit.get("range") or hit.get("number") or "").strip()
                        hit_time  = str(hit.get("time", ""))
                        if not full_sms or not service: continue

                        if not is_allowed_service(service):
                            continue

                        otp_code = extract_otp(full_sms)
                        if not otp_code or otp_code == "N/A": continue

                        c_otp_id = f"console_{range_id}_{otp_code}_{hit_time}"
                        if c_otp_id in seen_group: continue
                        seen_group.add(c_otp_id)

                        svc_icon      = get_service_icon(service)
                        service_title = service.title()
                        lookup_num    = range_id.replace("X", "").replace("x", "")
                        flag, c_name  = get_country_info(lookup_num)

                        display_id = range_id if "X" in range_id.upper() else mask_number(range_id)

                        group_msg = (
                            f"{svc_icon} <b>{service_title}</b> â€¢ {flag} {c_name}\n"
                            f"ðŸ“ž <code>{display_id}</code>\n\n"
                            f"ðŸ”” {html.escape(full_sms)}"
                        )
                        group_kb_buttons = [
                            InlineKeyboardButton(
                                text=f"ðŸ“‹ {otp_code}",
                                copy_text=CopyTextButton(text=otp_code)
                            )
                        ]
                        if channel_url:
                            group_kb_buttons.append(
                                InlineKeyboardButton("ðŸ¤– OTP Group", url=channel_url)
                            )
                        kb = InlineKeyboardMarkup([group_kb_buttons])
                        try:
                            await app.bot.send_message(
                                otp_target, group_msg,
                                parse_mode="HTML", reply_markup=kb
                            )
                        except Exception as e:
                            print(f"[ERROR] Consoleâ†’Group: {e}")

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

                        otp_time = str(otp.get("time", ""))
                        otp_id = str(otp.get("otp_id", f"{num}_{otp_code}_{otp_time}"))

                        if not full_sms or not otp_code or otp_code == "N/A":
                            if otp_id not in seen_skipped:
                                seen_skipped.add(otp_id)
                                print(f"[SKIP] num={num} | no real OTP content.")
                            continue

                        flag, c_name = get_country_info(num)
                        service = detect_service(full_sms)

                        if not is_allowed_service(service):
                            if otp_id not in seen_skipped:
                                seen_skipped.add(otp_id)
                            continue

                        svc_icon = get_service_icon(service)
                        service_title = service.title()
                        masked_num = mask_number(num)
                        channel_url = settings.get("channel_url", "")

                        if otp_target and otp_id not in seen_group:
                            seen_group.add(otp_id)
                            group_msg = (
                                f"{svc_icon} <b>{service_title}</b>  â€¢  {flag} {c_name}\n"
                                f"ðŸ“± <code>{masked_num}</code>\n"
                                f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                                f"ðŸ“© {html.escape(full_sms)}"
                            )
                            group_kb_buttons = [
                                InlineKeyboardButton(
                                    text=f"ðŸ“‹ {otp_code}",
                                    copy_text=CopyTextButton(text=otp_code)
                                )
                            ]
                            if channel_url:
                                group_kb_buttons.append(
                                    InlineKeyboardButton("ðŸ¤– OTP Group", url=channel_url)
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
                                f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                                f"   {svc_icon} <b>OTP RECEIVED!</b>\n"
                                f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                                f"ðŸ“± <b>Number:</b>  <code>+{num}</code>\n"
                                f"ðŸŒ <b>Service:</b>  {service_title}\n"
                                f"{flag} <b>Country:</b>  {c_name}\n\n"
                                f"ðŸ’¬ <b>Message:</b>\n"
                                f"<blockquote>{html.escape(full_sms)}</blockquote>\n"
                                f"ðŸ’° <b>Reward:</b> <code>+${otp_reward:.4f} Credited!</code> ðŸŽ‰"
                            )
                            user_kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    text=f"ðŸ“‹ {otp_code}",
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

        # âœ… FIX: Memory leak à¦°à§‹à¦§ â€” set à¦¬à¦¡à¦¼ à¦¹à¦²à§‡ à¦ªà§à¦°à¦¨à§‹ entries à¦¸à¦°à¦¾à¦“
        if len(seen_group) > 5000:
            seen_group.clear()
        if len(seen_skipped) > 5000:
            seen_skipped.clear()

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
        return True

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
            buttons.append([rbtn(f"ðŸ“¢ Join {ch}", style="primary", url=f"https://t.me/{clean_ch}")])
        buttons.append([rbtn("ðŸ”„ Verify / Check", style="success", callback_data="check_join")])

        msg = (
            "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            "      ðŸ”’ <b>JOIN REQUIRED</b>\n"
            "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            "To use this bot, please join\nour required channel(s) below:\n\n"
            "ðŸ‘‡ <b>Click to join, then verify:</b>"
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return False

    return True

# ==================== âœ… FIX: START FUNCTION (REFER COUNT BUG FIXED) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    uid = update.effective_user.id
    username = update.effective_user.username
    full_name = update.effective_user.full_name

    # âœ… FIX: à¦ªà§à¦°à¦¥à¦®à§‡à¦‡ users_db à¦²à§‹à¦¡ à¦•à¦°à¦¾ à¦¹à¦šà§à¦›à§‡
    users_db = load_json(USER_DATA_FILE, {})
    is_new = str(uid) not in users_db

    # âœ… FIX: get_user() à¦•à¦² à¦•à¦°à¦¾à¦° à¦ªà¦° à¦†à¦¬à¦¾à¦° fresh users_db à¦²à§‹à¦¡ à¦•à¦°à¦¤à§‡ à¦¹à¦¬à§‡
    get_user(uid, username, full_name)
    users_db = load_json(USER_DATA_FILE, {})  # âœ… re-load after get_user creates the entry

    # âœ… FIX: Referral Tracking à¦¸à¦®à§à¦ªà§‚à¦°à§à¦£ à¦¨à¦¤à§à¦¨à¦­à¦¾à¦¬à§‡ à¦²à§‡à¦–à¦¾
    if context.args and is_new:
        referrer_id = str(context.args[0])
        referrer_id = referrer_id.strip()

        if referrer_id != str(uid) and referrer_id in users_db:
            settings = load_settings()
            bonus = settings.get("refer_bonus", 0.05)

            # âœ… FIX: referred_by à¦¸à§‡à¦Ÿ à¦•à¦°à¦¾
            users_db[str(uid)]["referred_by"] = referrer_id
            save_json(USER_DATA_FILE, users_db)

            # âœ… FIX: Referrer-à¦à¦° balance, referrals, referral_earnings à¦†à¦ªà¦¡à§‡à¦Ÿ
            # à¦†à¦—à§‡ balance à¦†à¦ªà¦¡à§‡à¦Ÿ à¦•à¦°à¦¿
            await update_db_balance(referrer_id, bonus)

            # âœ… FIX: à¦à¦–à¦¨ fresh à¦²à§‹à¦¡ à¦•à¦°à§‡ referrals count à¦¬à¦¾à¦¡à¦¼à¦¾à¦‡
            users_db = load_json(USER_DATA_FILE, {})
            if referrer_id in users_db:
                users_db[referrer_id]["referrals"] = users_db[referrer_id].get("referrals", 0) + 1
                users_db[referrer_id]["referral_earnings"] = round(
                    users_db[referrer_id].get("referral_earnings", 0.0) + bonus, 4
                )
                save_json(USER_DATA_FILE, users_db)

            # âœ… Referrer-à¦•à§‡ notification à¦ªà¦¾à¦ à¦¾à¦¨à§‹
            try:
                await context.bot.send_message(
                    int(referrer_id),
                    f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                    f"      ðŸŽ <b>REFERRAL BONUS!</b>\n"
                    f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                    f"ðŸ†• <b>New user joined via your link!</b>\n\n"
                    f"ðŸ‘¤ <b>User:</b> {html.escape(full_name or 'Anonymous')}\n"
                    f"ðŸ’° <b>Bonus:</b> <code>+${bonus:.4f} Credited!</code> ðŸŽ‰",
                    parse_mode="HTML"
                )
            except:
                pass

    settings = load_settings()
    text = settings.get("welcome_message") or "ðŸ‘‹ Welcome to AutoSyncX Bot!"

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
        await update.message.reply_text(
            "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            "        ðŸš« <b>BANNED</b>\n"
            "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            "You have been <b>banned</b> from using this bot.\n\n"
            "If you think this is a mistake,\nplease contact support.",
            parse_mode="HTML"
        )
        return

    # âœ… FIX: Maintenance mode check â€” admin à¦¬à¦¾à¦¦à§‡ à¦¸à¦¬à¦¾à¦° à¦œà¦¨à§à¦¯ block
    if not is_admin(uid):
        settings = load_settings()
        if settings.get("maintenance_mode", False):
            await update.message.reply_text(
                "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                "    ðŸ›  <b>UNDER MAINTENANCE</b>\n"
                "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                "We're currently upgrading the bot.\n\n"
                "â± <i>Please check back shortly!\nWe'll be back online soon.</i>",
                parse_mode="HTML"
            )
            return

    if not await check_force_sub(update, context):
        return

    if text == "âŒ CANCEL":
        context.user_data.clear()
        await update.message.reply_text(
            "â†©ï¸ <b>Action cancelled.</b>\n<i>Returned to main menu.</i>",
            parse_mode="HTML",
            reply_markup=main_keyboard(uid)
        )
        return

    # ==================== 2FA SECRET KEY CAPTURE ====================
    if context.user_data.get("2fa_mode"):
        context.user_data.pop("2fa_mode", None)
        secret_raw = raw_text.strip().replace(" ", "").upper()

        # Validate â€” base32 characters only
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
        if not secret_raw or not all(c in valid_chars for c in secret_raw) or len(secret_raw) < 8:
            await update.message.reply_text(
                "âŒ <b>Invalid Secret Key!</b>\n\n"
                "Please send a valid Base32 secret key.\n"
                "<i>Example: JBSWY3DPEHPK3PXP</i>",
                parse_mode="HTML"
            )
            return

        code, remaining = generate_totp(secret_raw)
        if not code:
            await update.message.reply_text(
                "âŒ <b>Could not generate code!</b>\n\n"
                "Please check your secret key and try again.",
                parse_mode="HTML"
            )
            return

        # Store secret for refresh
        context.user_data["2fa_secret"] = secret_raw

        msg = format_2fa_message(secret_raw, code, remaining)
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ”„ Refresh Code", style="success", callback_data="2fa_refresh")],
            [rbtn("âŒ Close", style="danger", callback_data="2fa_close")]
        ])
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
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
                await update.message.reply_text(
                    f"âŒ <b>Invalid Amount!</b>\n\n"
                    f"ðŸ“Š Allowed range: <code>${min_w}</code> â€” <code>${max_w}</code>\n"
                    f"ðŸ’° Your balance: <code>${u_bal:.4f}</code>",
                    parse_mode="HTML",
                    reply_markup=cancel_keyboard()
                )
                return
            if amount > u_bal:
                await update.message.reply_text(
                    f"âŒ <b>Insufficient Balance!</b>\n\n"
                    f"ðŸ’° Your balance: <code>${u_bal:.4f}</code>\n"
                    f"ðŸ“¤ Requested: <code>${amount:.4f}</code>",
                    parse_mode="HTML",
                    reply_markup=cancel_keyboard()
                )
                return

            context.user_data["withdraw_amount"] = amount
            context.user_data["withdraw_mode"] = "number"
            await update.message.reply_text(
                f"ðŸ“± <b>Enter Account Number</b>\n\n"
                f"ðŸ’³ Method: <b>{context.user_data.get('withdraw_method', 'N/A')}</b>\n"
                f"ðŸ’µ Amount: <code>${amount:.4f}</code>\n\n"
                f"<i>Example: 017XXXXXXXX</i>",
                parse_mode="HTML",
                reply_markup=cancel_keyboard()
            )
            return
        except:
            await update.message.reply_text(
                "âŒ <b>Invalid input!</b>\n<i>Please send a valid number.</i>",
                parse_mode="HTML",
                reply_markup=cancel_keyboard()
            )
            return

    if w_mode == "number":
        method = context.user_data.get("withdraw_method")
        amount = context.user_data.get("withdraw_amount")
        payment_num = text
        pid = generate_payment_id()

        await update_db_balance(uid, -amount)

        w_requests = load_json(WITHDRAW_DATA_FILE, {})
        w_requests[pid] = {
            "user_id": uid, "method": method, "amount": amount,
            "number": payment_num, "payment_id": pid, "status": "pending",
            "timestamp": datetime.now().isoformat()
        }
        save_json(WITHDRAW_DATA_FILE, w_requests)

        context.user_data.clear()
        await update.message.reply_text(
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"   ðŸ“¤ <b>WITHDRAWAL SUBMITTED</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"âœ… Your request has been sent to admin!\n\n"
            f"ðŸ¦ <b>Method:</b> {method}\n"
            f"ðŸ“± <b>Account:</b> <code>{payment_num}</code>\n"
            f"ðŸ’µ <b>Amount:</b> <code>${amount:.4f}</code>\n"
            f"ðŸ†” <b>PID:</b> <code>{pid}</code>\n\n"
            f"â± <i>Please allow up to 24 hours for processing.</i>",
            parse_mode="HTML",
            reply_markup=main_keyboard(uid)
        )

        admin_msg = (
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"  ðŸ’° <b>WITHDRAWAL REQUEST</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"ðŸ†” <b>User ID:</b> <code>{uid}</code>\n"
            f"âš™ï¸ <b>Method:</b> {method}\n"
            f"ðŸ“ž <b>Account:</b> <code>{payment_num}</code>\n"
            f"ðŸ’µ <b>Amount:</b> <code>${amount:.4f}</code>\n"
            f"ðŸ”– <b>PID:</b> <code>{pid}</code>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("âœ… Approve", callback_data=f"adm_app_{pid}"),
             InlineKeyboardButton("âŒ Reject", callback_data=f"adm_rej_{pid}")]
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
            await update.message.reply_text("âœ… API Key updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "base_url":
            settings["base_url"] = raw_text
            save_settings(settings)
            await update.message.reply_text("âœ… API Base URL updated!", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "otp_channel":
            settings["otp_group_id"] = raw_text
            save_settings(settings)
            await update.message.reply_text(f"âœ… OTP Channel ID set to: <code>{raw_text}</code>", parse_mode="HTML", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "withdraw_limits":
            parts = raw_text.split()
            if len(parts) == 2:
                try:
                    settings["min_withdraw"] = float(parts[0])
                    settings["max_withdraw"] = float(parts[1])
                    save_settings(settings)
                    await update.message.reply_text(f"âœ… Limits set: Min {parts[0]}$ | Max {parts[1]}$", reply_markup=admin_system_config_keyboard())
                except ValueError:
                    await update.message.reply_text("âŒ Invalid numbers! Example: 0.5 100", reply_markup=admin_system_config_keyboard())
            else:
                await update.message.reply_text("âŒ Invalid format! Example: 0.5 100", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "refer_bonus":
            try:
                settings["refer_bonus"] = float(raw_text)
                save_settings(settings)
                await update.message.reply_text("âœ… Referral bonus updated!", reply_markup=admin_system_config_keyboard())
            except ValueError:
                await update.message.reply_text("âŒ Invalid number! Example: 0.05", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "cooldown":
            try:
                settings["cooldown_time"] = float(raw_text)
                save_settings(settings)
                await update.message.reply_text("âœ… Cooldown updated!", reply_markup=admin_system_config_keyboard())
            except ValueError:
                await update.message.reply_text("âŒ Invalid number! Example: 1.5", reply_markup=admin_system_config_keyboard())
        elif edit_mode == "welcome":
            settings["welcome_message"] = raw_text
            save_settings(settings)
            await update.message.reply_text("âœ… Welcome Message updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "support":
            settings["support_username"] = raw_text.replace("@", "")
            save_settings(settings)
            await update.message.reply_text("âœ… Support username updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "channel_link":
            settings["channel_url"] = raw_text
            save_settings(settings)
            await update.message.reply_text("âœ… Channel link updated!", reply_markup=admin_notice_bcast_keyboard())
        elif edit_mode == "add_balance":
            parts = raw_text.split()
            if len(parts) == 2 and parts[0].isdigit():
                t_uid, amt = parts[0], float(parts[1])
                new_b = await update_db_balance(t_uid, amt)
                await update.message.reply_text(f"âœ… Added {amt}$ to User {t_uid}. New Balance: {new_b}$", reply_markup=admin_user_balance_keyboard())
            else:
                await update.message.reply_text("âŒ Format: USER_ID AMOUNT", reply_markup=admin_user_balance_keyboard())
        elif edit_mode == "remove_balance":
            parts = raw_text.split()
            if len(parts) == 2 and parts[0].isdigit():
                t_uid, amt = parts[0], float(parts[1])
                new_b = await update_db_balance(t_uid, -amt)
                await update.message.reply_text(f"âœ… Removed {amt}$ from User {t_uid}. New Balance: {new_b}$", reply_markup=admin_user_balance_keyboard())
            else:
                await update.message.reply_text("âŒ Format: USER_ID AMOUNT", reply_markup=admin_user_balance_keyboard())
        elif edit_mode == "ban_user":
            if ban_user(raw_text):
                await update.message.reply_text(f"âœ… User {raw_text} banned!", reply_markup=admin_security_join_keyboard())
            else:
                await update.message.reply_text("âŒ User already banned!", reply_markup=admin_security_join_keyboard())

        # âœ… FIX: unban_user handler à¦¯à§‹à¦— à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡ (à¦†à¦—à§‡ à¦›à¦¿à¦² à¦¨à¦¾!)
        elif edit_mode == "unban_user":
            if unban_user(raw_text):
                await update.message.reply_text(f"âœ… User {raw_text} unbanned!", reply_markup=admin_security_join_keyboard())
            else:
                await update.message.reply_text("âŒ User not found in ban list!", reply_markup=admin_security_join_keyboard())

        elif edit_mode == "search_username":
            # âœ… FIX: search_username handler à¦¯à§‹à¦— à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡ (à¦†à¦—à§‡ à¦›à¦¿à¦² à¦¨à¦¾!)
            search_name = raw_text.replace("@", "").lower().strip()
            users = load_json(USER_DATA_FILE, {})
            found = []
            for u_id, u_data in users.items():
                uname = (u_data.get("username") or "").lower()
                fname = (u_data.get("full_name") or "").lower()
                if search_name in uname or search_name in fname:
                    found.append(
                        f"ðŸ†” <code>{u_id}</code> | @{u_data.get('username','N/A')} | "
                        f"{u_data.get('full_name','N/A')} | ðŸ’°{u_data.get('balance',0):.4f}$"
                    )
            if found:
                result_text = "\n".join(found[:10])
                await update.message.reply_text(
                    f"ðŸ” <b>Search Results:</b>\n\n{result_text}",
                    parse_mode="HTML",
                    reply_markup=admin_user_balance_keyboard()
                )
            else:
                await update.message.reply_text("âŒ No user found!", reply_markup=admin_user_balance_keyboard())

        elif edit_mode == "add_force_channel":
            ch = raw_text.strip()
            channels = settings.get("force_join_channels", [])
            if ch not in channels:
                channels.append(ch)
                settings["force_join_channels"] = channels
                settings["force_join_enabled"] = True
                save_settings(settings)
                await update.message.reply_text(f"âœ… Channel <code>{ch}</code> à¦¯à§‹à¦— à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡!", parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
            else:
                await update.message.reply_text("âŒ à¦à¦‡ à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à¦Ÿà¦¿ à¦†à¦—à§‡à¦‡ à¦¤à¦¾à¦²à¦¿à¦•à¦¾à¦¯à¦¼ à¦°à¦¯à¦¼à§‡à¦›à§‡!", reply_markup=admin_force_channel_keyboard())
        elif edit_mode == "del_force_channel":
            ch = raw_text.strip()
            channels = settings.get("force_join_channels", [])
            if ch in channels:
                channels.remove(ch)
                settings["force_join_channels"] = channels
                save_settings(settings)
                await update.message.reply_text(f"âœ… Channel <code>{ch}</code> à¦¤à¦¾à¦²à¦¿à¦•à¦¾ à¦¥à§‡à¦•à§‡ à¦®à§à¦›à§‡ à¦«à§‡à¦²à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡!", parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
            else:
                await update.message.reply_text("âŒ à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à¦Ÿà¦¿ à¦¤à¦¾à¦²à¦¿à¦•à¦¾à¦¯à¦¼ à¦ªà¦¾à¦“à¦¯à¦¼à¦¾ à¦¯à¦¾à¦¯à¦¼à¦¨à¦¿!", reply_markup=admin_force_channel_keyboard())
                
        elif edit_mode == "direct_msg":
            parts = raw_text.split(maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit():
                try:
                    await context.bot.send_message(int(parts[0]), f"ðŸ’¬ <b>MESSAGE FROM ADMIN:</b>\n\n{parts[1]}", parse_mode="HTML")
                    await update.message.reply_text("âœ… Message sent!", reply_markup=admin_user_balance_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"âŒ Failed: {e}", reply_markup=admin_user_balance_keyboard())
            else:
                await update.message.reply_text("âŒ Format: USER_ID MESSAGE", reply_markup=admin_user_balance_keyboard())
        elif edit_mode == "broadcast":
            users = load_json(USER_DATA_FILE, {})
            succ, fail = 0, 0
            msg = await update.message.reply_text("ðŸ“¢ Broadcasting started...")
            for u_id in users.keys():
                try:
                    await context.bot.send_message(int(u_id), f"ðŸ“¢ <b>ANNOUNCEMENT:</b>\n\n{raw_text}", parse_mode="HTML")
                    succ += 1
                except: fail += 1
                await asyncio.sleep(0.04)
            await msg.edit_text(f"âœ… Broadcast complete!\nSuccess: {succ} | Failed: {fail}")
        return

    # --- USER BUTTON COMMANDS ---
    if "GET NUMBER" in raw_text.upper():
        status = await update.message.reply_text("â³ Loading Services...")
        top_ranges, err = await fetch_top_ranges()
        if err or not top_ranges:
            err_msg = err if err else "No active services returned from API"
            await status.edit_text(f"âŒ Could not fetch ranges from server.\n\nðŸ” <b>Reason:</b> <code>{err_msg}</code>", parse_mode="HTML")
            return

        filtered_ranges = {
            app: ranges
            for app, ranges in top_ranges.items()
            if is_allowed_service(app)
        }

        if not filtered_ranges:
            await status.edit_text("âŒ <b>No active services available right now.</b>\n<i>Try again later.</i>", parse_mode="HTML")
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
        await status.edit_text(
            "ðŸ“² <b>SELECT SERVICE</b>\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            "<i>Choose a platform to get a virtual number:</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if text == "ðŸ’° MY WALLET" or text == "MY WALLET" or text == "ðŸ’µ BALANCE" or text == "BALANCE":
        u_info = get_user(uid)
        settings = load_settings()
        m_method = u_info.get("withdrawal_method") or "Not Set"
        bal = u_info['balance']
        min_w = settings['min_withdraw']
        can_withdraw = "âœ… Ready to withdraw" if bal >= min_w else f"âŒ Need ${min_w - bal:.4f} more"

        bal_text = (
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"      ðŸ’° <b>MY WALLET</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"ðŸ’µ <b>Balance</b>\n"
            f"  â”— <code>${bal:.4f}</code>\n\n"
            f"ðŸ¦ <b>Payment Method</b>\n"
            f"  â”— <code>{m_method}</code>\n\n"
            f"ðŸ“¤ <b>Withdraw Status</b>\n"
            f"  â”— {can_withdraw}\n\n"
            f"ðŸ“Š Limits: <code>${min_w}</code> â€” <code>${settings['max_withdraw']}</code>"
        )
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ¦ Set Payment Method", style="primary", callback_data="set_method")],
            [rbtn("ðŸ“¤ Withdraw Earnings", style="success", callback_data="init_withdraw")]
        ])
        await update.message.reply_text(bal_text, parse_mode="HTML", reply_markup=kb)
        return

    if text == "ðŸŽ REFER & EARN" or text == "REFER & EARN":
        settings = load_settings()
        b_info = await context.bot.get_me()
        ref_link = f"https://t.me/{b_info.username}?start={uid}"
        u_info = get_user(uid)
        total_refs = u_info.get('referrals', 0)
        ref_earn = u_info.get('referral_earnings', 0.0)
        bonus = settings['refer_bonus']

        ref_msg = (
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"      ðŸŽ <b>REFER & EARN</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"ðŸ”— <b>Your Referral Link:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n"
            f"â”‚ ðŸ‘¥  Referrals  â†’  <b>{total_refs} users</b>\n"
            f"â”‚ ðŸ’°  Earned     â†’  <b>${ref_earn:.4f}</b>\n"
            f"â”‚ ðŸŽ  Per Refer  â†’  <b>${bonus:.4f}</b>\n"
            f"â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n\n"
            f"ðŸ’¡ <i>Share your link and earn ${bonus:.4f}\nfor every new user who joins!</i>"
        )
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ“¤ Share My Referral Link", url=f"https://t.me/share/url?url={ref_link}")]
        ])
        await update.message.reply_text(ref_msg, parse_mode="HTML", reply_markup=kb)
        return

    if text == "ðŸ“¡ LIVE OTP FEED" or text == "LIVE OTP FEED" or text == "ðŸ“¡ LIVE CONSOLE" or text == "LIVE CONSOLE":
        settings = load_settings()
        if not settings.get("live_console_enabled", True):
            await update.message.reply_text(
                "ðŸ”´ <b>LIVE CONSOLE is currently disabled.</b>\n<i>Contact admin for more info.</i>",
                parse_mode="HTML"
            )
            return

        api_key = settings.get("api_key")
        base_url = settings.get("base_url", "").rstrip('/')

        if not api_key:
            await update.message.reply_text("âŒ <b>API key not configured.</b>", parse_mode="HTML")
            return

        wait_msg = await update.message.reply_text("ðŸ“¡ <b>Fetching Live Console...</b>", parse_mode="HTML")

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
                await wait_msg.edit_text("ðŸ“¡ <b>Live Console</b>\n\n<i>No recent hits in the last 15 minutes.</i>", parse_mode="HTML")
                return

            lines = [
                "ðŸ“¡ <b>LIVE OTP FEED</b> â€¢ Last 15 Min",
                "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            ]
            for hit in hits[:15]:
                if not isinstance(hit, dict): continue
                full_sms  = (hit.get("message") or "").strip()
                service   = (hit.get("sid") or hit.get("service") or "Unknown").strip()
                range_id  = (hit.get("range") or hit.get("number") or "").strip()

                if not full_sms: continue

                otp_code  = extract_otp(full_sms)
                svc_icon  = get_service_icon(service)
                flag, c_name = get_country_info(range_id.replace("X", ""))

                otp_part = f"\n  ðŸ”‘ <b>OTP:</b> <code>{otp_code}</code>" if otp_code and otp_code != "N/A" else ""
                lines.append(
                    f"{svc_icon} <b>{html.escape(service.title())}</b>  {flag} {c_name}\n"
                    f"  ðŸ“© <i>{html.escape(full_sms[:90])}{'â€¦' if len(full_sms) > 90 else ''}</i>"
                    f"{otp_part}"
                )
                lines.append("â”€  â”€  â”€  â”€  â”€  â”€  â”€  â”€")

            channel_url = settings.get("channel_url", "")
            kb = None
            if channel_url:
                kb = InlineKeyboardMarkup([[rbtn("ðŸ“¢ Join OTP Channel", style="primary", url=channel_url)]])

            await wait_msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)

        except Exception as e:
            await wait_msg.edit_text(f"âŒ <b>Error fetching console:</b> <code>{e}</code>", parse_mode="HTML")
        return


    if text == "ðŸ“Š TRAFFIC" or text == "TRAFFIC":
        settings = load_settings()
        if not settings.get("traffic_enabled", True):
            await update.message.reply_text(
                "ðŸ”´ <b>TRAFFIC feature is currently disabled.</b>\n<i>Contact admin for more info.</i>",
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
            await update.message.reply_text("ðŸ“Š <b>Live Traffic (Last 1 Hour)</b>\n\n<i>No OTP transactions in the last hour.</i>", parse_mode="HTML")
            return
            
        lines = [
            "ðŸ“Š <b>LIVE TRAFFIC</b> â€¢ Last 1 Hour",
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        ]
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        for i, ((srv, flag, cname), count) in enumerate(sorted_counts, 1):
            pct = (count / total) * 100
            bar_len = int(pct / 10)
            bar = "â–ˆ" * bar_len + "â–‘" * (10 - bar_len)
            svc_icon = get_service_icon(srv)
            lines.append(
                f"<b>{i}.</b> {svc_icon} <b>{srv}</b>  {flag} {cname}\n"
                f"   <code>[{bar}]</code> <code>{pct:.1f}%</code>  ({count} OTPs)\n"
            )
        lines.append("â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”")
        lines.append(f"ðŸ“ˆ <b>Total:</b> <code>{total}</code> OTPs received in last hour")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if text == "ðŸ† LEADERBOARD" or text == "LEADERBOARD":
        settings = load_settings()
        if not settings.get("leaderboard_enabled", True):
            await update.message.reply_text(
                "ðŸ”´ <b>LEADERBOARD feature is currently disabled.</b>\n<i>Contact admin for more info.</i>",
                parse_mode="HTML"
            )
            return

        stats = load_json(STATS_FILE, {})
        users = load_json(USER_DATA_FILE, {})

        ranked = []
        for u_id, s_data in stats.items():
            cnt = len(s_data.get("otps_received", []))
            if cnt > 0:
                ranked.append((u_id, cnt))

        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)[:10]

        # Top 3 à¦à¦° à¦œà¦¨à§à¦¯ à¦®à§‡à¦¡à§‡à¦²
        medals = {1: "ðŸ¥‡", 2: "ðŸ¥ˆ", 3: "ðŸ¥‰"}

        lines = [
            "ðŸ† <b>OTP LEADERBOARD</b> â€¢ Top 10",
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
        ]

        if ranked:
            for idx, (r_uid, count) in enumerate(ranked, 1):
                u_data = users.get(str(r_uid), {})

                # âœ… full_name à¦¸à¦¬à¦¾à¦° à¦†à¦—à§‡ à¦¦à§‡à¦–à¦¾à¦¬à§‡, à¦¨à¦¾ à¦¥à¦¾à¦•à¦²à§‡ username, à¦¨à¦¾ à¦¥à¦¾à¦•à¦²à§‡ ID
                full_name = (u_data.get("full_name") or "").strip()
                username  = (u_data.get("username") or "").strip()

                if full_name:
                    display_name = html.escape(full_name)
                    if username:
                        display_name += f" <i>(@{html.escape(username)})</i>"
                elif username:
                    display_name = f"@{html.escape(username)}"
                else:
                    display_name = f"User#{r_uid[-4:]}"

                medal = medals.get(idx, f"<b>#{idx}</b>")
                lines.append(
                    f"{medal} {display_name}\n"
                    f"     ðŸ“© <code>{count}</code> OTPs received\n"
                )
        else:
            lines.append("<i>No OTP record available yet.</i>")

        lines.append("â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if text == "ðŸ†˜ SUPPORT" or text == "SUPPORT" or text == "ðŸ’¬ SUPPORT":
        settings = load_settings()
        sup = settings.get("support_username", "support")
        msg = (
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"      ðŸ†˜ <b>SUPPORT CENTER</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"Having trouble? Our team is\nhere to help you anytime!\n\n"
            f"ðŸ‘¤ <b>Support:</b> @{sup}\n"
            f"â± <b>Response:</b> Within 24 hours"
        )
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ’¬ Chat with Support", style="primary", url=f"https://t.me/{sup}")]
        ])
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    # ==================== 2FA GENERATOR HANDLER ====================
    if text == "ðŸ” 2FA GENERATOR" or text == "2FA GENERATOR" or text == "ðŸ” 2FA SETUP" or text == "2FA SETUP":
        context.user_data["2fa_mode"] = True
        msg = (
            f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            f"     ðŸ” <b>2FA GENERATOR</b>\n"
            f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            f"ðŸ”‘ Send your <b>2FA Secret Key</b>\n"
            f"to instantly generate a 6-digit\nTOTP code.\n\n"
            f"ðŸ“Ž <b>Example Key:</b>\n"
            f"<code>JBSWY3DPEHPK3PXP</code>\n\n"
            f"ðŸ’¡ <i>Compatible with Google Authenticator,\nMicrosoft Authenticator & more!</i>"
        )
        kb = InlineKeyboardMarkup([[rbtn("âŒ Cancel", style="danger", callback_data="2fa_cancel")]])
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    # --- ADMIN MAIN MENU CATEGORIES ---
    if (text == "âš™ï¸ ADMIN PANEL" or text == "ADMIN PANEL") and is_admin(uid):
        await update.message.reply_text("âš™ï¸ <b>ADMIN CONTROL PANEL</b>", parse_mode="HTML", reply_markup=admin_main_keyboard())
        return

    if text == "âš™ï¸ SYSTEM CONFIG" and is_admin(uid):
        await update.message.reply_text("âš™ï¸ <b>SYSTEM CONFIGURATION</b>", parse_mode="HTML", reply_markup=admin_system_config_keyboard())
        return

    if text == "ðŸ’µ USER & BALANCE" and is_admin(uid):
        await update.message.reply_text("ðŸ’µ <b>USER & BALANCE MANAGEMENT</b>", parse_mode="HTML", reply_markup=admin_user_balance_keyboard())
        return

    if "SECURITY & JOIN" in text and is_admin(uid):
        await update.message.reply_text("ðŸ”’ <b>SECURITY & JOIN CONTROLS</b>", parse_mode="HTML", reply_markup=admin_security_join_keyboard())
        return

    if "FORCE CHANNELS" in text and is_admin(uid):
        settings = load_settings()
        ch_list = settings.get("force_join_channels", [])
        channels_text = "\n".join([f"â€¢ <code>{c}</code>" for c in ch_list]) if ch_list else "<i>à¦•à§‹à¦¨à§‹ à¦šà§à¦¯à¦¾à¦¨à§‡à¦² à¦¸à§‡à¦Ÿ à¦•à¦°à¦¾ à¦¨à§‡à¦‡</i>"
        msg = f"ðŸ“¢ <b>FORCE JOIN CHANNELS:</b>\n\n<b>à¦¬à¦°à§à¦¤à¦®à¦¾à¦¨ à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à¦¸à¦®à§‚à¦¹:</b>\n{channels_text}"
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=admin_force_channel_keyboard())
        return

    if "ADD CHANNEL" in text and is_admin(uid):
        context.user_data["admin_edit_mode"] = "add_force_channel"
        await update.message.reply_text("à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à§‡à¦° à¦‡à¦‰à¦œà¦¾à¦°à¦¨à§‡à¦® à¦¦à¦¿à¦¨ (à¦¯à§‡à¦®à¦¨: <code>@yourchannel</code>):", parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    if "DELETE CHANNEL" in text and is_admin(uid):
        context.user_data["admin_edit_mode"] = "del_force_channel"
        settings = load_settings()
        ch_list = settings.get("force_join_channels", [])
        channels_text = "\n".join([f"â€¢ <code>{c}</code>" for c in ch_list]) if ch_list else "<i>à¦•à§‹à¦¨à§‹ à¦šà§à¦¯à¦¾à¦¨à§‡à¦² à¦¨à§‡à¦‡</i>"
        await update.message.reply_text(f"à¦¯à§‡ à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à¦Ÿà¦¿ à¦¬à¦¾à¦¦ à¦¦à¦¿à¦¤à§‡ à¦šà¦¾à¦¨ à¦¤à¦¾à¦° à¦‡à¦‰à¦œà¦¾à¦°à¦¨à§‡à¦® à¦²à¦¿à¦–à§à¦¨:\n\n{channels_text}", parse_mode="HTML", reply_markup=cancel_keyboard())
        return

    if "BACK TO SECURITY" in text and is_admin(uid):
        await update.message.reply_text("ðŸ”’ <b>SECURITY & JOIN CONTROLS</b>", parse_mode="HTML", reply_markup=admin_security_join_keyboard())
        return
    if text == "ðŸ“¢ NOTICE & B-CAST" and is_admin(uid):
        await update.message.reply_text("ðŸ“¢ <b>NOTICE & BROADCASTING</b>", parse_mode="HTML", reply_markup=admin_notice_bcast_keyboard())
        return

    # --- ADMIN SYSTEM CONFIG ---
    if text == "ðŸ”‘ SET API KEY" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "api_key"
        await update.message.reply_text("Enter new API Key:", reply_markup=cancel_keyboard())
        return

    if text == "ðŸŒ SET API BASE URL" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "base_url"
        await update.message.reply_text("Enter new API Base URL:", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ“¢ SET OTP CHANNEL ID" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "otp_channel"
        await update.message.reply_text("Enter OTP Channel ID (e.g. -100xxxxxxxxxx or @channel):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ’° SET WITHDRAW LIMITS" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "withdraw_limits"
        await update.message.reply_text("Enter MIN and MAX withdraw limit separated by space (e.g. 0.5 100):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸŽ SET REFER BONUS" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "refer_bonus"
        await update.message.reply_text("Enter Referral Bonus Amount (e.g. 0.05):", reply_markup=cancel_keyboard())
        return

    if text == "â± SET COOLDOWN" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "cooldown"
        await update.message.reply_text("Enter Number Request Cooldown (in seconds):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸš« TOGGLE MAINTENANCE" and is_admin(uid):
        settings = load_settings()
        settings["maintenance_mode"] = not settings.get("maintenance_mode", False)
        save_settings(settings)
        status = "ENABLED" if settings["maintenance_mode"] else "DISABLED"
        await update.message.reply_text(f"ðŸ›  Maintenance Mode is now: <b>{status}</b>", parse_mode="HTML")
        return

    if ("LIVE CONSOLE" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("live_console_enabled", True)
        settings["live_console_enabled"] = not current
        save_settings(settings)
        new_state = settings["live_console_enabled"]
        icon = "ðŸŸ¢" if new_state else "ðŸ”´"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>Live Console Facebook OTP:</b> <b>{state_text}</b>\n\n"
            f"{'âœ… à¦à¦–à¦¨ Facebook OTP group-à¦ à¦†à¦¸à¦¬à§‡à¥¤' if new_state else 'â›” Facebook OTP group-à¦ à¦†à¦¸à¦¬à§‡ à¦¨à¦¾à¥¤'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    if ("TRAFFIC:" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("traffic_enabled", True)
        settings["traffic_enabled"] = not current
        save_settings(settings)
        new_state = settings["traffic_enabled"]
        icon = "ðŸŸ¢" if new_state else "ðŸ”´"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>TRAFFIC Feature:</b> <b>{state_text}</b>\n\n"
            f"{'âœ… Users can now see Traffic.' if new_state else 'â›” Traffic is hidden from users.'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    if ("LEADERBOARD:" in text.upper()) and is_admin(uid):
        settings = load_settings()
        current = settings.get("leaderboard_enabled", True)
        settings["leaderboard_enabled"] = not current
        save_settings(settings)
        new_state = settings["leaderboard_enabled"]
        icon = "ðŸŸ¢" if new_state else "ðŸ”´"
        state_text = "ON" if new_state else "OFF"
        await update.message.reply_text(
            f"{icon} <b>LEADERBOARD Feature:</b> <b>{state_text}</b>\n\n"
            f"{'âœ… Users can now see Leaderboard.' if new_state else 'â›” Leaderboard is hidden from users.'}",
            parse_mode="HTML",
            reply_markup=admin_system_config_keyboard()
        )
        return

    # --- ADMIN USER & BALANCE ---
    if text == "âž• ADD BALANCE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "add_balance"
        await update.message.reply_text("Enter USER_ID and AMOUNT (e.g. 123456789 5.0):", reply_markup=cancel_keyboard())
        return

    if text == "âž– REMOVE BALANCE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "remove_balance"
        await update.message.reply_text("Enter USER_ID and AMOUNT (e.g. 123456789 2.0):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ’¬ DIRECT MSG USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "direct_msg"
        await update.message.reply_text("Enter USER_ID and MESSAGE (e.g. 123456789 Hello):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ” SEARCH BY USERNAME" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "search_username"
        await update.message.reply_text("Enter Telegram Username (without @):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ“œ ALL USER BALANCE" and is_admin(uid):
        users = load_json(USER_DATA_FILE, {})
        tot_bal = sum(u.get("balance", 0.0) for u in users.values())
        lines = [f"Total Users: {len(users)} | Total Balance: {tot_bal:.4f}$\n"]
        for idx, (u_id, u_data) in enumerate(users.items(), 1):
            lines.append(f"{idx}. ID: {u_id} | Bal: {u_data.get('balance', 0.0):.4f}$")
        
        file_io = io.BytesIO("\n".join(lines).encode('utf-8'))
        file_io.name = "All_Users_Balance.txt"
        await update.message.reply_document(file_io, caption=f"ðŸ“Š Total System Balance: {tot_bal:.4f}$")
        return

    # --- ADMIN SECURITY & NOTICE ---
    if text == "ðŸš« BAN USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "ban_user"
        await update.message.reply_text("Enter USER_ID to ban:", reply_markup=cancel_keyboard())
        return

    if text == "âœ… UNBAN USER" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "unban_user"
        await update.message.reply_text("Enter USER_ID to unban:", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ“œ BAN USER LIST" and is_admin(uid):
        banned = load_json(BANNED_USERS_FILE, [])
        if not banned:
            await update.message.reply_text("ðŸ“œ <b>Banned Users (0):</b>\n\n<i>No users are banned.</i>", parse_mode="HTML")
        else:
            await update.message.reply_text(f"ðŸš« <b>Banned Users ({len(banned)}):</b>\n\n" + "\n".join(banned), parse_mode="HTML")
        return

    if text == "ðŸ“¢ BROADCAST NOTICE" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "broadcast"
        await update.message.reply_text("Enter text to broadcast to all users:", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ“ SET WELCOME MSG" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "welcome"
        await update.message.reply_text("Enter Welcome Text (HTML Supported):", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ’¬ SET SUPPORT USERNAME" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "support"
        await update.message.reply_text("Enter Support Telegram Username:", reply_markup=cancel_keyboard())
        return

    if text == "ðŸ”— SET CHANNEL LINK" and is_admin(uid):
        context.user_data["admin_edit_mode"] = "channel_link"
        await update.message.reply_text("Enter Channel Link:", reply_markup=cancel_keyboard())
        return

    if text in ["ðŸ”™ BACK TO ADMIN", "BACK TO ADMIN", "ðŸ”™ BACK TO MAIN", "BACK TO MAIN"]:
        await update.message.reply_text("Main Menu.", reply_markup=main_keyboard(uid))
        return

# ==================== CALLBACK QUERY HANDLER ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    # ==================== 2FA CALLBACKS ====================

    if data == "2fa_cancel":
        # 2fa mode à¦¬à¦¾à¦¤à¦¿à¦² à¦•à¦°à¦¾
        context.user_data.pop("2fa_mode", None)
        context.user_data.pop("2fa_secret", None)
        try:
            await query.message.delete()
        except:
            pass
        return

    if data == "2fa_refresh":
        secret = context.user_data.get("2fa_secret")
        if not secret:
            await query.answer("âš ï¸ Session expired! Please type 2FA SETUP again.", show_alert=True)
            return

        code, remaining = generate_totp(secret)
        if not code:
            await query.answer("âŒ Failed to generate code!", show_alert=True)
            return

        msg = format_2fa_message(secret, code, remaining)
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ”„ Refresh Code", style="success", callback_data="2fa_refresh")],
            [rbtn("âŒ Close", style="danger", callback_data="2fa_close")]
        ])
        try:
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            # Message unchanged à¦¹à¦²à§‡ Telegram error à¦¦à§‡à¦¯à¦¼, à¦¸à§‡à¦Ÿà¦¾ ignore à¦•à¦°à§‹
            pass
        return

    if data == "2fa_close":
        context.user_data.pop("2fa_secret", None)
        context.user_data.pop("2fa_mode", None)
        try:
            await query.message.delete()
        except:
            pass
        return

    if data == "check_join":
        if await check_force_sub(update, context):
            try:
                await query.message.delete()
            except:
                pass
            await query.message.reply_text("âœ… à¦§à¦¨à§à¦¯à¦¬à¦¾à¦¦! à¦¸à¦«à¦²à¦­à¦¾à¦¬à§‡ à¦¯à¦¾à¦šà¦¾à¦‡ à¦•à¦°à¦¾ à¦¹à¦¯à¦¼à§‡à¦›à§‡à¥¤", reply_markup=main_keyboard(uid))
        else:
            await query.answer("âŒ à¦†à¦ªà¦¨à¦¿ à¦à¦–à¦¨à§‹ à¦¸à¦¬ à¦šà§à¦¯à¦¾à¦¨à§‡à¦²à§‡ à¦œà¦¯à¦¼à§‡à¦¨ à¦•à¦°à§‡à¦¨à¦¨à¦¿!", show_alert=True)
        return

    if data.startswith("sel_app_"):
        app_name = data.replace("sel_app_", "")
        top_ranges = context.user_data.get("top_ranges", {})
        ranges = top_ranges.get(app_name, [])
        if not ranges:
            await query.edit_message_text("âŒ No ranges available for this service.")
            return

        country_map_data = {}
        for rng in ranges:
            flag, cname = get_country_info(rng)
            c_key = f"{flag} {cname}"
            if c_key not in country_map_data:
                country_map_data[c_key] = []
            country_map_data[c_key].append(rng)

        if "country_ranges" not in context.user_data:
            context.user_data["country_ranges"] = {}

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

        buttons.append([rbtn("ðŸ”™ Back to Services", style="danger", callback_data="back_to_services")])
        icon = get_service_icon(app_name)
        await query.edit_message_text(
            f"ðŸŒ <b>SELECT COUNTRY</b>\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"{icon} <b>{app_name}</b> â€” choose your region:",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("sel_cty_"):
        c_idx = data.replace("sel_cty_", "")
        c_info = context.user_data.get("country_ranges", {}).get(c_idx)
        if not c_info:
            await query.edit_message_text("âŒ Session expired. Please click GET NUMBER again.")
            return

        app_name = c_info["app"]
        country_label = c_info["label"]
        ranges = c_info["ranges"]

        selected_range = random.choice(ranges)
        last_range[uid] = selected_range
        context.user_data["current_app"] = app_name

        await query.edit_message_text(f"â³ <b>Searching number for {app_name} ({country_label})...</b>", parse_mode="HTML")
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

    if data == "back_to_services":
        top_ranges = context.user_data.get("top_ranges", {})
        if not top_ranges:
            await query.edit_message_text("âŒ Session expired. Please click GET NUMBER again.")
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
        await query.edit_message_text(
            "ðŸ“² <b>SELECT SERVICE</b>\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            "<i>Choose a platform to get a virtual number:</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "change_country":
        app_name = context.user_data.get("current_app", "")
        top_ranges = context.user_data.get("top_ranges", {})
        
        if not top_ranges:
            top_ranges, err = await fetch_top_ranges()
            if err or not top_ranges:
                await query.answer("âŒ Could not load services. Try again.", show_alert=True)
                return
            context.user_data["top_ranges"] = top_ranges

        if not app_name or app_name not in top_ranges:
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
            await query.edit_message_text(
            "ðŸ“² <b>SELECT SERVICE</b>\n"
            "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            "<i>Choose a platform to get a virtual number:</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
            return

        ranges = top_ranges.get(app_name, [])
        if not ranges:
            await query.answer("âŒ No ranges available.", show_alert=True)
            return

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

        buttons.append([rbtn("ðŸ”™ Back to Services", style="danger", callback_data="back_to_services")])
        icon_cc = get_service_icon(app_name)
        await query.edit_message_text(
            f"ðŸŒ <b>CHANGE COUNTRY</b>\n"
            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
            f"{icon_cc} <b>{app_name}</b> â€” select a new region:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "same_range":
        r_text = last_range.get(uid)
        if r_text:
            app_name = context.user_data.get("current_app", "Facebook")
            icon = get_service_icon(app_name)
            await query.edit_message_text(
                f"ðŸ”„ <b>Getting New Number...</b>\n\n"
                f"{icon} <b>{app_name}</b> â€” searching...",
                parse_mode="HTML"
            )
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
            await query.answer("âš ï¸ No previous range found! Please select a service.", show_alert=True)
        return

    if data == "set_method":
        kb = InlineKeyboardMarkup([
            [rbtn("ðŸ’š Bkash", style="primary", callback_data="m_Bkash"),
             rbtn("ðŸŸ  Nagad", style="primary", callback_data="m_Nagad")],
            [rbtn("ðŸ”µ Rocket", style="primary", callback_data="m_Rocket"),
             rbtn("ðŸŸ¡ Binance", style="primary", callback_data="m_Binance")]
        ])
        await query.edit_message_text(
            "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
            "   ðŸ¦ <b>PAYMENT METHOD</b>\n"
            "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
            "Select your preferred withdrawal method:",
            parse_mode="HTML", reply_markup=kb
        )
        return

    if data.startswith("m_"):
        method_name = data.replace("m_", "")
        users = load_json(USER_DATA_FILE, {})
        if str(uid) in users:
            users[str(uid)]["withdrawal_method"] = method_name
            save_json(USER_DATA_FILE, users)
            await query.edit_message_text(
                f"âœ… <b>Payment Method Set!</b>\n\n"
                f"ðŸ¦ Method: <b>{method_name}</b>\n\n"
                f"<i>You can now withdraw your earnings.</i>",
                parse_mode="HTML"
            )
        return

    if data == "init_withdraw":
        u_info = get_user(uid)
        m_method = u_info.get("withdrawal_method")
        if not m_method:
            await query.answer("âŒ Please set a payment method first!", show_alert=True)
            return

        settings = load_settings()
        if u_info["balance"] < settings["min_withdraw"]:
            await query.answer(f"âŒ Minimum withdrawal is ${settings['min_withdraw']}", show_alert=True)
            return

        context.user_data["withdraw_method"] = m_method
        context.user_data["withdraw_mode"] = "amount"
        await query.message.reply_text(
            f"ðŸ’µ <b>Enter Withdrawal Amount</b>\n\n"
            f"ðŸ¦ Method: <b>{m_method}</b>\n"
            f"ðŸ’° Balance: <code>${u_info['balance']:.4f}</code>\n"
            f"ðŸ“Š Range: <code>${settings['min_withdraw']}</code> â€” <code>${settings['max_withdraw']}</code>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        return

    if data.startswith("adm_app_"):
        pid = data.replace("adm_app_", "")
        w_reqs = load_json(WITHDRAW_DATA_FILE, {})
        if pid in w_reqs and w_reqs[pid]["status"] == "pending":
            w_reqs[pid]["status"] = "approved"
            save_json(WITHDRAW_DATA_FILE, w_reqs)

            u_id = w_reqs[pid]["user_id"]
            amt = w_reqs[pid]["amount"]
            method = w_reqs[pid].get("method", "N/A")
            try:
                await context.bot.send_message(
                    u_id,
                    f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                    f"  âœ… <b>WITHDRAWAL APPROVED!</b>\n"
                    f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                    f"ðŸŽ‰ Your withdrawal has been processed!\n\n"
                    f"ðŸ¦ <b>Method:</b> {method}\n"
                    f"ðŸ’µ <b>Amount:</b> <code>${amt:.4f}</code>\n"
                    f"ðŸ”– <b>PID:</b> <code>{pid}</code>\n\n"
                    f"â± <i>Payment will arrive shortly.</i>",
                    parse_mode="HTML"
                )
            except: pass

            await query.edit_message_text(f"âœ… <b>Approved!</b> PID: <code>{pid}</code>", parse_mode="HTML")
        return

    if data.startswith("adm_rej_"):
        pid = data.replace("adm_rej_", "")
        w_reqs = load_json(WITHDRAW_DATA_FILE, {})
        if pid in w_reqs and w_reqs[pid]["status"] == "pending":
            w_reqs[pid]["status"] = "rejected"
            save_json(WITHDRAW_DATA_FILE, w_reqs)

            u_id = w_reqs[pid]["user_id"]
            amt = w_reqs[pid]["amount"]
            method = w_reqs[pid].get("method", "N/A")

            await update_db_balance(u_id, amt)

            try:
                await context.bot.send_message(
                    u_id,
                    f"â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—\n"
                    f"  âŒ <b>WITHDRAWAL REJECTED</b>\n"
                    f"â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n\n"
                    f"ðŸ˜” Your withdrawal was not approved.\n\n"
                    f"ðŸ¦ <b>Method:</b> {method}\n"
                    f"ðŸ’µ <b>Amount:</b> <code>${amt:.4f}</code> â†©ï¸ <i>Refunded</i>\n"
                    f"ðŸ”– <b>PID:</b> <code>{pid}</code>\n\n"
                    f"ðŸ’¡ <i>Contact support if you have questions.</i>",
                    parse_mode="HTML"
                )
            except: pass

            await query.edit_message_text(f"âŒ <b>Rejected.</b> PID: <code>{pid}</code>  â€” Amount refunded.", parse_mode="HTML")
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

    print("ðŸš€ BOT RUNNING WITH FULL FEATURES...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
