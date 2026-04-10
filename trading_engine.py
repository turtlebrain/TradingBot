import pandas as pd
import numpy as np
import math
import strategy_tree_evaluator as ste
from Data.portfolio_state import PortfolioState
from Data.trade_record import TradeRecord
from Data.position_record import PositionRecord
import persistence as persist


engine_tol = 1e-9


def _signals_row_at(signals: pd.DataFrame, date) -> dict:
    """One row as dict; if duplicate labels, use the first row."""
    if signals.empty or date not in signals.index:
        return {}
    sel = signals.loc[date]
    if isinstance(sel, pd.DataFrame):
        if sel.empty:
            return {}
        sel = sel.iloc[0]
    elif not isinstance(sel, pd.Series):
        return {}
    return sel.to_dict()


def _coerce_trade_signal(raw) -> int:
    """Normalize signal to -1, 0, or 1 (handles duplicate-index rows, nested dicts, lists)."""
    if raw is None:
        return 0
    if isinstance(raw, dict):
        for key in ("signal", "value", "side"):
            if key in raw:
                return _coerce_trade_signal(raw[key])
        return 0
    if isinstance(raw, (list, tuple)):
        return _coerce_trade_signal(raw[0]) if raw else 0
    if isinstance(raw, np.ndarray):
        if raw.size == 0:
            return 0
        return _coerce_trade_signal(raw.flat[0])
    if isinstance(raw, (bool, np.bool_)):
        return int(bool(raw))
    if isinstance(raw, (int, np.integer)):
        v = int(raw)
        return 1 if v > 0 else (-1 if v < 0 else 0)
    if isinstance(raw, (float, np.floating)):
        if np.isnan(raw):
            return 0
        return 1 if raw > 0 else (-1 if raw < 0 else 0)
    try:
        v = float(raw)
        if np.isnan(v):
            return 0
        return 1 if v > 0 else (-1 if v < 0 else 0)
    except (TypeError, ValueError):
        return 0


