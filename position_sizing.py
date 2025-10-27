import math
import numpy as np
import pandas as pd

# Position Sizing Methods

def fixed_fraction_position_sizer(state, fixed_fraction : float) ->int:
    """
    Allocates a fixed-fraction of the available capital to the trade when signal > 0
    - if short_signal (signal < 0), it will sell a fixed-fraction of held if allow_short is True.
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
    slippage = state['slippage']
    fee_rate = state['fee_rate']
    fee_min = state['fee_min']
    lot_size = state['lot_size']
    
    # Max buyable shares with current cash at slippage+fees
    buy_exec_price = price * (1 + slippage) #execution price including slippage for a buy order
    if fee_rate >= 1.0: #guard against fee rate being higher that 100%
        max_buyable = 0
    else:
        # Account for fee min: reserve cash for min fee then apply fee rate on remaining cash
        fixed_fraction = max(0.0, min(1.0, fixed_fraction))
        cash_allowed = fixed_fraction * cash
        spendable_cash = max(0, cash_allowed - fee_min)
        max_buyable = math.floor(spendable_cash / (buy_exec_price * (1 + fee_rate)))
    if lot_size > 1:
        max_buyable= max_buyable - (max_buyable % lot_size )
    
    if signal > 0:
        return max(0, max_buyable)
    if signal < 0: 
        if allow_short:
            # Max-short such that short notional  is approx equity (no leverage)
            equity = state["equity"]
            sell_exc_price = price * (1 - slippage)
            target_short = int((equity // sell_exc_price))
            if lot_size > 1:
                target_short -= (target_short % lot_size)
            return -abs(target_short)
        else:
            return -abs(shares)
    return 0
    
    