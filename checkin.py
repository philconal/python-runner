import re
import json
import argparse
import requests
from urllib.parse import urlparse, parse_qs


START_URL = "https://blueprint.cyberlogitec.com.vn/sso/login"
UI_PAGE = "https://blueprint.cyberlogitec.com.vn/UI_TAT_028"
CHECKIN_API = "https://blueprint.cyberlogitec.com.vn/api/checkInOut/insert"


def to_absolute_url(base_url: str, location: str):
    if not location:
        return None
    if location.startswith("http"):
        return location
    if location.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{location}"
    return location


def extract_login_action(html: str):
    match = re.search(r'action="([^"]+login-actions/authenticate[^"]+)"', html)
    if not match:
        raise Exception("Cannot find login form action URL in HTML")
    return match.group(1).replace("&amp;", "&")


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session


def parse_accounts(args):
    accounts = []

    if args.accounts:
        for raw_account in args.accounts:
            if ":" not in raw_account:
                raise ValueError(f"Invalid account format: {raw_account}. Use username:password")
            username, password = raw_account.split(":", 1)
            username = username.strip()
            if not username:
                raise ValueError(f"Username is empty in account: {raw_account}")
            accounts.append((username, password))

    if args.accounts_json:
        with open(args.accounts_json, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        if not isinstance(json_data, list):
            raise ValueError("JSON file must be a list of accounts")

        for idx, item in enumerate(json_data):
            if not isinstance(item, dict):
                raise ValueError(f"Account at index {idx} must be an object")

            username = str(item.get("username", "")).strip()
            password = str(item.get("password", ""))

            if not username:
                raise ValueError(f"Missing or empty username at index {idx}")

            accounts.append((username, password))

    if accounts:
        return accounts

    return [(USERNAME, PASSWORD)]


def run_checkin(username: str, password: str):
    session = create_session()

    print(f"\n================= ACCOUNT: {username} =================")
    print("====================================================")
    print("[1] Start flow from Blueprint /sso/login")
    print("====================================================")

    r1 = session.get(START_URL, allow_redirects=False, timeout=30)

    print("Blueprint /sso/login status:", r1.status_code)
    redirect1 = r1.headers.get("Location")
    print("Redirect ->", redirect1)

    state_cookie = session.cookies.get("OAuth_Token_Request_State")
    print("OAuth_Token_Request_State cookie:", state_cookie)

    if not state_cookie:
        raise Exception("Missing OAuth_Token_Request_State cookie")

    if not redirect1:
        raise Exception("Blueprint did not redirect to Keycloak authorize URL")

    auth_url = to_absolute_url(START_URL, redirect1)

    print("====================================================")
    print("[2] Redirect to Keycloak authorize URL")
    print("====================================================")
    print("Auth URL:", auth_url)

    r2 = session.get(auth_url, allow_redirects=True, timeout=30)

    print("Keycloak login page status:", r2.status_code)
    print("Final URL:", r2.url)

    html = r2.text

    print("====================================================")
    print("[3] Extract login form action")
    print("====================================================")

    login_action_url = extract_login_action(html)
    print("Login Action URL:", login_action_url)

    print("====================================================")
    print("[4] Submit username/password")
    print("====================================================")

    payload = {
        "username": username,
        "password": password,
        "rememberMe": "on",
        "credentialId": ""
    }

    r3 = session.post(login_action_url, data=payload, allow_redirects=False, timeout=30)

    print("Login POST status:", r3.status_code)
    redirect2 = r3.headers.get("Location")
    print("Redirect after login ->", redirect2)

    if r3.status_code not in (302, 303):
        print("Login failed snippet:")
        print(r3.text[:1200])
        raise Exception("Login failed")

    final_blueprint_url = to_absolute_url(login_action_url, redirect2)

    print("====================================================")
    print("[5] Blueprint callback URL (contains code)")
    print("====================================================")
    print(final_blueprint_url)

    if "code=" not in final_blueprint_url:
        raise Exception("Redirect URL does not contain code")

    print("====================================================")
    print("[6] Call blueprint callback URL to create JSESSIONID")
    print("====================================================")

    r4 = session.get(final_blueprint_url, allow_redirects=True, timeout=30)

    print("Blueprint callback status:", r4.status_code)
    print("Blueprint final URL:", r4.url)

    jsession = session.cookies.get("JSESSIONID")
    print("JSESSIONID:", jsession)

    if not jsession:
        print("Cookies currently:")
        for c in session.cookies:
            print("   ", c.name, "=", c.value)
        raise Exception("JSESSIONID not created. Cannot call checkin API.")

    print("====================================================")
    print("[7] Open UI page (optional)")
    print("====================================================")

    session.get(UI_PAGE, allow_redirects=True, timeout=30)

    print("====================================================")
    print("[8] Call CheckIn API")
    print("====================================================")

    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://blueprint.cyberlogitec.com.vn",
        "Referer": UI_PAGE
    }

    api_resp = session.post(CHECKIN_API, headers=api_headers, timeout=30)

    print("Checkin status:", api_resp.status_code)
    print("Checkin response:", api_resp.text)


def main():
    parser = argparse.ArgumentParser(
        description="Run Blueprint checkin for one or many accounts."
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        help='List accounts in format "username:password". Example: --accounts "u1:p1" "u2:p2"',
    )
    parser.add_argument(
        "--accounts-json",
        help='Path to JSON file containing accounts list. Example: [{"username":"u1","password":"p1"}]',
    )
    args = parser.parse_args()

    accounts = parse_accounts(args)

    success_count = 0
    failed_accounts = []

    for username, password in accounts:
        try:
            run_checkin(username, password)
            success_count += 1
        except Exception as ex:
            print(f"\n[FAILED] {username}: {ex}")
            failed_accounts.append(username)

    print("\n================= RESULT =================")
    print(f"Total accounts: {len(accounts)}")
    print(f"Success: {success_count}")
    print(f"Failed: {len(failed_accounts)}")
    if failed_accounts:
        print("Failed accounts:", ", ".join(failed_accounts))


if __name__ == "__main__":
    main()