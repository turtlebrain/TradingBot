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


if __name__ == "__main__":
    # 1) Ask user to authorize
    print("\n1) Open this URL in your browser and log in:")
    auth_url = build_auth_url()
    print(auth_url)

    # Optionally auto-open the browser:
    try:
        webbrowser.open(auth_url)
    except:
        pass

    # 2) User pastes back the 'code' from the redirect URL
    print("\n2) After logging in, you’ll be redirected to:")
    print(f"   {REDIRECT_URI}?code=YOUR_CODE_HERE\n")
    code = input("   Paste the value of 'code' here: ").strip()
    if not code:
        print("No code provided, exiting.")
        sys.exit(1)

    # 3) Exchange code for tokens
    print("\n3) Exchanging code for tokens…")
    token_data = exchange_code_for_tokens(code)

    # 4) Show & persist tokens
    print("\n🚀 Success! Here’s what Questrade returned:\n")
    print(json.dumps(token_data, indent=2))

    # Save to file for later use
    with open("questrade_tokens.json", "w") as f:
        json.dump(token_data, f, indent=2)
    print("\nTokens saved to questrade_tokens.json")

    # 5) (Optional) Test an API call
    api_server   = token_data["api_server"]
    access_token = token_data["access_token"]
    headers      = {"Authorization": f"Bearer {access_token}"}

    print("\n4) Testing a simple API call (/v1/accounts)…")
    r = requests.get(f"{api_server}v1/accounts", headers=headers)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))