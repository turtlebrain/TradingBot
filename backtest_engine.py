import pandas as pd
import numpy as np
import math

engine_tol = 1e-9

def backtest_strategy(
    data :pd.DataFrame, 
    strategy_func, 
    strategy_param,
    position_sizer_func, 
    position_sizer_param,
    stop_loss_func,
    starting_capital=10000.0, 
    allow_short=False, 
    slippage=0.001, 
    fee_rate=0.001, 
    fee_min=1.0, 
    lot_size=1
    ) ->pd.DataFrame:
    """ 
    Backtests a trading strategy on historical data.
    :param data: DataFrame with historical price data 
    :param strategy_func: Function that generates trading signals
    :param strategy_param: Strategy parameters being passed to strategy function
    :param position_sizer_func: Function that determines position size based on state
    :param position_sizer_param: Position Sizer parameters being passed to position sizer function
    :param stop_loss_func: Function that determines the stop loss to manage risk
    :param initial_capital: Starting capital for backtest
    :param allow_short: Whether to allow short selling
    :param slippage: Proportional slippage per trade (e.g., 0.001 for 0.1%)
    :param fee_rate: Proportional fee rate per trade (e.g., 0.001 for 0.1%)
    :param fee_min: Minimum fee per trade
    :param lot_size: Minimum tradeable lot size (e.g., 1 for stocks)
    :return: DataFrame with backtest results including equity curve
    """
    # Generate signals using the provided strategy function
    candle_data = pd.DataFrame()
    if data is not None:
        candle_data = data.copy()
        if candle_data.empty:
            raise ValueError("Input data is empty.")
    if lot_size < 1:
        raise ValueError("lot_size must be at least 1.")
    shares = 0
    cash = float(starting_capital)
    signals = strategy_func(candle_data, strategy_param)
    if stop_loss_func is not None:
        signals = stop_loss_func(signals)
        
    # Output DataFrame to store backtest results
    out = {
        "price": [],
        "signal": [],
        "shares": [],
        "cash": [],
        "equity": [],
        "market_value": [],
        "order": [],
        "exec_price": [],
        "stop_loss": [],
        "fees": [],
        "trade_side": [],  # 'buy' or 'sell' or ''
        "pnl": []  # profit and loss from closed trades
    }
    # Build state to get order size from position sizer
    prev_equity = starting_capital
    stop_loss = np.nan
    for date, row in data.iterrows():
        price = row['close']
        signal = signals.at[date, 'signal'] if date in signals.index else 0
        equity = cash + shares * price
        
        state = {
            'signal': signal,
            'price': price,
            'cash': cash,
            'shares': shares,
            'equity': equity,
            'allow_short': allow_short,
            'slippage ': slippage,
            'fee_rate': fee_rate,
            'fee_min': fee_min,
            'lot_size': lot_size
        }
        # Get order size from position sizer
        fixed_fraction = float(position_sizer_param)
        order = position_sizer_func(state, fixed_fraction)
        # Round to lot size
        if lot_size > 1 and order != 0:
            if order > 0:
                order = order - (order % lot_size)
            else:
                order = -1*(order + (-order % lot_size)) #keep order negative for sells
        
        trade_side = ""
        exec_px = np.nan
        fees_paid = 0
        trade_side = ''
      
        # RISK MANAGEMENT - STOP-LOSS
        if price < stop_loss:
            state['signal'] = -1
            order = position_sizer_func(state, fixed_fraction)

        # BUY ORDER
        if order > 0:
            trade_side = "buy"
            buy_px = price * (1 + slippage)  # buying price including slippage for a buy order
            if fee_rate < 1.0:
                spendable = max(0, cash - fee_min)
                max_affordable = math.floor(spendable / (buy_px * (1 + fee_rate)))
            else:
                max_affordable = 0
            if lot_size > 1:
                max_affordable = max_affordable - (max_affordable % lot_size)
                
            qty = max(0, min(order, max_affordable))
            
            # Recalculate exact fees on the executed notional (notional = cost of shares minus fees)
            notional = qty * buy_px
            fees_paid = (fee_rate * notional)
            if fee_min > 0 and qty > 0:
                fees_paid = max(fee_min, fees_paid)
            
            total_cost = notional + fees_paid   
            if total_cost -  engine_tol > cash:
                # Final safeguard: if still too expensive due to rounding, reduce by one lot
                step = lot_size if lot_size > 1 else 1
                while qty > 0  and (qty * buy_px + max(fee_min, fee_rate * qty * buy_px)) - engine_tol > cash:
                    qty -= step
                notional = qty * buy_px
                fees_paid = max(fee_min, fee_rate * notional) if qty > 0 else 0.0
                total_cost = notional + fees_paid
            shares += qty
            cash -= total_cost 
            exec_px = buy_px if qty > 0 else np.nan
            order = qty # actual filled
            if signals.get('stop_loss') is not None:
                stop_loss = signals.at[date, 'stop_loss'] if date in signals.index else np.nan
            
        # SELL ORDER
        elif order < 0:
            trade_side = "sell"
            sell_px = price * (1 - slippage)
            qty_requested = -order
            
            if allow_short:
                qty = qty_requested # allow selling beyond current long (shorting)
                
            else:
                qty = min(qty_requested, max(0, shares)) # safequard against selling more shares than owed 
            
            notional = qty * sell_px
            fees_paid = (fee_rate * notional)
            if fee_min > 0.0 and qty > 0:
                fees_paid = max(fee_min, fees_paid)
            proceeds = notional - fees_paid
            cash += proceeds
            shares -= qty
            exec_px = sell_px if qty > 0 else np.nan
            order = -qty # actual filled (negative)
            stop_loss = np.nan
    
            
        # Record bactest results
        equity = cash + shares * price
        pnl = equity - prev_equity
        prev_equity = equity
        
        out["price"].append(price)
        out["signal"].append(signal)
        out["shares"].append(shares)
        out["cash"].append(cash)
        out["equity"].append(equity)
        out["market_value"].append(shares * price)
        out["order"].append(order)
        out["exec_price"].append(exec_px)
        out["stop_loss"].append(stop_loss)
        out["fees"].append(fees_paid)
        out["trade_side"].append(trade_side if order != 0 else "")
        out["pnl"].append(pnl)
        
    result = pd.DataFrame(out, index = data.index)
    # Performance helpers
    result["cum_max_equity"] = result["equity"].cummax()
    result["drawdown"] = (result["equity"] - result["cum_max_equity"]) / result["cum_max_equity"].replace(0, np.nan)  
    result["returns"] = result["equity"].pct_change().fillna(0.0)
    return result

