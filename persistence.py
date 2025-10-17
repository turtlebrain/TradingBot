import sqlite3
import pandas as pd
import datetime

DB_FILE = "trading_app.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

# --- Schema Initialization ---
def init_db():
    """Ensure the database file and tables exist with AUTOINCREMENT IDs."""
    with get_connection() as conn:
        cur = conn.cursor()

        # Accounts
        cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_opened  TIMESTAMP,
            capital      REAL NOT NULL
        )
        """)

        # Positions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    INTEGER NOT NULL,
            symbol        TEXT NOT NULL,
            quantity      REAL NOT NULL,
            avg_price     REAL NOT NULL,
            current_price REAL,
            pl            REAL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(account_id)
        )
        """)

        # Trades
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id     INTEGER NOT NULL,
            position_id    INTEGER,
            price          REAL NOT NULL,
            signal         TEXT,
            shares         REAL NOT NULL,
            cash           REAL,
            equity         REAL,
            "order"        TEXT,
            exec_price     REAL,
            stop_loss      REAL,
            fees           REAL,
            trade_side     TEXT CHECK(trade_side IN ('buy','sell')),
            pnl            REAL,
            cum_max_equity REAL,
            drawdown       REAL,
            returns        REAL,
            executed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(account_id),
            FOREIGN KEY(position_id) REFERENCES positions(position_id)
        )
        """)
        conn.commit()

# --- Insert Functions ---
def insert_account(name, capital):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO accounts (name, capital, last_opened) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (name, capital)
        )
        conn.commit()
        return cur.lastrowid  # new account_id

def insert_position(account_id, symbol, quantity, avg_price, current_price=None, pl=None):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO positions (account_id, symbol, quantity, avg_price, current_price, pl)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, symbol, quantity, avg_price, current_price, pl)
        )
        conn.commit()
        return cur.lastrowid  # new position_id

def insert_trade(account_id, position_id, price, signal, shares, trade_side,
                 cash=None, equity=None, order=None, exec_price=None,
                 stop_loss=None, fees=0.0, pnl=None, cum_max_equity=None,
                 drawdown=None, returns=None):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO trades
               (account_id, position_id, price, signal, shares, trade_side,
                cash, equity, "order", exec_price, stop_loss, fees, pnl,
                cum_max_equity, drawdown, returns)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, position_id, price, signal, shares, trade_side,
             cash, equity, order, exec_price, stop_loss, fees, pnl,
             cum_max_equity, drawdown, returns)
        )
        conn.commit()
        return cur.lastrowid  # new trade_id

# --- Update Functions ---
def update_account(account_id, **kwargs):
    """Update arbitrary fields on an account (e.g. last_opened, capital)."""
    if not kwargs:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        for col, val in kwargs.items():
            cur.execute(f"UPDATE accounts SET {col} = ? WHERE account_id = ?", (val, account_id))
        conn.commit()

def update_position(position_id, **kwargs):
    """Update arbitrary fields on a position (e.g. current_price, pl)."""
    if not kwargs:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        for col, val in kwargs.items():
            cur.execute(f"UPDATE positions SET {col} = ? WHERE position_id = ?", (val, position_id))
        conn.commit()

# --- Load Functions ---
def load_accounts():
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM accounts", conn, index_col="account_id")

def load_positions(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql(
                "SELECT * FROM positions WHERE account_id = ?",
                conn, params=(account_id,), index_col="position_id"
            )
        return pd.read_sql("SELECT * FROM positions", conn, index_col="position_id")

def load_trades(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql(
                "SELECT * FROM trades WHERE account_id = ?",
                conn, params=(account_id,), index_col="trade_id"
            )
        return pd.read_sql("SELECT * FROM trades", conn, index_col="trade_id")

# --- Accounts Manager ---
def create_account(name, capital):
    account_id = insert_account(name, capital)
    return load_accounts().loc[account_id]

def open_account(account_id):
    update_account(account_id, last_opened=datetime.datetime.now(datetime.timezone.utc))
    return load_accounts().loc[account_id]

def rename_account(account_id, new_name):
    update_account(account_id, name=new_name)
    return load_accounts().loc[account_id]

def delete_account(account_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
        conn.commit()
    return load_accounts()

# --- Bootstrap ---
def bootstrap_state():
    """Initialize schema and load DataFrames (empty if no data yet)."""
    init_db()
    df_accounts = load_accounts()
    df_positions = load_positions() if not df_accounts.empty else pd.DataFrame()
    df_trades = load_trades() if not df_accounts.empty else pd.DataFrame()
    return df_accounts, df_positions, df_trades