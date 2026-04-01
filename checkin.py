import re
import argparse
import requests
import sys
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo  # Python 3.9+

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
    if len(parts) != 2:
        raise ValueError("Format must be username:password")

    username, password = parts
    username = username.strip()

    if not username:
        raise ValueError("Username is empty")

    return username, password


# ================= TIME =================
def get_timestamp():
    vn_time = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    return vn_time.strftime("%d/%m/%Y %H:%M:%S")


# ================= CHECK SKIP =================
def check_skip_day():
    vn_holidays = set()
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    weekday = today.weekday()  # 0=Monday ... 6=Sunday

    if today.date() in vn_holidays:
        return "Ngày lễ"
    elif weekday >= 5:
        return "Thứ 7/Chủ nhật"
    return None


# ================= CORE LOGIC =================
def run_checkin(username: str, password: str):
    session = create_session()
    start_time = time.time()
    timestamp = get_timestamp()

    skip_reason = check_skip_day()
    if skip_reason:
        duration = time.time() - start_time
        return {
            "success": False,
            "code": 0,
            "message": "Check-in skip",
            "skip_reason": skip_reason,
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }

    try:
        # STEP 1
        r1 = session.get(START_URL, allow_redirects=False, timeout=30)
        if not r1.ok:
            raise CheckinError(r1.status_code, f"HTTP error at /sso/login: {r1.status_code}")

        redirect1 = r1.headers.get("Location")
        state_cookie = session.cookies.get("OAuth_Token_Request_State")

        if not state_cookie:
            raise CheckinError(1001, "Missing OAuth cookie")
        if not redirect1:
            raise CheckinError(1002, "No redirect to Keycloak")

        # STEP 2
        auth_url = to_absolute_url(START_URL, redirect1)
        r2 = session.get(auth_url, allow_redirects=True, timeout=30)

        if not r2.ok:
            raise CheckinError(r2.status_code, f"HTTP error at Keycloak login page: {r2.status_code}")

        login_action_url = extract_login_action(r2.text)

        # STEP 3
        payload = {
            "username": username,
            "password": password,
            "rememberMe": "on",
            "credentialId": ""
        }

        r3 = session.post(login_action_url, data=payload, allow_redirects=False, timeout=30)

        if r3.status_code not in (200, 302, 303):
            raise CheckinError(r3.status_code, f"Login failed: {r3.status_code}")

        redirect2 = r3.headers.get("Location")
        if not redirect2 or "code=" not in redirect2:
            raise CheckinError(1004, "Missing authorization code in redirect URL")

        # STEP 4
        final_url = to_absolute_url(login_action_url, redirect2)
        r4 = session.get(final_url, allow_redirects=True, timeout=30)

        if not r4.ok:
            raise CheckinError(r4.status_code, f"HTTP error at blueprint callback: {r4.status_code}")

        jsession = session.cookies.get("JSESSIONID")
        if not jsession:
            raise CheckinError(1005, "JSESSIONID not found")

        # STEP 5
        session.get(UI_PAGE, allow_redirects=True, timeout=30)

        # STEP 6
        api_headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://blueprint.cyberlogitec.com.vn",
            "Referer": UI_PAGE
        }

        api_resp = session.post(CHECKIN_API, headers=api_headers, timeout=30)

        if api_resp.status_code != 200:
            raise CheckinError(api_resp.status_code, f"Check-in API error: {api_resp.status_code}")

        duration = time.time() - start_time
        return {
            "success": True,
            "code": 0,
            "message": "Success",
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
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }

    except requests.RequestException as e:
        duration = time.time() - start_time
        return {
            "success": False,
            "code": getattr(e.response, "status_code", 503),
            "message": str(e),
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
            "username": username,
            "timestamp": timestamp,
            "duration_ms": int(duration * 1000),
            "duration_sec": round(duration, 2)
        }


# ================= MAIN =================
def main():
    parser = argparse.ArgumentParser(description="Blueprint auto checkin (JSON output)")

    parser.add_argument("--account", required=False, help="username:password")
    parser.add_argument("--username", required=False, help="username")
    parser.add_argument("--password", required=False, help="password")

    args = parser.parse_args()

    try:
        if args.account:
            username, password = parse_account(args.account)
        else:
            if not args.username or not args.password:
                raise ValueError("Missing --username / --password")

            username = args.username.strip()
            password = args.password

        result = run_checkin(username, password)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result["success"] else 1)

    except Exception as e:
        output = {
            "success": False,
            "code": 2,
            "message": f"Input error: {str(e)}",
            "username": getattr(args, "username", None),
            "timestamp": get_timestamp(),
            "duration_ms": 0,
            "duration_sec": 0
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(2)


if __name__ == "__main__":
    main()