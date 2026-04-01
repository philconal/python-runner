import re
import argparse
import requests
import sys
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo   # ✅ built-in Python 3.9+


START_URL = "https://blueprint.cyberlogitec.com.vn/sso/login"
UI_PAGE = "https://blueprint.cyberlogitec.com.vn/UI_TAT_028"
CHECKIN_API = "https://blueprint.cyberlogitec.com.vn/api/checkInOut/insert"


# ================= ERROR CLASS =================
class CheckinError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ================= UTIL =================
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
        raise CheckinError(1007, "Cannot find login form action URL")
    return match.group(1).replace("&amp;", "&")


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    return session


# ================= PARSE ACCOUNT =================
def parse_account(raw: str):
    parts = raw.split(":")

    if len(parts) != 3:
        raise ValueError("Format must be username:password:email")

    username, password, email = parts

    username = username.strip()
    email = email.strip()

    if not username:
        raise ValueError("Username is empty")

    if not email:
        raise ValueError("Email is empty")

    return username, password, email


# ================= TIME (FIXED) =================
def get_timestamp():
    vn_time = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    return vn_time.strftime("%d/%m/%Y %H:%M:%S")  # ✅ 24h format


# ================= CORE LOGIC =================
def run_checkin(username: str, password: str, email: str):
    session = create_session()

    start_time = time.time()
    timestamp = get_timestamp()

    try:
        r1 = session.get(START_URL, allow_redirects=False, timeout=30)

        redirect1 = r1.headers.get("Location")
        state_cookie = session.cookies.get("OAuth_Token_Request_State")

        if not state_cookie:
            raise CheckinError(1001, "Missing OAuth cookie")

        if not redirect1:
            raise CheckinError(1002, "No redirect to Keycloak")

        auth_url = to_absolute_url(START_URL, redirect1)
        r2 = session.get(auth_url, allow_redirects=True, timeout=30)

        login_action_url = extract_login_action(r2.text)

        payload = {
            "username": username,
            "password": password,
            "rememberMe": "on",
            "credentialId": ""
        }

        r3 = session.post(login_action_url, data=payload, allow_redirects=False, timeout=30)

        redirect2 = r3.headers.get("Location")

        if r3.status_code not in (302, 303):
            raise CheckinError(1003, "Login failed")

        final_url = to_absolute_url(login_action_url, redirect2)

        if "code=" not in final_url:
            raise CheckinError(1004, "Missing authorization code")

        session.get(final_url, allow_redirects=True, timeout=30)

        jsession = session.cookies.get("JSESSIONID")
        if not jsession:
            raise CheckinError(1005, "JSESSIONID not found")

        session.get(UI_PAGE, allow_redirects=True, timeout=30)

        api_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://blueprint.cyberlogitec.com.vn",
            "Referer": UI_PAGE
        }

        api_resp = session.post(CHECKIN_API, headers=api_headers, timeout=30)

        if api_resp.status_code != 200:
            raise CheckinError(1006, api_resp.text)

        duration = time.time() - start_time

        return {
            "success": True,
            "code": 0,
            "message": "Success",
            "email": email,
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }

    except CheckinError as e:
        duration = time.time() - start_time

        return {
            "success": False,
            "code": e.code,
            "message": e.message,
            "email": email,
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }

    except Exception as e:
        duration = time.time() - start_time

        return {
            "success": False,
            "code": 9999,
            "message": str(e),
            "email": email,
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }


# ================= MAIN =================
def main():
    parser = argparse.ArgumentParser(description="Blueprint auto checkin (n8n ready)")
    parser.add_argument("--account", required=True, help="username:password:email")

    args = parser.parse_args()

    try:
        username, password, email = parse_account(args.account)
    except Exception as e:
        output = {
            "success": False,
            "code": 2,
            "message": f"Input error: {str(e)}",
            "email": None,
            "username": None,
            "timestamp": get_timestamp(),
            "duration_ms": 0,
            "duration_sec": 0
        }
        print(json.dumps(output))
        sys.exit(2)

    result = run_checkin(username, password, email)

    print(json.dumps(result, ensure_ascii=False))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()