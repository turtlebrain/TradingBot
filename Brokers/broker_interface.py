from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime

class BrokerInterface(ABC):
    """Defines the contract every broker must implement."""

    @abstractmethod
    def authenticate(self) -> Dict[str, Any]:
        """Start authentication (OAuth or session)."""
        pass

    def complete_auth(self, code: str) -> Dict[str, Any]:
        """Finish OAuth if applicable. Optional for non-OAuth brokers."""
        raise NotImplementedError("This broker does not require a code to complete auth.")

    @abstractmethod
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access tokens or renew session."""
        pass

    @abstractmethod
    def get_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search symbols/contracts by prefix or name."""
        pass

    @abstractmethod
    def get_candles(self, symbol: str, start: datetime, end: datetime, interval: str) -> List[Dict[str, Any]]:
        """Fetch historical candles for a symbol."""
        pass

    @abstractmethod
    def place_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an order and return a structured result."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Return current positions."""
        pass

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """Return balances, P&L, buying power, etc."""
        pass