def _scalar_float_from_cell(val, default=np.nan):
    """Extract one float from a cell (handles duplicate-index list values)."""
    if isinstance(val, (list, tuple)) and len(val) > 0:
        return _scalar_float_from_cell(val[0], default)
    if isinstance(val, np.ndarray) and val.size > 0:
        return _scalar_float_from_cell(val.flat[0], default)
    if val is None:
        return default
    try:
        x = float(val)
        return default if np.isnan(x) else x
    except (TypeError, ValueError):
        return default


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
    signal = _coerce_trade_signal(signals_row.get("signal", 0))

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
            state.stop_loss = _scalar_float_from_cell(
                signals_row.get("stop_loss", np.nan), default=np.nan
            )

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

    # Unified evaluation
    signals = evaluate_signals(buy_logic, sell_logic, data)
    # Optional stop-loss enrichment
    if stop_loss_func is not None and not signals.empty:
        signals = stop_loss_func(signals)

    state = PortfolioState(
        cash=float(starting_capital),
        shares=0,
        stop_loss=np.nan,
        prev_equity=float(starting_capital),
    )

    records = []
    for date, row in data.iterrows():
        sig_row = _signals_row_at(signals, date)
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
    stop_loss_func=None,
    starting_capital=10000.0,
    allow_short=False,
    slippage=0.001,
    fee_rate=0.001,
    fee_min=1.0,
    lot_size=1,
    account_id=None,
    session_id=None,
    ui_callback=None,
    history_window=500,
):
    existing_positions = {}
    existing_cash = None
    realized_pnl_total = 0.0

    if account_id:
        acct_row = persist.open_account(account_id)
        existing_cash = float(acct_row["cash"])
        realized_pnl_total = float(acct_row.get("realized_pnl", 0.0))

        pos_df = persist.load_positions(account_id)
        if not pos_df.empty:
            for _, row in pos_df.iterrows():
                existing_positions[row["symbol"]] = PositionRecord(
                    date=row.get("timestamp", row.name),
                    symbol=row["symbol"],
                    shares=int(row["quantity"]),
                    avg_price=float(row["avg_price"]),
                    market_price=float(row["current_price"]),
                    market_value=float(row["current_price"]) * int(row["quantity"]),
                    unrealized_pnl=float(row.get("unrealized_pnl", 0.0)),
                    side=row.get("side", ""),
                )

    init_cash = float(existing_cash if existing_cash is not None else starting_capital)
    symbol = getattr(candle_source, "symbol", None)
    init_shares = int(existing_positions[symbol].shares) if symbol in existing_positions else 0

    state = PortfolioState(
        cash=init_cash,
        shares=init_shares,
        stop_loss=float("nan"),
        prev_equity=init_cash,
    )
    # add realized_pnl tracking to state
    state.realized_pnl = realized_pnl_total

    trade_records: list[TradeRecord] = []
    position_records: list[PositionRecord] = []
    live_candles = pd.DataFrame()
    bootstrapped_position = False

    def _seed_existing_position_snapshot(candle_row: pd.Series, symbol: str):
        nonlocal bootstrapped_position, position_records, state
        if bootstrapped_position or symbol not in existing_positions:
            return

        existing_position = existing_positions[symbol]
        close = float(candle_row.get("close", float("nan")))
        qty = existing_position.shares
        avg_price = existing_position.avg_price

        unrealized_pnl = (close - avg_price) * qty if qty else 0.0

        pos0 = PositionRecord(
            date=candle_row.name,
            symbol=symbol,
            shares=qty,
            avg_price=avg_price,
            market_price=close,
            market_value=qty * close,
            unrealized_pnl=unrealized_pnl,
            side=existing_position.side,
        )
        position_records.append(pos0)
        state.prev_equity = state.cash + unrealized_pnl

        if session_id:
            persist.update_position(
                account_id=account_id,
                symbol=pos0.symbol,
                quantity=pos0.shares,
                avg_price=pos0.avg_price,
                current_price=pos0.market_price,
                unrealized_pnl=pos0.unrealized_pnl,
                side=pos0.side,
            )
            persist.update_account(
                account_id=account_id,
                cash=state.cash,
                realized_pnl=state.realized_pnl,
                equity=state.cash + pos0.market_value
            )

        bootstrapped_position = True

    def on_new_candle(candle_row: pd.Series, symbol: str = None):
        nonlocal state, trade_records, position_records, live_candles

        if symbol not in existing_positions and symbol != getattr(candle_source, "symbol", None):
            return

        live_candles = pd.concat([live_candles, candle_row.to_frame().T]).tail(history_window)

        _seed_existing_position_snapshot(candle_row, symbol)

        # Unified evaluation
        signals_df = evaluate_signals(buy_logic, sell_logic, live_candles)

        if stop_loss_func and not signals_df.empty:
            signals_df = stop_loss_func(signals_df)

        latest_signals = signals_df.iloc[-1].to_dict() if not signals_df.empty else {}

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


        if rec is not None:
            trade_records.append(rec)

        pos = update_position_record(position_records, rec, state, candle_row, symbol)
        position_records.append(pos)

        if session_id:
            persist.update_position(
                account_id=account_id,
                symbol=pos.symbol,
                quantity=pos.shares,
                avg_price=pos.avg_price,
                current_price=pos.market_price,
                unrealized_pnl=pos.unrealized_pnl,
                side=pos.side,
            )
            persist.update_account(
                account_id=account_id,
                cash=state.cash,
                realized_pnl=state.realized_pnl,
                equity=state.cash + pos.market_value
            )

        if ui_callback and rec is not None:
            df = pd.DataFrame([rec.__dict__], index=[candle_row.name])
            ui_callback(df)

    candle_source.subscribe(lambda row: on_new_candle(row, getattr(candle_source, "symbol", None)))

    def finalize():
        trades_df = pd.DataFrame([r.__dict__ for r in trade_records])
        if session_id:
            if not trades_df.empty:
                persist.insert_trade_stream(session_id, trades_df)
            if position_records:
                pos = position_records[-1]
                persist.update_position(
                    account_id=account_id,
                    symbol=pos.symbol,
                    quantity=pos.shares,
                    avg_price=pos.avg_price,
                    current_price=pos.market_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    side=pos.side,
                )
                persist.update_account(
                    account_id=account_id,
                    cash=state.cash,
                    realized_pnl=state.realized_pnl,
                    equity=state.cash + pos.market_value
                )
        return trades_df

    return finalize

