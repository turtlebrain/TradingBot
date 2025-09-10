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
        signal_data = pd.DataFrame()
        if data is None:
            raise ValueError("Missing Signal Data")
        signal_data = data.copy()
        signal_data['H_L'] = signal_data['high'] - signal_data['low']                       # Range high - low
        signal_data['H_PC'] = abs(signal_data['high'] - signal_data['price'].shift(1))      # Range high - previous close
        signal_data['L_PC'] = abs(signal_data['low'] - signal_data['price'].shift(1))       # Range low - previous close
        signal_data['TR'] = signal_data[['H_L', 'H_PC', 'L_PC']].max(axis=1)                # True range - max(H-L, H-PC, L-PC)
        signal_data['ATR'] = signal_data['TR'].rolling(average_time_interval).mean()        # Average true range
        signal_data['stop_loss'] = np.nan
        for i in range(1, len(signal_data)):
            if signal_data['positions'].iloc[i] > 0:
                entry_price = signal_data['price'].iloc[i]
                stop_loss = entry_price - 2* signal_data['ATR'].iloc[i]
                signal_data['stop_loss'].iloc[i] = stop_loss       
        return signal_data