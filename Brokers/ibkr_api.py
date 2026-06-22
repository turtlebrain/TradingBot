import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

SymbolRef = Union[str, int, Dict[str, Any]]

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


def _parse_ib_bar_time(raw: str) -> datetime:
    """Parse IBKR historical bar timestamps (daily or intraday)."""
    parts = raw.strip().split()
    if len(parts) == 1:
        return datetime.strptime(parts[0], "%Y%m%d")
    return datetime.strptime(f"{parts[0]} {parts[1]}", "%Y%m%d %H:%M:%S")


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


def _historical_chunk_days(interval: str) -> int:
    if interval == "OneMinute":
        return 30
    if interval == "OneHour":
        return 365
    return 10_000


def _historical_wait_timeout(interval: str, chunk_days: int) -> float:
    if interval == "OneMinute":
        return min(120.0, 20.0 + chunk_days * 3.0)
    if interval == "OneHour":
        return min(90.0, 20.0 + chunk_days * 0.5)
    return 30.0


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _iter_historical_chunks(start, end, interval: str):
    """Yield (chunk_start, chunk_end) date pairs for IBKR historical paging."""
    start_d = _as_date(start)
    end_d = _as_date(end)
    max_days = _historical_chunk_days(interval)
    total_days = max((end_d - start_d).days, 1)
    if total_days <= max_days:
        yield start_d, end_d
        return

    cur_end = end_d
    while cur_end >= start_d:
        cur_start = max(start_d, cur_end - timedelta(days=max_days - 1))
        yield cur_start, cur_end
        cur_end = cur_start - timedelta(days=1)


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
        # conId/contract lookups are stable for a session; cache by symbol
        # to avoid a reqContractDetails round-trip on every candle fetch.
        self._contract_cache: Dict[str, List[Dict[str, Any]]] = {}

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
        self._contract_cache.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"status": "session", "detail": "No token refresh required for TWS API."}

    def _contract_from_symbol(self, symbol: SymbolRef) -> Contract:
        """Build an IB Contract. IBKR requires exchange/secType even when conId is set."""
        contract = Contract()
        if isinstance(symbol, dict):
            con_id = symbol.get("conId") or symbol.get("symbolId")
            if con_id:
                contract.conId = int(con_id)
            contract.symbol = symbol.get("symbol", "")
            contract.secType = symbol.get("secType", "STK")
            contract.exchange = symbol.get("exchange", "SMART")
            contract.currency = symbol.get("currency", "USD")
            return contract

        if isinstance(symbol, int) or (isinstance(symbol, str) and str(symbol).isdigit()):
            contract.conId = int(symbol)
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            return contract

        contract.symbol = str(symbol)
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"
        return contract

    def _request_errors(self, req_id: int) -> List[Dict[str, Any]]:
        return [
            err for err in self.client.errors
            if err.get("reqId") == req_id
            and err.get("code") not in (2104, 2106, 2107, 2158)
        ]

    def get_symbols(self, query: str) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("IBKR session not connected.")

        cache_key = query.upper().strip()
        cached = self._contract_cache.get(cache_key)
        if cached:
            return cached

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

        results = self.client.symbol_search_results
        if results:
            self._contract_cache[cache_key] = results
        return results

    def get_candles(
        self,
        symbol: SymbolRef,
        start: datetime,
        end: datetime,
        interval: str = "OneDay",
    ) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("IBKR session not connected.")

        contract = self._contract_from_symbol(symbol)
        start_d = _as_date(start)
        end_d = _as_date(end)
        start_ts = datetime.combine(start_d, datetime.min.time())
        end_ts = datetime.combine(end_d, datetime.max.time())

        merged: Dict[str, Dict[str, Any]] = {}
        chunks = list(_iter_historical_chunks(start_d, end_d, interval))
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            if idx > 0:
                time.sleep(1.0)

            bar_size, duration_str = _map_timeframe(interval, chunk_start, chunk_end)
            end_time = chunk_end.strftime("%Y%m%d 23:59:59 US/Eastern")
            chunk_days = max((chunk_end - chunk_start).days, 1)
            timeout = _historical_wait_timeout(interval, chunk_days)

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
            if not self._wait(req_id, timeout=timeout):
                raise RuntimeError(f"Timed out fetching candles for {symbol}.")

            req_errors = self._request_errors(req_id)
            if req_errors and not self.client.historical_data:
                raise RuntimeError(req_errors[-1]["msg"])

            for bar in self.client.historical_data:
                merged[bar["date"]] = bar

        filtered: List[Dict[str, Any]] = []
        for bar in sorted(merged.values(), key=lambda b: _parse_ib_bar_time(b["date"])):
            bar_dt = _parse_ib_bar_time(bar["date"])
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
