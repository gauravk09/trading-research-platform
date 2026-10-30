"""
auth.py — Kite Connect login and access token management

Kite access tokens expire every day at 6 AM IST.
This module handles generating a new token each day.

HOW TO USE:
    Step 1 (one-time): Run `python src/auth.py` in terminal
    Step 2: It opens a browser login URL — log in with your Zerodha credentials
    Step 3: You are redirected to your redirect URL with ?request_token=XXXX in the URL
    Step 4: Paste that request_token when prompted
    Step 5: Your .env file is updated automatically with the new access token
"""

import os
import webbrowser
from dotenv import load_dotenv, set_key
from kiteconnect import KiteConnect

ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def get_kite_client():
    """Return an authenticated KiteConnect client using the stored access token."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv("KITE_API_KEY")
    access_token = os.getenv("KITE_ACCESS_TOKEN")

    if not api_key or not access_token:
        raise ValueError("KITE_API_KEY or KITE_ACCESS_TOKEN missing in .env")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite


def generate_access_token():
    """
    Interactive flow to generate a fresh Kite access token.
    Run this script directly each morning before data collection.
    """
    load_dotenv(ENV_FILE)
    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")

    if not api_key or not api_secret:
        print("ERROR: KITE_API_KEY and KITE_API_SECRET must be set in .env first.")
        print("Get them from: https://developers.kite.trade/apps")
        return

    kite = KiteConnect(api_key=api_key)

    login_url = kite.login_url()
    print(f"\nOpening Kite login page in browser...")
    print(f"If it doesn't open, go here manually:\n{login_url}\n")
    webbrowser.open(login_url)

    request_token = input("After logging in, paste the request_token from the redirect URL: ").strip()

    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]

    set_key(ENV_FILE, "KITE_ACCESS_TOKEN", access_token)
    print(f"\nAccess token saved to .env successfully.")
    print(f"Token: {access_token[:10]}...{access_token[-5:]}")


if __name__ == "__main__":
    generate_access_token()
