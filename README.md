# TradingBot

TradingBot is a Python desktop app for testing and running algorithmic trading workflows. It provides a Tkinter/ttkbootstrap GUI, broker adapters for Questrade and Interactive Brokers, historical candle lookup, live candle streaming, account/session persistence, and a stacked machine-learning strategy workflow built on top of rule-based strategy scores.

## Features

- **Broker selection:** Choose Questrade or IBKR before logging in. Questrade uses the browser OAuth authorization-code flow; IBKR uses a TWS/IB Gateway session through `ibapi`.
- **Account management:** Create, open, rename, and delete local trading accounts backed by SQLite.
- **Chart workspace:** Search symbols, fetch candles, switch chart intervals, and view candlestick/line-chart output through ChartForgeTK wrappers.
- **Stacked meta-learner strategy:** Train a gradient-boosted classifier from base strategy scores, regime features, ATR-scaled triple-barrier labels, purged/embargoed walk-forward validation, optional calibration, and a decision threshold.
- **Base strategies:** DMA crossover, EMA breakout, RSI, support/resistance structure, and VWAP breakout remain available as signal generators and as continuous score inputs to the meta-learner.
- **Backtesting and live trading:** Run the selected model through a shared engine with fixed-fraction position sizing, optional ATR stop loss, slippage, fees, lot-size controls, and short-selling disabled by default.
- **Persistence:** Store accounts, positions, trade sessions, and trade stream rows in `trading_app.db`; save trained ML artifacts under `artifacts/<version>/`.
- **Request logging:** Questrade REST calls can be logged and verified with the request/logging utilities.

## Directory Structure

```text
TradingBot/
├── Brokers/                       # Broker interface, factory, Questrade, and IBKR adapters
├── Data/                          # Portfolio, trade, and position dataclasses
├── ML_Classifier/
│   ├── stacked_meta_learner.py     # Current ML training/inference pipeline
│   └── ml_trading_persistence.py   # Model artifact save/load helpers
├── chartforgetk_wrapper.py         # ChartForgeTK integration helpers
├── log_verifier.py                 # Log checking and validation
├── log_writter.py                  # Request log writer
├── persistence.py                  # SQLite account/session/position storage
├── position_sizing.py              # Position sizing logic
├── request_wrapper.py              # Logged HTTP session wrapper
├── risk_control.py                 # Stop-loss and risk helpers
├── strategy_tree_builder.py        # Strategy picker/parameter UI widgets
├── tick_processor.py               # Tick-to-candle aggregation
├── tick_streamer.py                # Market data streaming helpers
├── tooltip_helper.py               # UI tooltip helpers
├── trading_app.py                  # Main GUI application
├── trading_engine.py               # Backtest/live execution engine
├── trading_indicators.py           # Technical indicator calculations
├── trading_strategies.py           # Rule strategies and meta-learner score adapters
├── requirements.txt                # Python dependencies
└── .env.example                    # Sample Questrade environment config
```

Generated runtime files such as `trading_app.db`, `artifacts/`, and `logs/` are created by the app and are not source modules.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/turtlebrain/TradingBot.git
   cd TradingBot
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

   On macOS/Linux, use `source venv/bin/activate`.

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure broker settings:

   ```bash
   copy .env.example .env
   ```

   For Questrade, set `QUESTRADE_API_CLIENT_ID` and `GROK_REDIRECT_URI`. The Questrade logger also expects `LOG_HMAC_KEY` to be present in the process environment before the broker is created.

   For IBKR, make sure TWS or IB Gateway is running and accepting API connections. The current adapter defaults to `127.0.0.1:7497` with client ID `1`.

## Getting Started

Launch the GUI:

```bash
python trading_app.py
```

Typical workflow:

1. Choose a broker on the opening screen.
2. Log in or connect the broker session.
3. Open or create an account.
4. Search for a symbol and load candle data.
5. Add one or more base strategies in the Strategy panel.
6. Train or load a stacked meta-learner model.
7. Configure execution settings, then run a backtest or live strategy.
8. Review equity, drawdown, returns, trade history, and saved sessions in the Performance view.

## Strategy and ML Workflow

The current strategy panel is centered on the stacked meta-learner. Base strategies are selected in the GUI and converted into continuous score features by `trading_strategies.py`. `ML_Classifier/stacked_meta_learner.py` adds regime features, builds ATR-scaled triple-barrier labels, trains a `HistGradientBoostingClassifier`, evaluates it with purged/embargoed walk-forward splits, and persists the trained model plus metadata.

Saved model versions are listed in the Strategy panel. During backtests and live runs, the loaded model produces `+1`, `-1`, or `0` signals through `meta_learner_signals` and the trading engine handles sizing, costs, stop losses, persistence, and account updates.

## Configuration

- Add or adjust broker adapters in `Brokers/` and register them in `Brokers/broker_factory.py`.
- Add new rule strategies or score functions in `trading_strategies.py`.
- Add or modify indicators in `trading_indicators.py`.
- Tune model parameters from the Strategy panel: horizon, ATR barriers, embargo, calibration, decision threshold, CV splits, learning rate, costs, and ATR window.
- Tune execution settings from the Execution panel: fixed-fraction allocation, optional ATR stop loss, slippage, fee rate, minimum fee, and lot size.

## Contributing

1. Fork the repository.
2. Make your changes in a new branch.
3. Ensure code is tested and follows project conventions.
4. Submit a pull request.

## Disclaimer

Algorithmic trading carries risks. Backtest thoroughly before trading live. The authors provide no guarantee of performance or profit.

## License

[N/A]

---

**Author:** turtlebrain  
**Status:** Active Development
