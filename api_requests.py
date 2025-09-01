import os
from pathlib import Path
import requests
from datetime import datetime, timedelta
import pytz

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

def get_candlestick_data(access_token, api_server, symbol_id, start_date, end_date): 
    """
    Fetches candlestick data for a given stock symbol between specified dates. T
    This request is limited to a maximum of 20 datapoints per call by Questrade.
    """
    eastern = pytz.timezone('US/Eastern')
    start = eastern.localize(datetime.combine(start_date, datetime.min.time())).isoformat()
    end = eastern.localize(datetime.combine(end_date,datetime.min.time())).isoformat()
    url = f"{api_server}v1/markets/candles/{symbol_id}?startTime={start}&endTime={end}&interval=OneDay"
    headers = get_headers(access_token)
    response = requests.get(url, headers=headers)
    response.raise_for_status() 
    return response.json()['candles']

def get_candles_paginated(access_token, api_server, symbol_id, start_date, end_date, interval='OneDay', max_points=20):
    """
    Fetches candlestick data from Questrade API in paginated chunks.

    :param symbol_id: Questrade symbol ID (int)
    :param start_date: datetime object for the start of the range
    :param end_date: datetime object for the end of the range
    :param access_token: Questrade API OAuth access token (string)
    :param interval: Candle interval, default 'OneDay'
    :param max_points: Max candles per request (Questrade default ~20)
    :return: List of candle dictionaries
    """
    eastern = pytz.timezone('US/Eastern')
    
    candles = []
    current_start = start_date

    headers = get_headers(access_token)

    while current_start < end_date:
        # Calculate chunk end date based on max_points
        current_end = min(current_start + timedelta(days=max_points), end_date)

        url = f"{api_server}v1/markets/candles/{symbol_id}"
        params = {
            'startTime': eastern.localize(datetime.combine(current_start, datetime.min.time())).isoformat(),
            'endTime': eastern.localize(datetime.combine(current_end, datetime.min.time())).isoformat(),
            'interval': interval
        }

        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json().get('candles', [])

        candles.extend(data)

        # Move to the next chunk
        current_start = current_end

    return candles

def get_stock_data(access_token, api_server, symbol_str):
    url = f"{api_server}v1/symbols/search"
    headers = get_headers(access_token)
    params = {
        'prefix': symbol_str
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status() 
    return response.json()['symbols']

def get_headers(access_token):
    return {
        'Authorization': f'Bearer {access_token}'
    }
