import pandas as pd
import numpy as np
import math
import strategy_tree_evaluator as ste
from Data.portfolio_state import PortfolioState
from Data.trade_record import TradeRecord
import persistence as persist


engine_tol = 1e-9

def strategy_step(
    data_row,
    state: PortfolioState,
    signals_row: dict,
    position_sizer_func,
    position_sizer_param,
    allow_short: bool,
    slippage: float,
    fee_rate: float,
    fee_min: float,
    lot_size: int
) -> tuple[PortfolioState, TradeRecord]:
    price = data_row["close"]
    signal = signals_row.get("signal", 0)

    equity = state.cash + state.shares * price
    fixed_fraction = float(position_sizer_param)

    # Build state dict 
    sizing_state = {
        "signal": signal,
        "price": price,
        "cash": state.cash,
        "shares": state.shares,
        "equity": equity,
        "allow_short": allow_short,
        "slippage": slippage,
        "fee_rate": fee_rate,
        "fee_min": fee_min,
        "lot_size": lot_size,
    }

    # Apply stop-loss: if breached, force a sell signal for sizing
    if not np.isnan(state.stop_loss) and price < state.stop_loss:
        sizing_state["signal"] = -1

    order = position_sizer_func(sizing_state, fixed_fraction)

    # Round to lot size
    if lot_size > 1 and order != 0:
        if order > 0:
            order = order - (order % lot_size)
        else:
            order = -1 * (order + (-order % lot_size))

    trade_side = ""
    exec_px = np.nan
    fees_paid = 0.0
    filled_qty = 0

    # BUY
    if order > 0:
        trade_side = "buy"
        buy_px = price * (1 + slippage)
        spendable = max(0, state.cash - (fee_min if fee_rate < 1.0 else 0))
        max_affordable = math.floor(spendable / (buy_px * (1 + fee_rate))) if fee_rate < 1.0 else 0
        if lot_size > 1:
            max_affordable -= (max_affordable % lot_size)
        qty = max(0, min(order, max_affordable))

        # Recalculate fees on executed notional
        notional = qty * buy_px
        fees_paid = max(fee_min, fee_rate * notional) if qty > 0 else 0.0
        total_cost = notional + fees_paid

        # Final safeguard loop
        step = lot_size if lot_size > 1 else 1
        while qty > 0 and (qty * buy_px + max(fee_min, fee_rate * qty * buy_px)) > state.cash:
            qty -= step
        notional = qty * buy_px
        fees_paid = max(fee_min, fee_rate * notional) if qty > 0 else 0.0
        total_cost = notional + fees_paid

        state.shares += qty
        state.cash -= total_cost
        exec_px = buy_px if qty > 0 else np.nan
        filled_qty = qty

        # Update stop-loss if provided by signals
        if "stop_loss" in signals_row:
            state.stop_loss = signals_row.get("stop_loss", np.nan)

    # SELL
    elif order < 0:
        trade_side = "sell"
        sell_px = price * (1 - slippage)
        qty_requested = -order
        qty = qty_requested if allow_short else min(qty_requested, max(0, state.shares))

        notional = qty * sell_px
        fees_paid = max(fee_min, fee_rate * notional) if qty > 0 else 0.0
        proceeds = notional - fees_paid
        state.cash += proceeds
        state.shares -= qty
        exec_px = sell_px if qty > 0 else np.nan
        filled_qty = -qty
        state.stop_loss = np.nan

    # Record
    equity = state.cash + state.shares * price
    pnl = equity - state.prev_equity
    state.prev_equity = equity

    record = TradeRecord(
        price=price, signal=signal, shares=state.shares, cash=state.cash,
        equity=equity, market_value=state.shares * price, order=filled_qty,
        exec_price=exec_px, stop_loss=state.stop_loss, fees=fees_paid,
        trade_side=(trade_side if filled_qty != 0 else ""), pnl=pnl
    )
    return state, record


