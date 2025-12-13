import trading_indicators as indicators
from ML_Classifier.ml_trading_inference import predict_rule_ml_classifier
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
    Support/Resistance strategy with heuristic check for the last bar.
    """
    signals = pd.DataFrame(index=data.index)
    signals['price'] = data['close']
    signals['high'] = data['high']
    signals['low'] = data['low']

    sr_df = indicators.compute_sr_indicator(data, params)
    signals['nearest_support'] = sr_df['nearest_support']
    signals['nearest_resistance'] = sr_df['nearest_resistance']

    signals['signal'] = 0
    # Bounce off support
    signals.loc[signals['price'] > signals['nearest_support'], 'signal'] = 1
    # Reject resistance
    signals.loc[signals['price'] < signals['nearest_resistance'], 'signal'] = -1

    # --- Heuristic check for the last bar ---
    distance = int(params.get('distance', 20))
    if len(signals) > distance:
        last_i = len(signals) - 1
        window = slice(last_i - distance, last_i)
        if signals['high'].iloc[last_i] > signals['high'].iloc[window].max():
            signals.iloc[last_i, signals.columns.get_loc('signal')] = -1
        elif signals['low'].iloc[last_i] < signals['low'].iloc[window].min():
            signals.iloc[last_i, signals.columns.get_loc('signal')] = 1

    signals['positions'] = signals['signal'].cumsum()
    return signals

def ml_signals(data: pd.DataFrame, trained: dict, params: dict) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame(index=data.index if data is not None else [])

    out = predict_rule_ml_classifier(data, trained, params)

    signals = pd.DataFrame(index=data.index)
    signals["price"] = data["close"]
    signals["high"] = data["high"]
    signals["low"] = data["low"]
    
    # Add classifier outputs aligned by index
    signals = signals.join(out[["prob_up", "prob_down", "long_signal", "sell_signal"]], how="left")
    
    signals["signal"] = 0
    signals.loc[signals["long_signal"] == 1, "signal"] = 1
    signals.loc[signals["sell_signal"] == 1, "signal"] = -1
    
    signals["positions"] = signals["signal"].cumsum()

    return signals


# Map of strategy names to their corresponding methods
trading_strategies = {
    "DMA Crossing" : double_moving_average_crossover,
    "EMA Breakout" : exponential_moving_average_breakout,
    "S/R Structure" : support_resistance_structure,
    "RSI" : relative_strength_index
}
