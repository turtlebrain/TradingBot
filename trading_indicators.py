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
    Compute RSI using Wilder's smoothing.
    Returns a DataFrame with rsi.
    """
    price = data['close']
    lookback = int(params.get('lookback', 14))

    delta = price.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    # Wilder's smoothing
    avg_gain = pd.Series(gain).rolling(window=lookback, min_periods=lookback).mean()
    avg_loss = pd.Series(loss).rolling(window=lookback, min_periods=lookback).mean()

    # Recursive update for Wilder's method
    for i in range(lookback, len(price)):
        avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (lookback - 1) + gain[i]) / lookback
        avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (lookback - 1) + loss[i]) / lookback

    rs = avg_gain / avg_loss
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
