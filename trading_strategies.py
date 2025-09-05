import pandas as pd
import numpy as np

class TradingStrategy:
    def __init__(self, data):
        self.data = data
    
    def simple_moving_average_crossover(data, params):
        """
        Implements a Simple Moving Average (SMA) Crossover trading strategy.

        Parameters:
            params['short_window'] short_window (int): The window size for the short-term moving average.
            params['long_window'] long_window (int): The window size for the long-term moving average.

        Returns:
            pd.DataFrame: DataFrame containing the price, short and long moving averages,
                          trading signals (1 for buy, 0 for hold/sell), and position changes.

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
    
    def double_moving_average_crossover(data):
        # TO-DO
        return 0
    
    def exponential_moving_average_breakout(data):
        # TO-DO
        return 0
    
        
    # Map of strategy names to their corresponding methods
    trading_strategies = {
        "Simple Moving Average Crossover" : simple_moving_average_crossover,
        "Double Moving Average Crossover" : double_moving_average_crossover,
        "Exponential Moving Average Breakout" : exponential_moving_average_breakout,
    }