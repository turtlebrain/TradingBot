import math
import numpy as np
import pandas as pd

# Position Sizing Methods

def all_in_sizer(state) ->int:
    """
    Allocates all available capital to the trade when signal > 0
    - if short_signal (signal < 0), it will sell all shares held if allow_short is True.
    - returned value can be positive (buy) or negative (sell)
    - if signal == 0, no action (return 0)
    Returns the absolute number of shares to trade.
    """
    signal = state['signal']
    price = state['price']
    cash = state['cash']
    shares = state['shares']
    equity = state['equity']
    allow_short = state['allow_short']
    slippage = state['slippage ']
    fee_rate = state['fee_rate']
    fee_min = state['fee_min']
    lot_size = state['lot_size']
    
    # Max buyable shares with current cash at slippage+fees
    buy_exec_price = price * (1 + slippage) #execution price including slippage for a buy order
    if fee_rate >= 1.0: #guard against fee rate being higher that 100%
        max_buyable = 0
    else:
        # Account for fee min: reserve cash for min fee then apply fee rate on remaining cash
        spendable_cash = max(0, cash - fee_min)
        max_buyable = math.floor(spendable_cash / (buy_exec_price * (1 + fee_rate)))
    if lot_size > 1:
        max_buyable= max_buyable - (max_buyable % lot_size )
    
    if signal > 0:
        return max(0, max_buyable)
    if signal < 0 and allow_short and shares > 0:
        return -shares
    return 0
    
    