from dataclasses import dataclass

@dataclass
class PortfolioState:
    cash: float
    shares: int
    stop_loss: float = float("nan")
    prev_equity: float = 0.0
