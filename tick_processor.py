import datetime
import pandas as pd
from collections import defaultdict

class CandleAggregator:
    def __init__(self, time_interval: str = "OneMinute"):
        self.time_interval = time_interval
        # Map time intervals to seconds
        interval_map = {
        "OneMinute": 60,
        "OneHour": 3600, 
        "OneDay": 86400,  
        }
        if time_interval not in interval_map:
            raise ValueError(f"Invalid time interval: {time_interval}. Must be one of {list(interval_map.keys())}")
    
        interval_seconds = interval_map[time_interval]
        self.interval = interval_seconds
        self.candles = defaultdict(dict)  # {timestamp: {open, high, low, close, volume}}
        self._subscribers = []   # list of callbacks
    
    def subscribe(self, callback):
        """Register a function to be called when a candle closes"""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def clear_subscribers(self):
        self._subscribers.clear()

    def _notify_subscribers(self, ts, candle_dict):
        """Internal: notify all subscribers with the new candle row"""
        candle_row = pd.Series(candle_dict, name=ts)
        for cb in self._subscribers:
            cb(candle_row)

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
            # If there was a previous candle, it just closed
            if self.candles:
                last_ts = max(self.candles.keys())
                if last_ts < ts:  # new interval started
                    self._notify_subscribers(last_ts, self.candles[last_ts])

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
