import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Brokers.broker_interface import BrokerInterface

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

PAPER_PORTS = {7497, 4002}
LIVE_PORTS = {7496, 4001}
FATAL_CONNECTION_CODES = {326, 501, 502, 503, 504, 1100, 1101, 1102}
CLIENT_ID_COLLISION_CODE = 326
MAX_CLIENT_ID_ATTEMPTS = 5


def _load_ibkr_env() -> Dict[str, Any]:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)

    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))
    client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
    account = os.getenv("IBKR_ACCOUNT", "").strip()
    trading_mode = os.getenv("IBKR_TRADING_MODE", "paper").strip().lower()
    return {
        "host": host,
        "port": port,
        "client_id": client_id,
        "account": account,
        "trading_mode": trading_mode,
    }


def _map_timeframe(interval: str, start: datetime, end: datetime) -> Tuple[str, str]:
    """Map app timeframe strings to IBKR barSizeSetting and durationStr."""
    days = max((end - start).days, 1)
    if interval == "OneMinute":
        bar_size = "1 min"
        duration = f"{min(days, 30)} D"
    elif interval == "OneHour":
        bar_size = "1 hour"
        duration = f"{min(days, 365)} D"
    elif interval == "OneWeek":
        bar_size = "1 week"
        weeks = max(days // 7 + 1, 52)
        duration = f"{min(weeks, 104)} W"
    else:
        bar_size = "1 day"
        duration = f"{max(days, 30)} D" if days < 365 else f"{days // 365 + 1} Y"
    return bar_size, duration


class _IBClient(EWrapper, EClient):
    """Thin wrapper combining IBKR EWrapper and EClient."""

    def __init__(self):
        EClient.__init__(self, self)
        self.symbol_search_results: List[Dict[str, Any]] = []
        self.historical_data: List[Dict[str, Any]] = []
        self.order_statuses: List[Dict[str, Any]] = []
        self.positions: List[Dict[str, Any]] = []
        self.account_values: Dict[str, Any] = {}
        self.errors: List[Dict[str, Any]] = []
        self.connected_event = threading.Event()
        self.next_order_id: Optional[int] = None
        self._pending: Dict[int, threading.Event] = {}
        self._fatal_error: Optional[str] = None

    def _signal(self, req_id: int):
        event = self._pending.get(req_id)
        if event:
            event.set()

    def nextValidId(self, orderId: int):
        self.next_order_id = orderId
        self.connected_event.set()

    def error(self, reqId, errorCode, errorString):
        self.errors.append({"reqId": reqId, "code": errorCode, "msg": errorString})
        # 2104/2106/2107/2158 are informational farm status messages.
        if errorCode in FATAL_CONNECTION_CODES:
            self._fatal_error = errorString
            self.connected_event.set()
        if reqId in self._pending and errorCode not in (2104, 2106, 2107, 2158):
            self._signal(reqId)

    def contractDetails(self, reqId, contractDetails):
        contract = contractDetails.contract
        self.symbol_search_results.append({
            "symbol": contract.symbol,
            "symbolId": contract.conId,
            "conId": contract.conId,
            "secType": contract.secType,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "description": contractDetails.longName or contract.symbol,
        })

    def contractDetailsEnd(self, reqId):
        self._signal(reqId)

    def historicalData(self, reqId, bar):
        self.historical_data.append({
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })

    def historicalDataEnd(self, reqId, start, end):
        self._signal(reqId)

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId,
                    parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        self.order_statuses.append({
            "orderId": orderId,
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
        })

    def position(self, account, contract, position, avgCost):
        self.positions.append({
            "account": account,
            "symbol": contract.symbol,
            "secType": contract.secType,
            "conId": contract.conId,
            "position": position,
            "avgCost": avgCost,
        })

    def positionEnd(self):
        self._signal(0)

    def updateAccountValue(self, key, val, currency, accountName):
        self.account_values[key] = {"value": val, "currency": currency}

    def accountSummary(self, reqId, account, tag, value, currency):
        self.account_values[tag] = {"value": value, "currency": currency}

    def accountSummaryEnd(self, reqId):
        self._signal(reqId)


class IBKRBroker(BrokerInterface):
    """Concrete broker for IBKR using TWS/IB Gateway via ibapi."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
        account: Optional[str] = None,
        trading_mode: Optional[str] = None,
    ):
        cfg = _load_ibkr_env()
        self.host = host or cfg["host"]
        self.port = port if port is not None else cfg["port"]
        self.client_id = client_id if client_id is not None else cfg["client_id"]
        self.account = account or cfg["account"]
        self.trading_mode = (trading_mode or cfg["trading_mode"]).lower()

        if self.trading_mode == "paper" and self.port not in PAPER_PORTS:
            raise RuntimeError(
                f"IBKR_TRADING_MODE=paper but IBKR_PORT={self.port}. "
                f"Use a paper port ({sorted(PAPER_PORTS)})."
            )
        if self.trading_mode == "live" and self.port not in LIVE_PORTS:
            raise RuntimeError(
                f"IBKR_TRADING_MODE=live but IBKR_PORT={self.port}. "
                f"Use a live port ({sorted(LIVE_PORTS)})."
            )

        self.client = _IBClient()
        self.connected = False
        self._thread: Optional[threading.Thread] = None
        self._req_id = 1000

    def _next_req_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _wait(self, req_id: int, timeout: float = 15.0) -> bool:
        event = threading.Event()
        self.client._pending[req_id] = event
        finished = event.wait(timeout)
        self.client._pending.pop(req_id, None)
        return finished

    def authenticate(self) -> Dict[str, Any]:
        if self.connected:
            return {
                "status": "connected",
                "host": self.host,
                "port": self.port,
                "client_id": self.client_id,
            }

        base_client_id = self.client_id
        last_error: Optional[str] = None

        for attempt in range(MAX_CLIENT_ID_ATTEMPTS):
            candidate_id = base_client_id + attempt
            result = self._try_connect(candidate_id)
            if result is not None:
                self.client_id = candidate_id
                self.connected = True
                return result

            last_error = self.client._fatal_error
            if self._last_collision_code() != CLIENT_ID_COLLISION_CODE:
                break

        self.disconnect()
        if last_error and "client id" in last_error.lower():
            raise RuntimeError(
                f"{last_error} Tried client IDs {base_client_id}"
                f"-{base_client_id + MAX_CLIENT_ID_ATTEMPTS - 1}. "
                "Close other API apps, restart IB Gateway, or set IBKR_CLIENT_ID "
                "to a free value."
            )
        raise RuntimeError(
            last_error or (
                f"Timed out waiting for IB Gateway at {self.host}:{self.port}. "
                "Check API settings (socket port, trusted IPs, socket clients enabled)."
            )
        )

    def _last_collision_code(self) -> Optional[int]:
        for err in reversed(self.client.errors):
            if err.get("code") == CLIENT_ID_COLLISION_CODE:
                return CLIENT_ID_COLLISION_CODE
        return None

    def _try_connect(self, client_id: int) -> Optional[Dict[str, Any]]:
        """Attempt one socket session. Returns auth dict on success, None on client-id collision."""
        self.disconnect()
        self.client = _IBClient()
        self.client.connected_event.clear()
        self.client._fatal_error = None

        self.client.connect(self.host, self.port, client_id)

        if not self.client.isConnected():
            raise RuntimeError(
                f"Unable to connect to IB Gateway at {self.host}:{self.port}. "
                "Is Gateway running with socket clients enabled?"
            )

        self._thread = threading.Thread(target=self.client.run, daemon=True)
        self._thread.start()

        if not self.client.connected_event.wait(timeout=15.0):
            self.disconnect()
            raise RuntimeError(
                f"Timed out waiting for IB Gateway at {self.host}:{self.port}. "
                "Check API settings (socket port, trusted IPs, socket clients enabled)."
            )

        if self.client._fatal_error:
            if self._last_collision_code() == CLIENT_ID_COLLISION_CODE:
                self.disconnect()
                return None
            raise RuntimeError(self.client._fatal_error)

        return {
            "status": "connected",
            "host": self.host,
            "port": self.port,
            "client_id": client_id,
        }

    def disconnect(self) -> None:
        if self.client.isConnected():
            self.client.disconnect()
        self.connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"status": "session", "detail": "No token refresh required for TWS API."}

    def _contract_from_symbol(self, symbol: Any) -> Contract:
        contract = Contract()
        if isinstance(symbol, int) or (isinstance(symbol, str) and str(symbol).isdigit()):
            contract.conId = int(symbol)
        else:
            contract.symbol = str(symbol)
            contract.secType = "STK"
            contract.currency = "USD"
            contract.exchange = "SMART"
        return contract

    def get_symbols(self, query: str) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("IBKR session not connected.")

        base = Contract()
        base.symbol = query
        base.secType = "STK"
        base.currency = "USD"
        base.exchange = "SMART"

        req_id = self._next_req_id()
        self.client.symbol_search_results = []
        self.client.reqContractDetails(req_id, base)
        if not self._wait(req_id, timeout=10.0):
            raise RuntimeError(f"Timed out searching symbols for '{query}'.")

        return self.client.symbol_search_results

    def get_candles(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "OneDay",
    ) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("IBKR session not connected.")

        contract = self._contract_from_symbol(symbol)
        bar_size, duration_str = _map_timeframe(interval, start, end)
        end_time = end.strftime("%Y%m%d 23:59:59 US/Eastern")

        req_id = self._next_req_id()
        self.client.historical_data = []
        self.client.reqHistoricalData(
            req_id,
            contract,
            end_time,
            duration_str,
            bar_size,
            "TRADES",
            1,
            1,
            False,
            [],
        )
        if not self._wait(req_id, timeout=30.0):
            raise RuntimeError(f"Timed out fetching candles for {symbol}.")

        start_ts = datetime.combine(start, datetime.min.time())
        end_ts = datetime.combine(end, datetime.max.time())
        filtered: List[Dict[str, Any]] = []
        for bar in self.client.historical_data:
            raw = bar["date"]
            if " " in raw:
                bar_dt = datetime.strptime(raw.split(" ")[0] + " " + raw.split(" ")[1], "%Y%m%d %H:%M:%S")
            else:
                bar_dt = datetime.strptime(raw, "%Y%m%d")
            if start_ts <= bar_dt <= end_ts:
                filtered.append(bar)
        return filtered

    def place_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        contract = Contract()
        contract.symbol = order["symbol"]
        contract.secType = order.get("secType", "STK")
        contract.currency = order.get("currency", "USD")
        contract.exchange = order.get("exchange", "SMART")

        ib_order = Order()
        ib_order.action = order["side"]
        ib_order.totalQuantity = order["qty"]
        ib_order.orderType = order["type"]
        if ib_order.orderType == "LMT":
            ib_order.lmtPrice = order["limitPrice"]
        if self.account:
            ib_order.account = self.account

        order_id = self.client.next_order_id or self._next_req_id()
        if self.client.next_order_id:
            self.client.next_order_id += 1
        self.client.placeOrder(order_id, contract, ib_order)

        time.sleep(1.0)
        statuses = [s for s in self.client.order_statuses if s["orderId"] == order_id]
        return {"orderId": order_id, "statuses": statuses}

    def get_positions(self) -> List[Dict[str, Any]]:
        self.client.positions.clear()
        self.client._pending[0] = threading.Event()
        self.client.reqPositions()
        self._wait(0, timeout=10.0)
        self.client._pending.pop(0, None)
        return self.client.positions

    def get_account_info(self) -> Dict[str, Any]:
        self.client.account_values = {}
        req_id = self._next_req_id()
        self.client.reqAccountSummary(req_id, "All", "NetLiquidation,TotalCashValue,BuyingPower,UnrealizedPnL,RealizedPnL")
        self._wait(req_id, timeout=10.0)
        self.client.cancelAccountSummary(req_id)
        return self.client.account_values
