import sqlite3
import pandas as pd

DB_FILE = "trading_app.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

def save_accounts(df_accounts):
    with get_connection() as conn:
        df_accounts.to_sql("accounts", conn, if_exists="replace", index=False)
        
def save_positions(df_positions):
    with get_connection() as conn:
        df_positions.to_sql("positions", conn, if_exists="replace", index=False)
        
def save_trades(df_trades):
    with get_connection() as conn:
        df_trades.to_sql("trades", conn, if_exists="replace", index=False)
        
def load_accounts():
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM accounts", conn)
    
def load_positions(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql("SELECT * FROM positions WHERE account_id = ?", conn, params=(account_id,))
        return pd.read_sql("SELECT * FROM positions", conn)

def load_trades(account_id=None):
    with get_connection() as conn:
        if account_id:
            return pd.read_sql("SELECT * FROM trades WHERE account_id = ?", conn, params=(account_id,))
        return pd.read_sql("SELECT * FROM trades", conn)