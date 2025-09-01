import pandas as pd
import numpy as np

class TradingStrategy:
    def __init__(self, data):
        self.data = data
    
    def moving_average_crossover(data, short_window=50, long_window=200):
        """
        Implements a Simple Moving Average (SMA) Crossover trading strategy.

        Parameters:
            short_window (int): The window size for the short-term moving average.
            long_window (int): The window size for the long-term moving average.

        Returns:
            pd.DataFrame: DataFrame containing the price, short and long moving averages,
                          trading signals (1 for buy, 0 for hold/sell), and position changes.

        Strategy Logic:
            Generates a buy signal (1) when the short-term moving average crosses above
            the long-term moving average, otherwise the signal is 0.
        """
        signals = pd.DataFrame(index=data.index)
        signals['price'] = data['close']
        signals['short_mavg'] = data['close'].rolling(window=short_window, min_periods=1).mean()
        signals['long_mavg'] = data['close'].rolling(window=long_window, min_periods=1).mean()
        
        signals['signal'] = 0
        signals.loc[signals.index[short_window:], 'signal'] = (
            signals['short_mavg'][short_window:] > signals['long_mavg'][short_window:]
        ).astype(int)
        signals['positions'] = signals['signal'].diff()
        
        return signals
        
    # Map of strategy names to their corresponding methods
    trading_strategies = {
        "Moving Average Crossover Strategy" : moving_average_crossover
    }