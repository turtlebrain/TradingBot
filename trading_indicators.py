import pandas as pd
import numpy as np
from scipy.signal import find_peaks


def compute_dma_indicators(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute short/long simple moving averages (DMA) needed for features.
    Returns a DataFrame with dma_short and dma_long.
    """
    short_window = int(params.get('short_window', 20))
    long_window = int(params.get('long_window', 50))

    out = pd.DataFrame(index=data.index)
    out['dma_short'] = data['close'].rolling(window=short_window, min_periods=short_window).mean()
    out['dma_long'] = data['close'].rolling(window=long_window, min_periods=long_window).mean()
    return out

def compute_ema_indicators(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute short/long EMAs for features.
    Returns a DataFrame with ema_short and ema_long.
    """
    short_window = int(params.get('short_window', 12))
    long_window = int(params.get('long_window', 26))

    out = pd.DataFrame(index=data.index)
    out['ema_short'] = data['close'].ewm(span=short_window, adjust=False).mean()
    out['ema_long'] = data['close'].ewm(span=long_window, adjust=False).mean()
    return out

def compute_rsi_indicator(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute RSI using Wilder's smoothing (fully vectorized via EWM).
    alpha = 1/lookback is mathematically equivalent to Wilder's recursive formula.
    Returns a DataFrame with rsi.
    """
    price = data['close']
    lookback = int(params.get('lookback', 14))

    delta = price.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's smoothing: ewm with alpha=1/lookback, no Python loop required
    avg_gain = gain.ewm(alpha=1.0 / lookback, adjust=False, min_periods=lookback).mean()
    avg_loss = loss.ewm(alpha=1.0 / lookback, adjust=False, min_periods=lookback).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    out = pd.DataFrame(index=data.index)
    out['rsi'] = rsi
    return out

def compute_sr_indicator(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Detect recent support/resistance levels and provide nearest levels per bar.
    Returns nearest_support and nearest_resistance.
    """
    distance = int(params.get('distance', 20))

    highs = data['high']
    lows = data['low']

    # Peaks in highs = resistance, peaks in -lows = support
    res_idx, _ = find_peaks(highs, distance=distance)
    sup_idx, _ = find_peaks(-lows, distance=distance)

    # Build level series (NaN where not a level)
    res_levels = pd.Series(np.nan, index=data.index)
    sup_levels = pd.Series(np.nan, index=data.index)
    res_levels.iloc[res_idx] = highs.iloc[res_idx].values
    sup_levels.iloc[sup_idx] = lows.iloc[sup_idx].values

    # Forward-fill nearest levels so every bar has a reference
    nearest_resistance = res_levels.ffill()
    nearest_support = sup_levels.ffill()

    out = pd.DataFrame(index=data.index)
    out['nearest_support'] = nearest_support
    out['nearest_resistance'] = nearest_resistance
    return out

def _typical_price(data: pd.DataFrame) -> pd.Series:
    """Bar typical price for VWAP; falls back to close when OHLC incomplete."""
    required = ("high", "low", "close")
    if all(col in data.columns for col in required):
        return (data["high"] + data["low"] + data["close"]) / 3.0
    return data["close"].astype(float)


def _us_session_keys(index: pd.DatetimeIndex, tz: str = "America/New_York") -> pd.Series:
    """Calendar session key per bar in ``tz`` (midnight-normalized local dates)."""
    if index.tz is None:
        idx_local = index.tz_localize("UTC").tz_convert(tz)
    else:
        idx_local = index.tz_convert(tz)
    return pd.Series(idx_local.normalize(), index=index)


def compute_vwap_indicator(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute session-anchored VWAP from OHLCV data.

    VWAP resets at the start of each US equity session day (calendar date in
    ``tz``, default America/New_York). This matches how VWAP is used
    intraday; the previous implementation cumulated across the entire fetched
    range, which breaks multi-day minute/hour series.

    Params
    ------
    tz : str
        Timezone for session boundaries (default ``America/New_York``).
    session_anchor : bool
        When True (default), reset cumulative VWAP each session day. When
        False, use legacy whole-series cumulative VWAP.

    Expected columns: ``close``, ``volume``; ``high``/``low`` optional for
    typical price ``(H+L+C)/3``.
    """
    out = pd.DataFrame(index=data.index)
    if data is None or data.empty:
        out["vwap"] = pd.Series(dtype=float, index=data.index)
        return out

    if "volume" not in data.columns:
        out["vwap"] = np.nan
        return out

    tz = str(params.get("tz", "America/New_York"))
    session_anchor = bool(params.get("session_anchor", True))

    typical = _typical_price(data)
    volume = data["volume"].astype(float).clip(lower=0)
    pv = typical * volume

    if session_anchor and isinstance(data.index, pd.DatetimeIndex):
        session_key = _us_session_keys(data.index, tz=tz)
        cum_pv = pv.groupby(session_key, sort=False).cumsum()
        cum_vol = volume.groupby(session_key, sort=False).cumsum()
    else:
        cum_pv = pv.cumsum()
        cum_vol = volume.cumsum()

    out["vwap"] = cum_pv / cum_vol.replace(0, np.nan)
    return out
