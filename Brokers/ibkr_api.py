from typing import Any, Dict, List, Optional
from datetime import datetime
import time

from broker_interface import BrokerInterface

# IB API imports
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

class _IBClient(EWrapper, EClient):
    """Thin wrapper combining IBKR EWrapper and EClient."""
    def __init__(self):
        EClient.__init__(self, self)
        # Internal buffers for responses
        self.symbol_search_results: List[Dict[str, Any]] = []
        self.historical_data: List[Dict[str, Any]] = []
        self.order_statuses: List[Dict[str, Any]] = []
        self.positions: List[Dict[str, Any]] = []
        self.account_values: Dict[str, Any] = {}
        self.errors: List[Dict[str, Any]] = []

    # Error handling
    def error(self, reqId, errorCode, errorString):
        self.errors.append({"reqId": reqId, "code": errorCode, "msg": errorString})

    # Contract search callback
    def contractDetails(self, reqId, contractDetails):
        cd = contractDetails
        self.symbol_search_results.append({
            "symbol": cd.contract.symbol,
            "secType": cd.contract.secType,
            "exchange": cd.contract.exchange,
            "currency": cd.contract.currency,
            "conId": cd.contract.conId,
        })

    def contractDetailsEnd(self, reqId):
        pass  # Signal completion if you add a condition variable

    # Historical data callbacks
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
        pass  # Signal completion if you add a condition variable

    # Order status callbacks
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId,
                    parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        self.order_statuses.append({
            "orderId": orderId,
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
        })

    # Positions callbacks
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
        pass

    # Account values callback
    def updateAccountValue(self, key, val, currency, accountName):
        self.account_values[key] = {"value": val, "currency": currency}

class IBKRBroker(BrokerInterface):
    """Concrete broker for IBKR using TWS/IB Gateway via ibapi."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        # Connection parameters for TWS/IB Gateway
        self.host = host
        self.port = port  # 7497 for paper; 7496 for live by default
        self.client_id = client_id

        # Internal client instance (event-driven)
        self.client = _IBClient()
        self.connected = False

    def authenticate(self) -> Dict[str, Any]:
        # Connect to the running TWS/IB Gateway session
        self.client.connect(self.host, self.port, self.client_id)
        self.connected = True

        # Start network thread to process messages
        thread = self.client.run  # The run() blocks; usually start in a thread
        # In production, use threading.Thread(target=self.client.run, daemon=True).start()
        # For simplicity here, we won’t start the thread inline.

        return {"status": "connected", "host": self.host, "port": self.port, "client_id": self.client_id}

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        # IBKR TWS API uses a session; no OAuth refresh token needed
        return {"status": "session", "detail": "No token refresh required for TWS API."}

    def get_symbols(self, query: str) -> List[Dict[str, Any]]:
        # Build a generic stock contract for search
        base = Contract()
        base.symbol = query
        base.secType = "STK"
        base.currency = "USD"
        base.exchange = "SMART"

        req_id = 1001
        self.client.reqContractDetails(req_id, base)
        time.sleep(1.0)  # In production, wait on a condition/event

        return self.client.symbol_search_results

    def get_candles(self, symbol: str, start: datetime, end: datetime, interval: str = "1 day") -> List[Dict[str, Any]]:
        # Build a contract for historical data
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"

        # IBKR expects end time and duration strings
        endTime = end.strftime("%Y%m%d %H:%M:%S")
        durationStr = "30 D"  # Adjust based on (end - start)
        barSizeSetting = "1 day" if interval == "1 day" else "1 min"
        whatToShow = "TRADES"
        useRTH = 1  # Regular Trading Hours

        req_id = 2001
        self.client.reqHistoricalData(
            req_id, contract, endTime, durationStr, barSizeSetting, whatToShow, useRTH, 1, False, []
        )
        time.sleep(2.0)  # In production, wait on a condition/event

        return self.client.historical_data

    def place_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        # Convert dict to IB Order + Contract
        contract = Contract()
        contract.symbol = order["symbol"]
        contract.secType = order.get("secType", "STK")
        contract.currency = order.get("currency", "USD")
        contract.exchange = order.get("exchange", "SMART")

        ib_order = Order()
        ib_order.action = order["side"]        # "BUY" or "SELL"
        ib_order.totalQuantity = order["qty"]  # integer
        ib_order.orderType = order["type"]     # "MKT" or "LMT"
        if ib_order.orderType == "LMT":
            ib_order.lmtPrice = order["limitPrice"]

        order_id = self.client.getReqId() if hasattr(self.client, "getReqId") else 1
        self.client.placeOrder(order_id, contract, ib_order)

        time.sleep(1.0)  # In production, wait on orderStatus events
        statuses = [s for s in self.client.order_statuses if s["orderId"] == order_id]
        return {"orderId": order_id, "statuses": statuses}

    def get_positions(self) -> List[Dict[str, Any]]:
        self.client.positions.clear()
        self.client.reqPositions()
        time.sleep(1.0)  # Wait for callbacks
        return self.client.positions

    def get_account_info(self) -> Dict[str, Any]:
        # Request account updates (once subscribed, callbacks will fill account_values)
        self.client.account_values = {}
        self.client.reqAccountSummary(9001, "All", "NetLiquidation,TotalCashValue,BuyingPower,UnrealizedPnL,RealizedPnL")
        time.sleep(1.0)
        self.client.cancelAccountSummary(9001)
        return self.client.account_values