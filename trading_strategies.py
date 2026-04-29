import trading_indicators as indicators
import pandas as pd
import numpy as np

def double_moving_average_crossover(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Double Moving Average (DMA) Crossover strategy.
    Uses compute_dma_indicators for moving averages, then applies crossover logic.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']

    # Get DMA columns
    dma_df = indicators.compute_dma_indicators(data, params)
    signals['dma_short'] = dma_df['dma_short']
    signals['dma_long'] = dma_df['dma_long']

    # Generate raw signal: 1 for bullish, -1 for bearish, 0 otherwise
    signals['raw_signal'] = np.where(
        signals['dma_short'] > signals['dma_long'], 1,
        np.where(signals['dma_short'] < signals['dma_long'], -1, 0)
    )

    # Detect crossover events (change in raw_signal)
    signals['signal'] = signals['raw_signal'].diff().fillna(0)
    signals['positions'] = signals['signal'].cumsum()

    return signals

def exponential_moving_average_breakout(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    EMA Breakout strategy.
    Uses compute_ema_indicators for EMAs, then applies breakout logic.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']

    ema_df = indicators.compute_ema_indicators(data, params)
    signals['ema_short'] = ema_df['ema_short']
    signals['ema_long'] = ema_df['ema_long']

    signals['raw_signal'] = np.where(
        signals['ema_short'] > signals['ema_long'], 1,
        np.where(signals['ema_short'] < signals['ema_long'], -1, 0)
    )

    signals['signal'] = signals['raw_signal'].diff().fillna(0)
    signals['positions'] = signals['signal'].cumsum()

    return signals

def relative_strength_index(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    RSI-based strategy.
    Uses compute_rsi_indicator for RSI values, then applies overbought/oversold logic.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']

    rsi_df = indicators.compute_rsi_indicator(data, params)
    signals['rsi'] = rsi_df['rsi']

    overbought = float(params.get('overbought', 70))
    oversold = float(params.get('oversold', 30))

    signals['signal'] = 0
    signals.loc[(signals['rsi'] > oversold) & (signals['rsi'].shift(1) <= oversold), 'signal'] = 1
    signals.loc[(signals['rsi'] < overbought) & (signals['rsi'].shift(1) >= overbought), 'signal'] = -1

    signals['positions'] = signals['signal'].cumsum()

    return signals

def support_resistance_structure(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Support/Resistance strategy with heuristic breakout check.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']

    sr_df = indicators.compute_sr_indicator(data, params)
    signals['nearest_support'] = sr_df['nearest_support']
    signals['nearest_resistance'] = sr_df['nearest_resistance']

    # Initialize all signals as hold (0)
    signals['signal'] = 0

    # Long if bouncing off support
    signals.loc[signals['price'] <= signals['nearest_support'], 'signal'] = 1

    # Short if rejecting resistance
    signals.loc[signals['price'] >= signals['nearest_resistance'], 'signal'] = -1

    # --- Heuristic check for the last bar ---
    distance = int(params.get('distance', 20))
    if len(signals) > distance:
        last_i = len(signals) - 1
        window = slice(last_i - distance, last_i)

        # Only override if last bar is neutral (0)
        if signals['signal'].iloc[last_i] == 0:
            if signals['high'].iloc[last_i] > signals['high'].iloc[window].max():
                signals.iloc[last_i, signals.columns.get_loc('signal')] = -1
            elif signals['low'].iloc[last_i] < signals['low'].iloc[window].min():
                signals.iloc[last_i, signals.columns.get_loc('signal')] = 1

    signals['positions'] = signals['signal'].cumsum()
    return signals

def vwap_breakout_strategy(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    VWAP Breakout strategy.
    Uses compute_vwap_indicator, then applies breakout confirmation logic.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']
    signals['volume'] = data['volume']

    # --- VWAP indicator ---
    vwap_df = indicators.compute_vwap_indicator(data, params)
    signals['vwap'] = vwap_df['vwap']

    # --- Parameters ---
    lookback = int(params.get('lookback', 14))  # breakout window

    # --- Breakout levels ---
    recent_high = signals['high'].rolling(window=lookback).max()
    recent_low = signals['low'].rolling(window=lookback).min()

    # --- Raw signal logic ---
    signals['raw_signal'] = np.where(
        (signals['price'] > signals['vwap']) & (signals['price'] > recent_high.shift(1)), 1,
        np.where(
            (signals['price'] < signals['vwap']) & (signals['price'] < recent_low.shift(1)), -1,
            0
        )
    )

    # --- Trade signal + positions ---
    signals['signal'] = signals['raw_signal'].diff().fillna(0)
    signals['positions'] = signals['signal'].cumsum()

    return signals

# --------------------------------------------------------------------
# Continuous score functions for the stacked meta-learner.
#
# Convention: each *_score returns a pandas Series of floats, roughly in
# [-1, +1], where positive = bullish setup, negative = bearish setup.
# The meta-learner is free to invert any individual sign via its weights;
# we only care that the score is monotone in 'how strong is this setup'.
# --------------------------------------------------------------------

_EPS = 1e-9


def _atr(data: pd.DataFrame, window: int) -> pd.Series:
    high = data["high"]
    low = data["low"]
    prev_close = data["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def dma_score(data: pd.DataFrame, params: dict) -> pd.Series:
    """ATR-normalized gap between short and long simple moving averages."""
    dma = indicators.compute_dma_indicators(data, params)
    atr = _atr(data, int(params.get("atr_window", 14)))
    raw = (dma["dma_short"] - dma["dma_long"]) / (atr + _EPS)
    return np.tanh(raw).rename("dma_score")


def ema_score(data: pd.DataFrame, params: dict) -> pd.Series:
    """ATR-normalized gap between short and long EMAs."""
    ema = indicators.compute_ema_indicators(data, params)
    atr = _atr(data, int(params.get("atr_window", 14)))
    raw = (ema["ema_short"] - ema["ema_long"]) / (atr + _EPS)
    return np.tanh(raw).rename("ema_score")


def rsi_score(data: pd.DataFrame, params: dict) -> pd.Series:
    """
    Mean-reversion-flavored RSI score: positive when oversold, negative when
    overbought. Values are in [-1, +1] by construction (RSI is in [0, 100]).
    """
    rsi = indicators.compute_rsi_indicator(data, params)["rsi"]
    return ((50.0 - rsi) / 50.0).rename("rsi_score")


def sr_score(data: pd.DataFrame, params: dict) -> pd.Series:
    """
    Support/Resistance score in [-1, +1].

    +1 when price sits at the most recent support (max bullish), -1 at
    resistance, 0 at midpoint. Computed as
    ``(R + S - 2*P) / (R - S)`` clipped to [-1, +1].
    """
    sr = indicators.compute_sr_indicator(data, params)
    support = sr["nearest_support"]
    resistance = sr["nearest_resistance"]
    rng = (resistance - support).replace(0, np.nan)
    score = (resistance + support - 2.0 * data["close"]) / (rng + _EPS)
    return score.clip(-1.0, 1.0).rename("sr_score")


def vwap_score(data: pd.DataFrame, params: dict) -> pd.Series:
    """ATR-normalized signed distance from VWAP."""
    vwap = indicators.compute_vwap_indicator(data, params)["vwap"]
    atr = _atr(data, int(params.get("atr_window", 14)))
    raw = (data["close"] - vwap) / (atr + _EPS)
    return np.tanh(raw).rename("vwap_score")


# Score functions registered by canonical strategy name (matches keys in
# ``trading_strategies`` below). The meta-learner consumes these.
strategy_scores = {
    "DMA Crossing": dma_score,
    "EMA Break": ema_score,
    "RSI": rsi_score,
    "S/R Structure": sr_score,
    "VWAP Break": vwap_score,
}


# --------------------------------------------------------------------
# Meta-learner adapter
#
# This is the callable handed to ``signal_logic`` in trading_engine. It
# wraps ``predict_meta_learner`` so the engine receives a signals frame
# in its expected schema (price/high/low/volume + signal + auxiliary
# probability columns).
# --------------------------------------------------------------------
def meta_learner_signals(data: pd.DataFrame, trained: dict, params: dict) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame(index=data.index if data is not None else [])

    from ML_Classifier.stacked_meta_learner import predict_meta_learner

    out = predict_meta_learner(data, trained, params)

    signals = pd.DataFrame(index=data.index)
    signals["price"] = data["close"]
    signals["high"] = data["high"]
    signals["low"] = data["low"]
    if "volume" in data.columns:
        signals["volume"] = data["volume"]

    cols = [c for c in ("prob_up", "prob_down", "score", "signal") if c in out.columns]
    signals = signals.join(out[cols], how="left")
    signals["signal"] = signals["signal"].fillna(0).astype(int)
    signals["positions"] = signals["signal"].cumsum()
    return signals


# Map of strategy names to their corresponding methods
trading_strategies = {
    "DMA Crossing" : double_moving_average_crossover,
    "EMA Break" : exponential_moving_average_breakout,
    "S/R Structure" : support_resistance_structure,
    "RSI" : relative_strength_index,
    "VWAP Break" : vwap_breakout_strategy,
}
