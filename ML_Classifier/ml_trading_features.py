import pandas as pd
import numpy as np
import trading_indicators as indicators

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
    
    # Indicator features
    ind_feats = add_indicator_features(df, params)
    feats = pd.concat([feats, ind_feats], axis=1)
    
    # Rolling context
    if params.get("extra_candle_features", True):
        feats["ret_5m"] = df["close".pct_chage(5)]
        feats["vol_5m"] = df['close'].pct_change().rolling(5).std()
        feats["vol_15m"] = df['close'].pct_change().rolling(15).std()
        feats["mom_10m"] = df["close"].diff(10)
        
    # Final cleanup
    feats = feats.replace([np.inf, -np.inf], np.nan).dropna()
    return feats


def add_indicator_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Add ML-friendly indicator features, using existing columns if present
    else computing them via indicator helpers.
    """
    feats = pd.DataFrame(index=df.index)

    # --- RSI ---
    if params.get("use_rsi", True):
        if "rsi" in df.columns:
            feats["rsi"] = df["rsi"]
        else:
            rsi_df = indicators.compute_rsi_indicator(df, params.get("rsi_params", params))
            feats["rsi"] = rsi_df["rsi"]
        feats["rsi_overbought"] = (feats["rsi"] > 70).astype(int)
        feats["rsi_oversold"] = (feats["rsi"] < 30).astype(int)

    # --- DMA ---
    if params.get("use_dma", True):
        if {"dma_short", "dma_long"}.issubset(df.columns):
            feats["dma_short"] = df["dma_short"]
            feats["dma_long"] = df["dma_long"]
        else:
            dma_df = indicators.compute_dma_indicators(df, params.get("dma_params", params))
            feats["dma_short"] = dma_df["dma_short"]
            feats["dma_long"] = dma_df["dma_long"]
        feats["dma_cross_up"] = (feats["dma_short"] > feats["dma_long"]).astype(int)
        feats["dma_cross_down"] = (feats["dma_short"] < feats["dma_long"]).astype(int)
        feats["dma_short_slope"] = feats["dma_short"].diff()

    # --- EMA ---
    if params.get("use_ema_breakout", True):
        # Prefer ema_short/ema_long; if only a single 'ema' exists, still compute distance
        have_both = {"ema_short", "ema_long"}.issubset(df.columns)
        if have_both:
            feats["ema_short"] = df["ema_short"]
            feats["ema_long"] = df["ema_long"]
        else:
            ema_df = indicators.compute_ema_indicators(df, params.get("ema_params", params))
            feats["ema_short"] = ema_df["ema_short"]
            feats["ema_long"] = ema_df["ema_long"]

        # Distance of close to long EMA (stable baseline)
        feats["ema_dist"] = (df["close"] - feats["ema_long"]) / (feats["ema_long"] + 1e-9)
        feats["ema_breakout_up"] = (df["close"] > feats["ema_long"]).astype(int)
        feats["ema_breakout_down"] = (df["close"] < feats["ema_long"]).astype(int)

    # --- Support/Resistance ---
    if params.get("use_sr", True):
        have_sr = {"nearest_support", "nearest_resistance"}.issubset(df.columns)
        if have_sr:
            feats["nearest_support"] = df["nearest_support"]
            feats["nearest_resistance"] = df["nearest_resistance"]
        else:
            sr_df = indicators.compute_sr_indicator(df, params.get("sr_params", params))
            feats["nearest_support"] = sr_df["nearest_support"]
            feats["nearest_resistance"] = sr_df["nearest_resistance"]

        feats["dist_support"] = (df["close"] - feats["nearest_support"]) / (df["close"] + 1e-9)
        feats["dist_resistance"] = (feats["nearest_resistance"] - df["close"]) / (df["close"] + 1e-9)

    # Clean NaNs/infinities introduced by rolling and divisions
    feats = feats.replace([np.inf, -np.inf], np.nan)
    return feats