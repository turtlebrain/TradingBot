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

def compute_vwap_indicator(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute VWAP (Volume Weighted Average Price) from OHLCV data.
    Returns a DataFrame with vwap column.

    Expected columns in `data`:
        - 'close'
        - 'volume'
    """

    out = pd.DataFrame(index=data.index)

    # Cumulative price*volume and cumulative volume
    pv = (data['close'] * data['volume']).cumsum()
    v = data['volume'].cumsum()

    out['vwap'] = pv / v

    return out

def compute_orb_indicator(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Improved Opening Range Breakout (ORB) indicator.
    Returns orb_high, orb_low, orb_range, orb_breakout_up, orb_breakout_down.
    """

    ts_col = params.get("timestamp_col", "timestamp")
    orb_start = params.get("orb_start", "09:30")
    orb_end = params.get("orb_end", "09:45")

    # Bar times: column if present; else DatetimeIndex (_normalize_candles_to_df uses index only).
    if ts_col in data.columns:
        timestamps = pd.to_datetime(data[ts_col])
    elif isinstance(data.index, pd.DatetimeIndex):
        timestamps = pd.Series(pd.to_datetime(data.index), index=data.index)
    else:
        raise KeyError(
            f"ORB needs column {ts_col!r} or a DatetimeIndex; "
            f"columns={list(data.columns)}, index={type(data.index).__name__}"
        )
    dates = timestamps.dt.date
    times = timestamps.dt.time

    start_t = pd.to_datetime(orb_start).time()
    end_t = pd.to_datetime(orb_end).time()

    # ORB window mask
    orb_mask = (times >= start_t) & (times <= end_t)

    # Compute ORB high/low per day (robust: skip days with no ORB window)
    orb_high = data.loc[orb_mask].groupby(dates)["high"].max()
    orb_low = data.loc[orb_mask].groupby(dates)["low"].min()

    # Map back to full index
    orb_high_full = pd.Series(dates).map(orb_high)
    orb_low_full = pd.Series(dates).map(orb_low)

    out = pd.DataFrame(index=data.index)
    out["orb_high"] = orb_high_full
    out["orb_low"] = orb_low_full
    out["orb_range"] = out["orb_high"] - out["orb_low"]

    # Breakout signals (only valid AFTER ORB window)
    close = data["close"]
    after_orb = times > end_t

    out["orb_breakout_up"] = ((close > out["orb_high"]) & after_orb).astype(int)
    out["orb_breakout_down"] = ((close < out["orb_low"]) & after_orb).astype(int)

    return out