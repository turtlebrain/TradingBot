import sqlite3
import pandas as pd
import datetime

DB_FILE = "trading_app.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

# --- Schema Initialization ---
def init_db():
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
            UNIQUE(account_id, symbol)  -- enforce one row per symbol per account
        )
        """)

        # Trade sessions (one row per run)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_sessions (
            session_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id   INTEGER NOT NULL,
            started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at     TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(account_id)
        )
        """)

        # Trade streams (all rows of a run)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_streams (
            row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER NOT NULL,
            ts            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            price         REAL,
            signal        TEXT,
            shares        REAL,
            cash          REAL,
            equity        REAL,
            market_value  REAL,
            "order"       TEXT,
            exec_price    REAL,
            stop_loss     REAL,
            fees          REAL,
            trade_side    TEXT,
            pnl           REAL,
            cum_max_equity REAL,
            drawdown      REAL,
            returns       REAL,
            FOREIGN KEY(session_id) REFERENCES trade_sessions(session_id)
        )
        """)

        conn.commit()

# --- Account file i/o ---
def insert_account(name, capital):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO accounts (name, capital, last_opened) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (name, capital)
        )
        conn.commit()
        return cur.lastrowid  # new account_id

def update_account(account_id, **kwargs):
    """Update arbitrary fields on an account (e.g. last_opened, capital)."""
    if not kwargs:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        for col, val in kwargs.items():
            cur.execute(f"UPDATE accounts SET {col} = ? WHERE account_id = ?", (val, account_id))
        conn.commit()

def load_accounts():
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM accounts", conn, index_col="account_id")

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
  
# --- Trading file i/o --- 
def start_trade_session(account_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO trade_sessions (account_id) VALUES (?)", (account_id,))
        conn.commit()
        return cur.lastrowid

def end_trade_session(session_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE trade_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id=?", (session_id,))
        conn.commit()

def insert_trade_stream(session_id, df_stream):
    """
    Persist an entire DataFrame of trade stream rows for a session.
    df_stream must have columns matching col_headers.
    """
    with get_connection() as conn:
        df_stream.assign(session_id=session_id).to_sql(
            "trade_streams", conn, if_exists="append", index=False
        )

def load_trade_sessions(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql("SELECT * FROM trade_sessions WHERE account_id=?", conn,
                               params=(account_id,), index_col="session_id")
        return pd.read_sql("SELECT * FROM trade_sessions", conn, index_col="session_id")

def load_trade_stream(session_id):
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM trade_streams WHERE session_id=? ORDER BY row_id",
                           conn, params=(session_id,), index_col="row_id")

# --- Positions file i/o ---
def update_position(account_id, symbol, quantity, avg_price, current_price=None, pl=None):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO positions (account_id, symbol. quantity, avg_price, current_price, pl)
            VALUES (?, ?, ?, ?, ?, ?)
            ON_CONFLICT(account_id, symbol) DO UPDATE SET
                quantity = excluded.quantity,
                avg_price = excluded.avg_price,
                current_price, excluded.current_price,
                pl = excluded.pl
        """, (account_id, symbol, quantity, avg_price, current_price, pl))
        conn.commit()
        return cur.lastrowid


def load_positions(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql(
                "SELECT * FROM positions WHERE account_id = ?",
                conn, params=(account_id,), index_col="position_id"
            )
        return pd.read_sql("SELECT * FROM positions", conn, index_col="position_id")


# --- Bootstrap ---
def bootstrap_state():
    """Initialize schema and load DataFrames (empty if no data yet)."""
    init_db()
    df_accounts = load_accounts()
    df_positions = load_positions() if not df_accounts.empty else pd.DataFrame()
    df_trade_sessions = load_trade_sessions() if not df_accounts.empty else pd.DataFrame()
    return df_accounts, df_positions, df_trade_sessions