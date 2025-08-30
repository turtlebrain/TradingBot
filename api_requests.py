import os
from pathlib import Path
import requests
import webbrowser
import json
import sys

# ── CONFIG ─────────────────────────────────────────────────────────────────────
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)
    
CLIENT_ID    = os.getenv("QUESTRADE_API_CLIENT_ID")
REDIRECT_URI = os.getenv("GROK_REDIRECT_URI")   # http tunnelling service URL

if not CLIENT_ID or not REDIRECT_URI:
    raise RuntimeError("Please set the QUESTRADE_CLIENT_ID and GROK_REDIRECT_URI environment variables.")
# ── END CONFIG ───────────────────────────────────────────────────────────────

# ── QUESTRADE ENDPOINTS ────────────────────────────────────────────────────────────
AUTH_BASE_URL  = "https://login.questrade.com/oauth2/authorize"
TOKEN_BASE_URL = "https://login.questrade.com/oauth2/token"
# ── END QUESTRADE ENDPOINTS ───────────────────────────────────────────────────────

def build_auth_url():
    """
    Constructs the URL where the user must log in and authorize your app.
    """
    params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
    }
    req = requests.Request("GET", AUTH_BASE_URL, params=params).prepare()
    return req.url


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchanges the one-time 'code' for an access token, refresh token, etc.
    """
    params = {
        "client_id":    CLIENT_ID,
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.get(TOKEN_BASE_URL, params=params)
    resp.raise_for_status()
    return resp.json()

def get_candlestick_data(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Fetches candlestick data for a given stock symbol between specified dates.
    """
    # Placeholder for actual API call to fetch candlestick data
    # This function should be implemented to interact with Questrade's API
    return {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "data": [
            {"date": "2023-01-01", "open": 100, "high": 105, "low": 95, "close": 102},
            {"date": "2023-01-02", "open": 102, "high": 107, "low": 97, "close": 104},
        ]
    }
    
def get_stock_data(access_token, api_server, symbol_str):
    url = f"{api_server}/v1/symbols/search"
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    params = {
        'prefix': symbol_str
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status() 
    return response.json()['symbols']