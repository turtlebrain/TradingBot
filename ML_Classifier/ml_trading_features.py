import pandas as pd
import numpy as np
import trading_indicators as indicators

def build_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Feature builder with:
    - Leakage-safe alignment (shifted features)
    - ATR-normalized candle microstructure
    - Log-return volatility context
    - Robust EWM volume z-score
    - Optional intraday cyclical time features
    """
    EPS = 1e-8
    feats = pd.DataFrame(index=df.index)

    # Core returns and ranges
    feats["ret_1m_log"] = np.log(df["close"]).diff()  # additive, stable vs pct_change
    feats["hl_range_pct"] = (df["high"] - df["low"]) / (df["close"].shift(1) + EPS)

    # True range and ATR normalization (robust size scaling)
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr_w = int(params.get("atr_window", 14))
    atr = tr.rolling(atr_w, min_periods=atr_w).mean()

    # Candle microstructure (absolute and ATR-normalized)
    body_abs = (df["close"] - df["open"]).abs()
    feats["body_abs"] = body_abs
    feats["body_atr"] = body_abs / (atr + EPS)

    upper_anchor = df[["open", "close"]].max(axis=1)
    lower_anchor = df[["open", "close"]].min(axis=1)
    upper_wick = (df["high"] - upper_anchor).clip(lower=0)
    lower_wick = (lower_anchor - df["low"]).clip(lower=0)

    feats["upper_wick_ratio"] = upper_wick / (body_abs + EPS)
    feats["lower_wick_ratio"] = lower_wick / (body_abs + EPS)
    feats["upper_wick_atr"]   = upper_wick / (atr + EPS)
    feats["lower_wick_atr"]   = lower_wick / (atr + EPS)

    # Volume context (robust EWM z-score)
    span = int(params.get("vol_span", 60))
    vol_mean = df["volume"].ewm(span=span, min_periods=10, adjust=False).mean()
    vol_std  = df["volume"].ewm(span=span, min_periods=10, adjust=False).std()
    feats["volume_z"] = ((df["volume"] - vol_mean) / (vol_std + EPS)).clip(-5, 5)

    # Indicator features passthrough
    ind_feats = add_indicator_features(df, params)
    feats = pd.concat([feats, ind_feats], axis=1)

    # Rolling context (log-volatility and ATR-normalized momentum)
    if params.get("extra_candle_features", True):
        feats["ret_5m_log"]   = np.log(df["close"]).diff(5)
        logret_1m            = np.log(df["close"]).diff()
        feats["vol_5m_log"]  = logret_1m.rolling(5).std()
        feats["vol_15m_log"] = logret_1m.rolling(15).std()
        feats["mom_10m_atr"] = (df["close"] - df["close"].shift(10)) / (atr + EPS)

        # Volatility regime percentile (min-max proxy, leak-safe)
        win = int(params.get("regime_window", 240))
        v = feats["vol_15m_log"]
        v_min = v.rolling(win, min_periods=win).min()
        v_max = v.rolling(win, min_periods=win).max()
        feats["vol_regime_pct"] = ((v - v_min) / (v_max - v_min + EPS)).clip(0, 1)

    # Optional intraday cyclical time features (for equities; default 390 minutes)
    if params.get("add_time_cycles", False):
        session_minutes = int(params.get("session_minutes", 390))
        minute_of_day = df.index.hour * 60 + df.index.minute
        angle = 2 * np.pi * (minute_of_day % session_minutes) / max(session_minutes, 1)
        feats["tod_sin"] = np.sin(angle)
        feats["tod_cos"] = np.cos(angle)

    # Leakage-safe alignment: use only completed candle info for next decision
    feats = feats.shift(1)

    # Cleanup
    feats = feats.replace([np.inf, -np.inf], np.nan).dropna()
    return feats


def add_indicator_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Add ML-friendly indicator features based on selected indicators
    from StrategySection. Uses existing columns if present,
    else computes them via indicator helpers.
    """
    feats = pd.DataFrame(index=df.index)

    # Get selected indicators (list of dicts from StrategySection.serialize())
    selected = params.get("indicators", [])

    for ind in selected:
        name = ind.get("name")
        iparams = ind.get("params", {})

        # --- RSI ---
        if name == "RSI":
            if "rsi" in df.columns:
                feats["rsi"] = df["rsi"]
            else:
                rsi_df = indicators.compute_rsi_indicator(df, iparams)
                feats["rsi"] = rsi_df["rsi"]
            feats["rsi_overbought"] = (feats["rsi"] > 70).astype(int)
            feats["rsi_oversold"] = (feats["rsi"] < 30).astype(int)

        # --- DMA ---
        elif name == "DMA Crossing":
            if {"dma_short", "dma_long"}.issubset(df.columns):
                feats["dma_short"] = df["dma_short"]
                feats["dma_long"] = df["dma_long"]
            else:
                dma_df = indicators.compute_dma_indicators(df, iparams)
                feats["dma_short"] = dma_df["dma_short"]
                feats["dma_long"] = dma_df["dma_long"]
            feats["dma_cross_up"] = (feats["dma_short"] > feats["dma_long"]).astype(int)
            feats["dma_cross_down"] = (feats["dma_short"] < feats["dma_long"]).astype(int)
            feats["dma_short_slope"] = feats["dma_short"].diff()

        # --- EMA ---
        elif name == "EMA Breakout":
            have_both = {"ema_short", "ema_long"}.issubset(df.columns)
            if have_both:
                feats["ema_short"] = df["ema_short"]
                feats["ema_long"] = df["ema_long"]
            else:
                ema_df = indicators.compute_ema_indicators(df, iparams)
                feats["ema_short"] = ema_df["ema_short"]
                feats["ema_long"] = ema_df["ema_long"]

            feats["ema_dist"] = (df["close"] - feats["ema_long"]) / (feats["ema_long"] + 1e-9)
            feats["ema_breakout_up"] = (df["close"] > feats["ema_long"]).astype(int)
            feats["ema_breakout_down"] = (df["close"] < feats["ema_long"]).astype(int)

        # --- Support/Resistance ---
        elif name == "S/R Structure":
            have_sr = {"nearest_support", "nearest_resistance"}.issubset(df.columns)
            if have_sr:
                feats["nearest_support"] = df["nearest_support"]
                feats["nearest_resistance"] = df["nearest_resistance"]
            else:
                sr_df = indicators.compute_sr_indicator(df, iparams)
                feats["nearest_support"] = sr_df["nearest_support"]
                feats["nearest_resistance"] = sr_df["nearest_resistance"]

            feats["dist_support"] = (df["close"] - feats["nearest_support"]) / (df["close"] + 1e-9)
            feats["dist_resistance"] = (feats["nearest_resistance"] - df["close"]) / (df["close"] + 1e-9)

    # Clean NaNs/infinities introduced by rolling and divisions
    feats = feats.replace([np.inf, -np.inf], np.nan)
    return feats