def compute_sharpe_ratio(returns: pd.Series, timeframe: str = "OneDay", annual_rf: float = 0.02) -> float:
    """
    Compute annualized Sharpe Ratio for different timeframes.
    
    Parameters:
    - returns: pd.Series of periodic returns (e.g., hourly, daily, weekly, monthly)
    - timeframe: one of ["OneHour", "OneDay", "OneWeek", "OneMonth"]
    - annual_rf: annualized risk-free rate (default = 0.02 = 2%)
    
    Returns:
    - Sharpe Ratio (float)
    """
    # Map timeframe to periods per year
    frequency_map = {
        "OneMinute": 252 * 6.5 * 60,  # ~6.5 trading hours/day × 252 days × 60 minutes
        "OneHour": int(252 * 6.5),  # ~6.5 trading hours/day × 252 days
        "OneDay": 252,              # trading days/year
        "OneWeek": 52,              # weeks/year
        "OneMonth": 12              # months/year
    }
    
    if timeframe not in frequency_map:
        raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {list(frequency_map.keys())}")
    
    periods_per_year = frequency_map[timeframe]
    
    # Convert annual risk-free rate to per-period
    rf_per_period = (1 + annual_rf) ** (1 / periods_per_year) - 1
    
    # Excess returns
    excess_returns = returns - rf_per_period
    
    mean_excess = excess_returns.mean()
    sigma_p = excess_returns.std(ddof=1)
    
    # Annualized Sharpe
    sharpe = (mean_excess / sigma_p) * np.sqrt(periods_per_year)
    return sharpe

