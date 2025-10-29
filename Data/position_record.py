from dataclasses import dataclass
import math

@dataclass
class PositionRecord:
    symbol: str
    shares: int
    avg_price: float
    market_price: float
    market_value: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    side: str = ""   # "long", "short", or ""
    date: object = None  # timestamp of snapshot
