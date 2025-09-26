import datetime
import pandas as pd
from collections import defaultdict

class CandleAggregator:
    def __init__(self, interval_seconds=60):
        self.interval = interval_seconds
        self.candles = defaultdict(dict)  # {timestamp: {open, high, low, close, volume}}

    def _floor_time(self, dt: datetime.datetime) -> datetime.datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)  # force UTC if naive
        seconds = (dt - dt.replace(hour=0, minute=0, second=0, microsecond=0)).seconds
        rounding = seconds // self.interval * self.interval
        return dt.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(seconds=rounding)

    def update(self, tick: dict):
        """
        Update candles with a new tick.
        tick = {"price": float, "volume": int, "timestamp": datetime}
        """
        ts = self._floor_time(tick["timestamp"])
        c = self.candles.get(ts)

        if not c:
            # start a new candle
            self.candles[ts] = {
                "open": tick["price"],
                "high": tick["price"],
                "low": tick["price"],
                "close": tick["price"],
                "volume": tick["volume"]
            }
        else:
            c["high"] = max(c["high"], tick["price"])
            c["low"] = min(c["low"], tick["price"])
            c["close"] = tick["price"]
            c["volume"] += tick["volume"]

    def get_candles(self):
        """Return candles as a properly formatted pandas DataFrame."""
        if not self.candles:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        df = pd.DataFrame.from_dict(self.candles, orient="index")
        # Ensure datetime index
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        # Sort by time
        df = df.sort_index()
        return df
