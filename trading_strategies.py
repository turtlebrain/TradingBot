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
            params['short_window'] short_window (int): The window size for the short-term moving average (default 20).
            params['long_window'] long_window (int): The window size for the long-term moving average (default 50).

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
        
        signals['raw_signal'] = np.where(
            signals['short_mavg'] > signals['long_mavg'],  1,
            np.where(signals['short_mavg'] < signals['long_mavg'], -1, 0)
        )
        signals['signal']=signals['raw_signal'].diff().fillna(0)
        signals['positions'] = signals['signal'].diff().fillna(0)
        
        return signals
    
    # More reactive to price changes
    def exponential_moving_average_breakout(data, params):
        """
        Implements an Exponential Moving Average (EMA) breakout strategy

        Parameters:
            params['short_window'] short_window (int): The window size for the short-term moving average.
            params['long_window'] long_window (int): The window size for the long-term moving average.

        Returns:
            pd.DataFrame: DataFrame containing the price, short and long moving averages,
                          trading signals (1 for buy, -1 for sell, 0 for hold), and position changes.
        
        Strategy Logic:
            Generates a buy signal (1) when the short-term EMA crosses above the long-term EMA, 
            Generates a sell signal (-1) when the short-term EMA crosses below the long-term EMA
            Otherwise return a flat signal (0) if the short-term EMA = long-term EMA
        """
        short_window = int(params['short_window'])
        long_window = int(params['long_window'])
        signals = pd.DataFrame(index=data.index)
        signals['price'] = data['close']
        signals['high'] = data['high']
        signals['low'] = data['low']
        # Calculate EMAs using .ewm() (Exponential Weighted Moving average) 
        # adjust = False ensures the EMA calculation uses a recursive formula(common in trading)
        signals['EMA_short'] = data['close'].ewm(span=short_window, adjust=False).mean()
        signals['EMA_long'] = data['close'].ewm(span=long_window, adjust=False).mean()
        
        signals['raw_signal'] = np.where(
            signals['EMA_short'] > signals['EMA_long'],  1,
            np.where(signals['EMA_short'] < signals['EMA_long'], -1, 0)
        )
        signals['signal']=signals['raw_signal'].diff().fillna(0)
        signals['positions'] = signals['signal'].diff().fillna(0)
        
        return signals
    
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
    
    def support_resistance_structure(data: pd.DataFrame, params: dict) -> pd.DataFrame:
       """
       Implements a simple Peak/Valley Detection to find Support and Resistance Levels.

       Parameters:
           data: DataFrame with columns ['high','low','close']
           params['distance']: minimum separation between peaks/valleys

       Returns:
           pd.DataFrame with columns: price, high, low, signal, positions
           
        Strategy Logic:
            Generates a buy signal (1) when the price bounces off a detected support level
            Generates a sell signal (-1) when the price rejects a detected resistance level
            Otherwise return a flat signal (0) 
       """
       signals = pd.DataFrame(index=data.index.copy())
       signals['price'] = data['close']
       signals['high'] = data['high']
       signals['low'] = data['low']
       signals['signal'] = 0    
       distance = int(params['distance'])   
       # Standard confirmed peaks/valleys
       res_idx, _ = find_peaks(signals['high'], distance=distance)
       sup_idx, _ = find_peaks(-signals['low'], distance=distance)  
       for i in res_idx:
           if signals['price'].iloc[i] < signals['high'].iloc[i]:
               signals.iloc[i, signals.columns.get_loc('signal')] = -1
       for i in sup_idx:
           if signals['price'].iloc[i] > signals['low'].iloc[i]:
               signals.iloc[i, signals.columns.get_loc('signal')] = 1   
       # --- NEW: heuristic check for the last bar ---
       if len(signals) > distance:
           last_i = len(signals) - 1
           window = slice(last_i - distance, last_i)  # previous N bars     
           if signals['high'].iloc[last_i] > signals['high'].iloc[window].max():
               signals.iloc[last_i, signals.columns.get_loc('signal')] = -1
           elif signals['low'].iloc[last_i] < signals['low'].iloc[window].min():
               signals.iloc[last_i, signals.columns.get_loc('signal')] = 1  
       signals['positions'] = signals['signal'].diff().fillna(0)
       return signals


    
    # Map of strategy names to their corresponding methods
    trading_strategies = {
        "DMA Crossover" : double_moving_average_crossover,
        "EMA Breakout" : exponential_moving_average_breakout,
        "S/R Structure" : support_resistance_structure,
        "RSI" : relative_strength_index
    }