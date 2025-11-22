from dataclasses import dataclass

@dataclass
class PositionRecord:
    symbol: str
    shares: int
    avg_price: float
    market_price: float
    market_value: float
    unrealized_pnl: float = 0.0
    side: str = ""   # "long", "short", or ""
    date: object = None  # timestamp of snapshot