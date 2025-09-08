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
        distance = int(params['distance'])
        # Detect resistance (peaks) and Support (Valleys) in terms of their indices
        resistance_idx, _ = find_peaks(data['high'], distance = distance)
        support_idx, _ = find_peaks(-data['low'], distance = distance)
        signals['signal'] = None
        for i in range(len(signals)):
            if i in resistance_idx and data['close'].iloc[i] < data['high'].iloc[i]:
                signals['signal'].iloc[i] = -1 #SELL
            elif i in support_idx and data['close'].iloc[i] > data['low'].iloc[i]:
                signals['signal'].iloc[i] = 1 #BUY
            else:
                signals['signal'].iloc[i] = 0 #HOLD
                
        signals['positions'] = signals['signal'].diff().fillna(0)
        
        return signals
    
    # Map of strategy names to their corresponding methods
    trading_strategies = {
        "Double Moving Average Crossover" : double_moving_average_crossover,
        "Exponential Moving Average Breakout" : exponential_moving_average_breakout,
        "Support and Resistance Structure" : support_resistace_structure,
    }