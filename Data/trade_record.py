from dataclasses import dataclass

@dataclass
class TradeRecord:
    price: float
    signal: int
    shares: int
    cash: float
    equity: float
    market_value: float
    order: int                  # actual filled qty (positive buy, negative sell, 0 none)
    exec_price: float = float("nan")
    stop_loss: float = float("nan")
    fees: float = 0.0
    trade_side: str = ""        # "buy"/"sell" or ""
    pnl: float = 0.0