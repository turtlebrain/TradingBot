import pandas as pd
import numpy as np

class StopLoss:
    def __init__(self, data):
        self.signal_data = data
    
    def average_true_range_stop(data, average_time_interval = 14):
        """
        Summary:
            Uses Average True Range to set a volatility-adjusted stop
            and adds a ['stop_loss'] column to the signal data
            
        Args:
            data (pd.DataFrame) : signal_data
            
        Returns:
            signal_data: returns a modified signal_data with additional columns ['stop_loss'] and ['ATR']
        """
        if data is None:
            raise ValueError("Missing Signal Data")

        # Work on a copy to avoid modifying the original
        signal_data = data.copy()

        # Calculate ATR components
        signal_data['H_L'] = signal_data['high'] - signal_data['low']
        signal_data['H_PC'] = (signal_data['high'] - signal_data['price'].shift(1)).abs()
        signal_data['L_PC'] = (signal_data['low'] - signal_data['price'].shift(1)).abs()

        # True Range and ATR
        signal_data['TR'] = signal_data[['H_L', 'H_PC', 'L_PC']].max(axis=1)
        signal_data['ATR'] = signal_data['TR'].rolling(average_time_interval).mean()

        # Initialize stop_loss column
        signal_data['stop_loss'] = np.nan

        # Position-based loop (index may be DatetimeIndex, not 0..n-1)
        stop_ix = signal_data.columns.get_loc("stop_loss")
        for pos in range(1, len(signal_data)):
            if signal_data["positions"].iloc[pos] > 0:
                entry_price = signal_data["price"].iloc[pos]
                atr = signal_data["ATR"].iloc[pos]
                if pd.notna(atr):
                    signal_data.iat[pos, stop_ix] = entry_price - 2 * atr

        return signal_data
