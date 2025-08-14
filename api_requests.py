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