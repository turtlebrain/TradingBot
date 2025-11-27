import os
from pathlib import Path
from datetime import datetime, timedelta
import pytz
import requests
from typing import Any, Dict, List
from Brokers.broker_interface import BrokerInterface

from request_wrapper import LoggedSession
from log_writter import LogWriter

AUTH_BASE_URL  = "https://login.questrade.com/oauth2/authorize"
TOKEN_BASE_URL = "https://login.questrade.com/oauth2/token"

class QuestradeBroker(BrokerInterface):
    """Concrete broker for Questrade using OAuth and REST."""

    def __init__(self, env: str = "practice", actor_id: str = "QuestradeBroker"):
        # Initialize logging
        self.log_dir = os.path.join(os.getcwd(), "logs")
        self.hmac_key = os.environ["LOG_HMAC_KEY"].encode()
        self.log = LogWriter(base_dir=self.log_dir, hmac_key=self.hmac_key, app_env=env)
        self.log.start_session()
        self.http = LoggedSession(log=self.log, env=env, actor_id=actor_id)

        # Load environment variables
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path)

        self.client_id = os.getenv("QUESTRADE_API_CLIENT_ID")
        self.redirect_uri = os.getenv("GROK_REDIRECT_URI")

        if not self.client_id or not self.redirect_uri:
            raise RuntimeError("Please set QUESTRADE_API_CLIENT_ID and GROK_REDIRECT_URI.")

        # Session state placeholders
        self.access_token: str = ""
        self.refresh_token_value: str = ""
        self.api_server: str = ""  # e.g., https://api01.iq.questrade.com/

    def authenticate(self) -> Dict[str, Any]:
        # Build the authorization URL users visit to grant access
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
        }
        req = requests.Request("GET", AUTH_BASE_URL, params=params).prepare()
        auth_url = req.url

        return {"auth_url": auth_url}

    def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        # Exchange the one-time code for tokens and API server
        params = {
            "client_id":    self.client_id,
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": self.redirect_uri,
        }
        resp = self.http.get(TOKEN_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        # Persist tokens and server base
        self.access_token = data["access_token"]
        self.refresh_token_value = data["refresh_token"]
        self.api_server = data["api_server"]
        return data

    def complete_auth(self, code: str) -> Dict[str, Any]:
        data = self.exchange_code_for_tokens(code)
        return {
            "api_server": data.get("api_server"),
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
        }


    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        # Use refresh token to obtain new access token
        params = {
            "client_id":     self.client_id,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        }
        resp = self.http.get(TOKEN_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        # Update session state
        self.access_token = data["access_token"]
        self.refresh_token_value = data["refresh_token"]
        self.api_server = data["api_server"]
        return data

    def _headers(self) -> Dict[str, str]:
        # Authorization header required for Questrade API calls
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_symbols(self, query: str) -> List[Dict[str, Any]]:
        # Search for symbols by prefix
        url = f"{self.api_server}v1/symbols/search"
        params = {"prefix": query}
        resp = self.http.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        symbols = resp.json().get("symbols", [])
        return symbols

    def get_candles(self, symbol: str, start: datetime, end: datetime, interval: str = "OneDay") -> List[Dict[str, Any]]:
        # Paginated candles to respect Questrade limits (~20 per call)
        eastern = pytz.timezone("US/Eastern")
        candles: List[Dict[str, Any]] = []
        current_start = start

        while current_start < end:
            current_end = min(current_start + timedelta(days=20), end)

            url = f"{self.api_server}v1/markets/candles/{symbol}"
            params = {
                "startTime": eastern.localize(datetime.combine(current_start, datetime.min.time())).isoformat(),
                "endTime":   eastern.localize(datetime.combine(current_end,   datetime.min.time())).isoformat(),
                "interval":  interval,
            }

            resp = self.http.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            data = resp.json().get("candles", [])
            candles.extend(data)

            current_start = current_end

        return candles

    def place_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        # Placeholder: implement Questrade order endpoint as needed
        # Structure 'order' dict to include symbolId, side, qty, type, limitPrice, etc.
        raise NotImplementedError("Implement Questrade order placement as needed.")

    def get_positions(self) -> List[Dict[str, Any]]:
        # Placeholder: depends on Questrade accounts endpoint
        raise NotImplementedError("Implement Questrade positions endpoint.")

    def get_account_info(self) -> Dict[str, Any]:
        # Placeholder: depends on Questrade accounts endpoint
        raise NotImplementedError("Implement Questrade account info endpoint.")