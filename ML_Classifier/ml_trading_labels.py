import pandas as pd
import numpy as np

def build_labels(df: pd.DataFrame, params: dict) -> pd.Series:
    """
     Create forward-looking binary labels for classification.

    Label definition:
      - horizon (int): number of minutes to look ahead (e.g., 3)
      - min_move (float): minimal fractional return to consider 'up' (e.g., 0.0005)

    Returns:
      A pandas Series of {0, 1} with the same index as df (tail rows dropped where future is unknown).
    """
    # 1) Read configuration parameters with safe defaults
    h = int(params.get("horizon", 3))
    tau = float(params.get("min_move", 0.0005))
    
    # 2) Compute the future close price by shifting backward (negative shift)
    #    shift(-h) means "value h rows ahead"
    future_close = df["close"].shift(-h)
    
    # 3) Compute the forward return from t to t+h
    #    (future_close - current_close) / current_close
    current_close = df["close"]
    ret_fwd = (future_close - current_close) / current_close
    
    # 4) Turn the return into a binary label:
    #    1 if ret_fwd >= tau (up move of at least tau). else 0
    y = (ret_fwd >= tau).astype(int)
    
    # 5) Drop rows where future_close is NaN (tail of the series)
    #    These cannot be labeled because the future isb't known yet
    valid_mask = ~future_close.isna()
    y = y.loc[valid_mask]
    
    return y

def build_labels_down(df: pd.DataFrame, params: dict) -> pd.Series:
    h = int(params.get("horizon", 3))
    tau = float(params.get("min_move", 0.0005))
    future_close = df["close"].shift(-h)
    current_close = df["close"]
    ret_fwd = (future_close - current_close) / current_close
    y_down = (ret_fwd <= -tau).astype(int)
    y_down = y_down.loc[~future_close.isna()]
    return y_down