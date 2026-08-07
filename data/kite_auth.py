"""
Handles Kite Connect authentication.
Run this once each morning before market open — Kite access tokens expire daily.
"""
import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")


def get_kite_session():
    kite = KiteConnect(api_key=API_KEY)
    print("Login here, then paste the request_token from the redirect URL:")
    print(kite.login_url())
    request_token = input("Enter request_token: ").strip()

    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    # Save it so other scripts can reuse it without logging in again today
    with open(".env", "a") as f:
        pass  # we'll update KITE_ACCESS_TOKEN properly below

    _update_env_token(access_token)
    kite.set_access_token(access_token)
    print("Session ready. Access token saved to .env")
    return kite


def _update_env_token(token):
    """Rewrites KITE_ACCESS_TOKEN line in .env with the fresh token."""
    lines = []
    found = False
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith("KITE_ACCESS_TOKEN="):
            lines[i] = f"KITE_ACCESS_TOKEN={token}\n"
            found = True
            break
    if not found:
        lines.append(f"KITE_ACCESS_TOKEN={token}\n")

    with open(".env", "w") as f:
        f.writelines(lines)


if __name__ == "__main__":
    get_kite_session()