def evaluate_signals(buy_logic, sell_logic, data: pd.DataFrame):
    if callable(buy_logic):
        signals_df = buy_logic(data)
        if signals_df is None or signals_df.empty:
            return pd.DataFrame(index=data.index)
        return signals_df

    signals_df = ste.evaluate_strategy(buy_logic, sell_logic, data)

    if "buy" in signals_df.columns and "sell" in signals_df.columns:
        signals_df = signals_df.rename(columns={"buy": "long_signal", "sell": "short_signal"})

    return signals_df

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

def calculate_avg_price(old_shares, old_avg_price, trade_shares, trade_price):
    """
    Calculate new average price after a trade.
    - old_shares: current position size (can be 0, positive for long, negative for short)
    - old_avg_price: current average price
    - trade_shares: signed quantity of the trade (+buy, -sell)
    - trade_price: execution price of the trade
    """
    # No existing position → avg price is just the trade price
    if old_shares == 0:
        return trade_price

    # Same direction (adding to position)
    if (old_shares > 0 and trade_shares > 0) or (old_shares < 0 and trade_shares < 0):
        new_shares = old_shares + trade_shares
        return ((old_avg_price * old_shares) + (trade_price * trade_shares)) / new_shares

    # Reducing position (partial close) → avg price unchanged
    if abs(trade_shares) < abs(old_shares):
        return old_avg_price

    # Flipping position (close + open opposite) → reset avg price
    return trade_price

def calculate_position_pnl(prev_pos, trade_shares, trade_price, current_price, avg_price, total_shares):
    """
    Calculate realized and unrealized P/L for a position.

    prev_pos: previous PositionRecord or None
    trade_shares: signed trade size (positive buy, negative sell)
    trade_price: execution price of the trade
    current_price: latest market price
    avg_price: updated average price of the position
    total_shares: current open shares after the trade

    Returns:
        realized_delta: realized P&L from this trade (to add to account state)
        unrealized_pnl: unrealized P&L on remaining shares
    """

    realized_delta = 0.0

    # If reducing or flipping, compute realized P/L on closed portion
    if prev_pos and (trade_shares * prev_pos.shares) < 0:
        closed_qty = min(abs(trade_shares), abs(prev_pos.shares))
        direction = 1 if prev_pos.shares > 0 else -1
        realized_delta = closed_qty * (trade_price - prev_pos.avg_price) * direction

    # Unrealized P/L on remaining shares
    unrealized_pnl = (current_price - avg_price) * total_shares

    return realized_delta, unrealized_pnl

def update_position_record(position_records, rec: TradeRecord, state: PortfolioState, candle_row, symbol: str):
    """
    Update the position record given a new trade and current portfolio state.

    - Uses calculate_position_pnl to compute realized delta (for account) and unrealized P&L (for position).
    - Updates PortfolioState.realized_pnl with the realized delta.
    - Returns a new PositionRecord snapshot with unrealized P&L only.
    """

    prev_pos = next((p for p in reversed(position_records) if p.symbol == symbol), None)

    # Calculate new average price after trade
    new_avg_price = calculate_avg_price(
        old_shares=prev_pos.shares if prev_pos else 0,
        old_avg_price=prev_pos.avg_price if prev_pos else 0.0,
        trade_shares=rec.order,
        trade_price=rec.exec_price if rec.exec_price is not None and not math.isnan(rec.exec_price) else 0.0
    )

    # Compute realized delta (for account) and unrealized P&L (for position)
    realized_delta, unrealized_pnl = calculate_position_pnl(
        prev_pos=prev_pos,
        trade_shares=rec.order,
        trade_price=rec.exec_price,
        current_price=candle_row["close"],
        avg_price=new_avg_price,
        total_shares=state.shares
    )

    # Update account-level realized P&L
    if rec is not None and rec.exec_price is not None:
        state.realized_pnl = getattr(state, "realized_pnl", 0.0) + realized_delta

    # Build new PositionRecord snapshot (only unrealized P&L)
    pos = PositionRecord(
        symbol=symbol,
        shares=state.shares,
        avg_price=new_avg_price,
        market_price=candle_row["close"],
        market_value=state.shares * candle_row["close"],
        unrealized_pnl=unrealized_pnl,
        side="long" if state.shares > 0 else "short" if state.shares < 0 else "",
        date=candle_row.name
    )

    return pos