import pandas as pd
import numpy as np

def build_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Constructs a feature matrix using OHLCV data and indicators.
    df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
    params: dictionary controlling which features to include
    Returns: DataFrame with engineered features.
    """
    feats = pd.DataFrame(index=df.index)
    # 1-minute return: how much the price changed in the last minute
    feats["ret_1m"] = df["close"].pct_change()
    # High-low range relative to previous close: measures volatility in 1-minute
    feats["hl_range"] = (df["high"] - df["low"]) / df["close"].shift(1)
    # Candle body size: absolute difference between open and close
    feats["body"] = (df["close"] - df["open"]).abs()
    # Upper wick: distance rom higher of open/close to the high
    feats["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)).clip(lower=0)
    # Lower wick: distance from lower of open/close to the low
    feats["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]).clip(lower=0)
    # Ratios: wick size relative to body size (helps detect doji candles, long wicks, etc.)
    feats["upper_wick_ratio"] = feats["upper_wick"] / (feats["body"] + 1e-9)
    feats["lower_wick_ratio"] = feats["lower_wick"] / (feats["body"] + 1e-9)
    # Volume z-score: how unusual is the volume compared to the last 60 minutes
    feats["volume_z"] = (df["volume"]- df["volume"].rolling(60).mean()) / (df["volume"].rolling(60).std() + 1e-9)
    
    return feats