def backtest_strategy(
    data :pd.DataFrame, 
    buy_logic, 
    sell_logic,
    position_sizer_func, 
    position_sizer_param,
    stop_loss_func,
    starting_capital=10000.0, 
    allow_short=False, 
    slippage=0.001, 
    fee_rate=0.001, 
    fee_min=1.0, 
    lot_size=1,
    session_id=None
    ) ->pd.DataFrame:
    """ 
    Backtests a trading strategy on historical data.
    :param data: DataFrame with historical price data 
    :param buy_logic: Logic (Serialized Strategy Section) that generates buy signals
    :param sell_logic: Logic (Serialized Strategy Section) that generates sell signals
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
    if data is None or data.empty:
        raise ValueError("Input data is empty.")
    if lot_size < 1:
        raise ValueError("lot_size must be at least 1.")

    signals = ste.evaluate_strategy(buy_logic, sell_logic, data)
    if stop_loss_func is not None:
        signals = stop_loss_func(signals)

    state = PortfolioState(
        cash=float(starting_capital),
        shares=0,
        stop_loss=np.nan,
        prev_equity=float(starting_capital),
    )

    records = []
    for date, row in data.iterrows():
        sig_row = signals.loc[date].to_dict() if date in signals.index else {}
        state, rec = strategy_step(
            row, state, sig_row,
            position_sizer_func, position_sizer_param,
            allow_short, slippage, fee_rate, fee_min, lot_size
        )
        records.append(rec.__dict__)

    result = pd.DataFrame(records, index=data.index)

    # Performance helpers (unchanged)
    result["cum_max_equity"] = result["equity"].cummax()
    result["drawdown"] = (result["equity"] - result["cum_max_equity"]) / result["cum_max_equity"].replace(0, np.nan)
    result["returns"] = result["equity"].pct_change().fillna(0.0)
    
    # Persist results as a trade stream and add to trade history
    if session_id:
        persist.insert_trade_stream(session_id, result)
        
    return result


def run_live_strategy(
    candle_source,
    buy_logic,
    sell_logic,
    position_sizer_func,
    position_sizer_param,
    stop_loss_func,
    starting_capital=10000.0,
    allow_short=False,
    slippage=0.001,
    fee_rate=0.001,
    fee_min=1.0,
    lot_size=1,
    session_id=None,
    ui_callback=None
    ):
    """
    Run a trading strategy in live paper mode using streaming candles only.
    Processes each new candle as it arrives, applies strategy logic, and
    persists TradeRecords incrementally.
    """
    
    state = PortfolioState(
        cash=float(starting_capital),
        shares=0,
        stop_loss=float("nan"),
        prev_equity=float(starting_capital),
    )
    records: list[TradeRecord] = []

    def on_new_candle(candle_row: pd.Series):
        nonlocal state, records
        # compute signals
        signals_df = ste.evaluate_strategy(buy_logic, sell_logic, pd.DataFrame([candle_row]))
        if stop_loss_func:
            signals_df = stop_loss_func(signals_df)
        latest_signals = signals_df.iloc[-1].to_dict()

        # step strategy
        state, rec = strategy_step(
            data_row=candle_row,
            state=state,
            signals_row=latest_signals,
            position_sizer_func=position_sizer_func,
            position_sizer_param=position_sizer_param,
            allow_short=allow_short,
            slippage=slippage,
            fee_rate=fee_rate,
            fee_min=fee_min,
            lot_size=lot_size,
        )

        records.append(rec)

        # UI update only
        if ui_callback:
            df = pd.DataFrame([rec.__dict__], index=[candle_row.name])
            ui_callback(df)

    # subscribe to stream
    candle_source.subscribe(on_new_candle)

    # return all records when session ends (caller decides when to stop)
    def finalize():
        df = pd.DataFrame([r.__dict__ for r in records])
        if session_id:
            persist.insert_trade_stream(session_id, df)
        return df

    return finalize



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

