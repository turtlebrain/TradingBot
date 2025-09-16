import pandas as pd
import numpy as np
from scipy.signal import find_peaks

class TradingStrategy:
    def __init__(self, data):
        self.data = data
    
    def double_moving_average_crossover(data, params):
        """
        Implements a Double Moving Average (MA) Crossover trading strategy.

        Parameters:
            params['short_window'] short_window (int): The window size for the short-term moving average.
            params['long_window'] long_window (int): The window size for the long-term moving average.

        Returns:
            pd.DataFrame: DataFrame containing the price, short and long moving averages,
                          trading signals (1 for buy, -1 for sell, 0 for hold), and position changes.

        Strategy Logic:
            Generates a buy signal (1) when the short-term moving average crosses above the long-term moving average, 
            Generates a sell signal (-1) when the short-term moving average crosses below the long-term moving average
            Otherwise return a flat signal (0) if the short-term moving average = long-term moving average
        """
        short_window = int(params['short_window'])
        long_window = int(params['long_window'])
        signals = pd.DataFrame(index=data.index)
        signals['price'] = data['close']
        signals['high'] = data['high']
        signals['low'] = data['low']
        signals['short_mavg'] = data['close'].rolling(window=short_window, min_periods=1).mean()
        signals['long_mavg'] = data['close'].rolling(window=long_window, min_periods=1).mean()
        
        signals['signal'] = np.where(
            signals['short_mavg'] > signals['long_mavg'],  1,
            np.where(signals['short_mavg'] < signals['long_mavg'], -1, 0)
        )

        signals['positions'] = signals['signal'].diff().fillna(0)
        
        return signals
    
    # More reactive to price changes
    def exponential_moving_average_breakout(data):
        # TO-DO
        return 0
    
    def relative_strength_index(data, params):
        """
        Compute RSI-based trading signals.
    
        Parameters:
            params['lookback']  : int, RSI lookback period (default 14).
            params['overbought'] : float, RSI threshold above which we consider the market overbought (default 70).
            params['oversold'] : float, RSI threshold below which we consider the market oversold (default 30).
    
        Returns:
            pd.DataFrame : Original DataFrame with added 'rsi' and 'signal' columns.
        """
        signals = pd.DataFrame(index=data.index)
        signals['price'] = data['close']
        signals['high'] = data['high']
        signals['low'] = data['low']
        lookback = int(params['lookback'])
        overbought = float(params['overbought'])
        oversold = float(params['oversold'])
        # Calculate gains (+positive price change), and losses (-negative price change)
        delta = signals['price'].diff()
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        # Calculate rolling averages (Wilder's smoothing)
        avg_gain = pd.Series(gain).rolling(window=lookback, min_periods = lookback).mean()
        avg_loss = pd.Series(loss).rolling(window=lookback, min_periods = lookback).mean()
        
        for i in range(lookback, len(signals)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (lookback - 1) + gain[i]) / lookback
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (lookback - 1) + loss[i]) / lookback
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss   
        rsi = 100 - (100 / (1 + rs))
        signals['rsi']= rsi
        
        signals['signal'] = 0
        # Buy signal: RSI crosses above oversold
        signals.loc[(signals['rsi'] > oversold) & (signals['rsi'].shift(1) <= oversold), 'signal'] = 1
        # Sell signal: RSI crosses below overbought
        signals.loc[(signals['rsi'] < overbought) & (signals['rsi'].shift(1)) >= overbought, 'signal'] = -1
        
        signals['positions'] = signals['signal'].diff().fillna(0)

        return signals
    
    def support_resistace_structure(data, params):
        """
        Implements a simple Peak/Valley Detection to find Support and Resistance Levels
        
        Parameters:
            params['distance'] distance for peak/valley detection for e.g 5 means peaks are found with at least 5 candles inbetween

        Returns:
            pd.DataFrame: DataFrame containing the price,
                          trading signals (1 for buy, 0 for hold/sell), and position changes.

        Strategy Logic:
            Generates a buy signal (1) when the price bounces off a detected support level
            Generates a sell signal (-1) when the price rejects a detected resistance level
            Otherwise return a flat signal (0) 
        """
        signals = pd.DataFrame(index=data.index)
        signals['price'] = data['close']
        signals['high'] = data['high']
        signals['low'] = data['low']
        distance = int(params['distance'])
        # Detect resistance (peaks) and Support (Valleys) in terms of their indices
        resistance_idx, _ = find_peaks(data['high'], distance = distance)
        support_idx, _ = find_peaks(-data['low'], distance = distance)
        # Initialize 'signal' column with 0 (HOLD) by default
        signals['signal'] = 0 
        # SELL condition: index in resistance_idx AND close < high
        sell_mask = signals.index.isin(resistance_idx) & (data['close'] < data['high'])
        # BUY condition: index in support_idx AND close > low
        buy_mask = signals.index.isin(support_idx) & (data['close'] > data['low'])
        # Apply SELL (-1) and BUY (+1) signals
        signals.loc[sell_mask, 'signal'] = -1
        signals.loc[buy_mask, 'signal'] = 1    
        
        signals['positions'] = signals['signal'].diff().fillna(0)
        
        return signals
    
    # Map of strategy names to their corresponding methods
    trading_strategies = {
        "Double Moving Average Crossover" : double_moving_average_crossover,
        "Exponential Moving Average Breakout" : exponential_moving_average_breakout,
        "Support and Resistance Structure" : support_resistace_structure,
        "Relative Strength Index" : relative_strength_index
    }