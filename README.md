# TradingBot

TradingBot is a Python-based algorithmic trading system designed to automate trading strategies using machine learning and customizable rule-based logic. It integrates with multiple brokers, supports real-time market data streaming, and includes tools for backtesting, risk management, and logging. The project features a graphical user interface and modular architecture for easy extension and customization.

## Features

- **Broker Integration**: Connects to brokers like Questrade (and others, via `Brokers/`)
- **Strategy Automation**: Build and evaluate trading strategies with rules and ML classifiers
- **Backtesting & Live Trading**: Test strategies on historical/real data
- **Risk Management**: Advanced position sizing and risk control
- **Persistence**: Store results, trades, and logs in a database
- **GUI**: User interface built with Tkinter and ttkbootstrap
- **Technical Indicators**: Includes libraries for common trading indicators

## Directory Structure

```
TradingBot/
├── Brokers/                  # Broker connectors and integrations
├── Data/                     # Market and backtesting data
├── ML_Classifier/            # Machine learning models/classifiers
├── chartforgetk_wrapper.py   # Chart rendering utilities
├── log_verifier.py           # Log checking and validation
├── log_writter.py            # Logging automation
├── persistence.py            # Database layer
├── position_sizing.py        # Position sizing logic
├── request_wrapper.py        # HTTP request tools
├── risk_control.py           # Risk management utilities
├── strategy_tree_builder.py  # Strategy building logic
├── strategy_tree_evaluator.py# Strategy evaluation logic
├── tick_processor.py         # Tick data processing
├── tick_streamer.py          # Market data streaming
├── tooltip_helper.py         # UI tooltip helpers
├── trading_app.py            # Main GUI application
├── trading_engine.py         # Core trading engine
├── trading_indicators.py     # Technical indicators
├── trading_strategies.py     # Trading strategies
├── requirements.txt          # Python dependencies
├── .env.example              # Sample environment config
├── .gitignore                # Git ignore rules
```

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/turtlebrain/TradingBot.git
   cd TradingBot
   ```

2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate           # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your broker credentials and settings
   ```

## Getting Started

To launch the application:

```bash
python trading_app.py
```

- Configure your trading strategy via the GUI
- Set up broker connection and credentials
- Choose between backtesting or live trading modes

## Usage

- **Strategy Building:** Use the GUI or code to create trading strategies via rules and indicators.
- **Backtesting:** Run tests on historical data from the `Data/` directory.
- **Live Trading:** Execute strategies in real-time with integrated broker APIs.

## Configuration

- Update `.env` for broker connection details and API keys.
- Add or modify strategies in `trading_strategies.py`.
- Extend indicators in `trading_indicators.py` or add new ML classifiers.

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
