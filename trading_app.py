import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import api_requests as qt_api
import json
import ttkbootstrap as ttkb
from ttkbootstrap.widgets import DateEntry
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
import trading_strategies as strategies
import pandas as pd
import tkinter.font as tkFont
import position_sizing as pos_sz
import risk_control as risk
import trading_engine as engine
import requests 
import chartforgetk_wrapper as cftk_wrap
import time
import datetime
import threading
import tick_streamer as qt_stream
import strategy_tree_builder as stb
import persistence as persist
import tick_processor
import queue


class TradingBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TradingBot")
        self.root.geometry("1496x842")
        self.system_running = False

        # Initialize database
        persist.init_db()
        
        # Change default font for all widgets to Poppins
        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family="Poppins")

        # --- Container with 2 rows: nav bar (row 0), content frames (row 1) ---
        container = ttk.Frame(root)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(1, weight=1)   # row 1 expands
        container.grid_columnconfigure(0, weight=1)

        # --- Nav bar (row 0), hidden until after_auth() ---
        self.nav_frame = ttk.Frame(container)
        self.nav_frame.grid(row=0, column=0, sticky="ew")
        self.nav_frame.grid_remove()  # hide initially

        self.nav_buttons = {}

        # --- Content area (row 1) ---
        self.frames = {}
        for F in (LoginFrame, AuthFrame, AccountManagerFrame, TradingStrategyFrame, BackTestingResultsFrame):
            frame = F(parent=container, controller=self)
            self.frames[F] = frame
            frame.grid(row=1, column=0, sticky="nsew")

        # Start at login
        self.show_frame(LoginFrame)
     
    def show_frame(self, frame_calss):
        frame = self.frames[frame_calss]
        frame.tkraise() 
    
    def show_main_frame(self, frame_class, name):
        """Show one of the main frames and update nav button styles."""
        self.show_frame(frame_class)
        # Update nav button styles
        for btn_name, btn in self.nav_buttons.items():
            if btn_name == name:
                btn.configure(bootstyle="primary-toolbutton")  # active
            else:
                btn.configure(bootstyle="primary-outline-toolbutton")  # inactive
    
    def after_auth(self):
        """Call this once AuthFrame succeeds."""
        # Build nav buttons once
        if not self.nav_buttons:
            # Configure nav_frame to use grid with 3 equal columns
            self.nav_frame.columnconfigure(0, weight=1)
            self.nav_frame.columnconfigure(1, weight=1)
            self.nav_frame.columnconfigure(2, weight=1)

            self.nav_buttons["accounts"] = ttk.Button(
                self.nav_frame, text="Accounts",
                bootstyle="primary-outline-toolbutton",
                command=lambda: self.show_main_frame(AccountManagerFrame, "accounts")
            )
            self.nav_buttons["accounts"].grid(row=0, column=0, sticky="ew", padx=2, pady=2)

            self.nav_buttons["trading"] = ttk.Button(
                self.nav_frame, text="Trading",
                bootstyle="primary-outline-toolbutton",
                command=lambda: self.show_main_frame(TradingStrategyFrame, "trading")
            )
            self.nav_buttons["trading"].grid(row=0, column=1, sticky="ew", padx=2, pady=2)

            self.nav_buttons["performance"] = ttk.Button(
                self.nav_frame, text="Performance",
                bootstyle="primary-outline-toolbutton",
                command=lambda: self.show_main_frame(BackTestingResultsFrame, "performance")
            )
            self.nav_buttons["performance"].grid(row=0, column=2, sticky="ew", padx=2, pady=2)

        # Show nav bar
        self.nav_frame.grid()  # make it visible
        # Default to Accounts view
        self.show_main_frame(AccountManagerFrame, "accounts")

    def create_tab(self, notebook, title, frame_factory):
        tab_frame = ttk.Frame(notebook, padding=10)
        notebook.add(tab_frame, text=title)
        collapsible = frame_factory(tab_frame)
        collapsible.pack(side='left', fill='y')
        return collapsible
    
    def add_outer_rows_and_cols(self, frame: ttk.Frame):
        cols, rows = frame.grid_size()
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(cols+1, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_rowconfigure(rows+1, weight=1)         
        
    def on_close(self):
        self.running = False
        # Gracefully end trade live trading and finalize dataframe, and finally stop stream and persist sessions
        qt_api.log.end_session()
        self.root.quit()
        self.root.destroy()
            
class LoginFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.login_button = ttk.Button(self, width=50, text="Log in", command=self.login)
        self.login_button.place(relx=0.5, rely=0.5, anchor="center")
        self.pack_propagate(False)
    
    def login(self):
        auth_url = qt_api.build_auth_url()
        try:
            webbrowser.open(auth_url)
        except:
            pass
        messagebox.showinfo("Login", f"After logging in, you'll be redirected to: {qt_api.REDIRECT_URI}?code=YOUR_CODE_HERE")
        self.controller.show_frame(AuthFrame)
        
class AuthFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.code_label = ttk.Label(self, width=10, text="Enter code:")
        self.code_label.grid(row=1, column=1, padx=2, pady=2, sticky="we")
        self.code_entry = ttk.Entry(self, width=30)
        self.code_entry.grid(row=1, column=2, padx=2, pady=2, sticky="we")
        self.auth_button = ttk.Button(self, text="Authenticate", width=50, command=self.authenticate)
        self.auth_button.grid(row=2, column=1, columnspan=2, padx=2, pady=2)
        self.controller.add_outer_rows_and_cols(self)
        self.refresh_token = None
        self.access_token = None
        self.api_server = None
        self.expiry_time = None
        self.thread = None
        self.lock = threading.Lock()
        
    def authenticate(self):
        code = self.code_entry.get().strip()
        if not code:
            messagebox.showwarning("Input Error", "No code provided.")
            return
        token_data = qt_api.exchange_code_for_tokens(code)
        messagebox.showinfo("Tokens", f"Received tokens: {json.dumps(token_data, indent=2)}")
        self.api_server = token_data.get('api_server', '')   
        self.access_token = token_data.get('access_token', '')
        self.refresh_token = token_data.get('refresh_token', '')
        self.expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=token_data.get('expires_in', 0))
        if self.api_server and self.access_token:
            # Start background thread for auto-refresh
            self.thread = threading.Thread(target=self.auto_refresh_tokens, daemon=True)
            self.thread.start()
        self.controller.after_auth()
        
    def auto_refresh_tokens(self):
        while True:
            with self.lock:
                if self.expiry_time:
                    # Refresh 2 minutes before expiry
                    time_to_wait = max(0,(self.expiry_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds() - 120)
                else:
                    time_to_wait = 60 # Default wait time if expiry unknown
            
            time.sleep(time_to_wait)
            try:
                refresh_token_data = qt_api.refresh_access_token(self.refresh_token)
                self.api_server = refresh_token_data.get('api_server', '')   
                self.access_token = refresh_token_data.get('access_token', '')
                self.refresh_token = refresh_token_data.get('refresh_token', '')  
                streamer = self.controller.frames[TradingStrategyFrame].chart_frame.streamer 
                if streamer:
                    streamer.access_token = self.access_token
                    streamer.api_server = self.api_server
                    streamer.reconnect()
                    print("Access token refreshed successfully")

                self.expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                    seconds=refresh_token_data.get("expires_in", 0)
                )
                
            except Exception as e:
                print("Failed to refresh token:", e)
                time.sleep(30)


class AccountManagerFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.accounts = persist.load_accounts()
        
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.render_accounts()
        
        ttk.Button(self, text="➕ New Account", width=25, bootstyle=SUCCESS, command=self.create_account).pack(pady=10)
    
    def render_accounts(self):
        for widget in self.list_frame.winfo_children():
            widget.destroy()

        if self.accounts.empty:
            ttk.Label(self.list_frame, text="No accounts yet. Create one to get started.").pack()
            return

        for account_id, meta in self.accounts.iterrows():
            row = ttk.Frame(self.list_frame, bootstyle="light")  
            row.pack(fill="x", pady=2, padx=5, ipady=5, ipadx=5)

            # Bind click to row and all children
            row.bind("<Button-1>", lambda e, n = account_id: self.open_account(n))
        
            # Create widgets
            name_lbl = ttk.Label(row, text=meta["name"], font=("Poppins", 12, "bold"))
            created_lbl = ttk.Label(row, text=f"Created: {meta['date_created']}", foreground="gray")
            opened_lbl = ttk.Label(row, text=f"Last opened: {meta['last_opened']}", foreground="gray")
            rename_btn = ttk.Button(row, text="Rename", width = 8, bootstyle=INFO, command=lambda n=meta.name: self.rename_account(n))
            delete_btn = ttk.Button(row, text="Delete", width = 8, bootstyle=DANGER, command=lambda n=meta.name: self.delete_account(n))

            name_lbl.pack(side="left")
            created_lbl.pack(side="left", padx=10)
            opened_lbl.pack(side="left", padx=10)
            delete_btn.pack(side="right", padx=2)
            rename_btn.pack(side="right", padx=2)

            # Bind click to labels too
            for widget in [name_lbl, created_lbl, opened_lbl]:
                widget.bind("<Button-1>", lambda e, n = account_id: self.open_account(n))
            
    def on_open_trading_view(self, meta):
        """
        Open the trading view for the given account metadata.
        Sets the active account, refreshes account info, clears charts,
        and reloads positions/backtest data.
        """
        # Get references to frames
        trading_frame = self.controller.frames[TradingStrategyFrame]
        backtest_frame = self.controller.frames[BackTestingResultsFrame]

        # --- Activate account and refresh account info ---
        trading_frame.set_active_account(meta)
        trading_frame.update_account_info()

        # --- Clear and refresh trading chart + positions ---
        trading_frame.chart_frame.candle_chart.clear()
        trading_frame.render_positions_table()

        # --- Clear and refresh backtesting results ---
        backtest_frame.results_chart.chart.clear()
        backtest_frame.clear_backtest_display()
        backtest_frame.render_trade_history()

        # --- Show trading frame ---
        self.controller.show_main_frame(TradingStrategyFrame, "trading")

        
    def create_account(self):
        dialog = AccountDialog(self)
        self.wait_window(dialog.top)

        if dialog.result:
            name, capital = dialog.result
            if not self.accounts.empty and name in self.accounts["name"].values:
                messagebox.showerror("Error", f"Account '{name}' already exists.")
                return

            meta = persist.create_account(name, capital)   # persistence handles insert + reload
            self.accounts = persist.load_accounts()
            self.render_accounts()
            self.on_open_trading_view(meta)

    def open_account(self, account_id):
        meta = persist.open_account(account_id)            # persistence handles update + reload
        self.accounts = persist.load_accounts()
        self.on_open_trading_view(meta)

    def rename_account(self, account_id):
        new_name = simpledialog.askstring("Rename Account", "Enter new name:")
        if new_name and new_name not in self.accounts["name"].values:
            meta = persist.rename_account(account_id, new_name)
            self.accounts = persist.load_accounts()
            self.render_accounts()

    def delete_account(self, account_id):
        if messagebox.askyesno("Delete Account", f"Delete {self.accounts.loc[account_id, 'name']}?"):
            self.accounts = persist.delete_account(account_id)  # persistence handles delete + reload
            self.render_accounts()
        
class AccountDialog:
    def __init__(self, parent):
        top = self.top = tk.Toplevel(parent)
        top.title("New Account")

        ttk.Label(top, text="Account Name:").pack(pady=5)
        self.name_entry = ttk.Entry(top)
        self.name_entry.pack(padx=5, pady=5)

        ttk.Label(top, text="Starting Capital:").pack(pady=5)
        self.capital_entry = ttk.Entry(top)
        self.capital_entry.pack(padx=5, pady=5)

        ttk.Button(top, text="Create", command=self.on_ok, bootstyle=SUCCESS).pack(padx=10, pady=10)

        self.result = None

    def on_ok(self):
        name = self.name_entry.get().strip()
        try:
            capital = float(self.capital_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for capital.")
            return
        if not name:
            messagebox.showerror("Error", "Account name cannot be empty.")
            return
        self.result = (name, capital)
        self.top.destroy()


class TabbedWorkspaceFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # Workspace area (row 0)
        self.workspace_area = ttk.Frame(self)
        self.workspace_area.grid(row=0, column=0, sticky="nsew")
        self.workspace_area.grid_rowconfigure(0, weight=1)
        self.workspace_area.grid_columnconfigure(0, weight=1)

        # Tab bar (row 1)
        self.tab_bar = ttk.Frame(self)
        self.tab_bar.grid(row=1, column=0, sticky="ew", pady=4)

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        self.workspaces = []
        self.active_workspace = None

        self.add_workspace_tab()

    def _create_tab_widget(self, title, closable=True):
        tab = ttk.Frame(self.tab_bar)
        tab.pack(side="left", padx=2, pady=2)

        lbl = ttk.Label(tab, text=title, width=6, anchor="center")
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e, t=tab: self.select_workspace(t))

        if closable:
            btn = ttk.Button(tab, text="✖", width=2, bootstyle=DANGER,
                             command=lambda t=tab: self.close_workspace(t))
            btn.pack(side="right")

        return tab

    def add_workspace_tab(self):
        idx = len(self.workspaces) + 1
        label = f"🗂{idx}"
        closable = idx > 1

        # Each workspace = sidebar + chart
        workspace = ttk.Frame(self.workspace_area)
        workspace.grid(row=0, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=0)
        workspace.columnconfigure(1, weight=1)
        workspace.rowconfigure(0, weight=1)

        # Sidebar Notebook
        notebook = ttk.Notebook(workspace, style="TNotebook")
        notebook.grid(row=0, column=0, sticky="ns")

        self.controller.create_tab(
            notebook, "General",
            lambda parent: GeneralInfoCollapsibleFrame(parent, self.controller)
        )
        self.controller.create_tab(
            notebook, "Strategy",
            lambda parent: StrategyCollapsibleFrame(parent)
        )
        self.controller.create_tab(
            notebook, "Execution", ExecutionCollasibleFrame
        )

        # Chart
        chart = CandlestickChartFrame(workspace, self.controller)
        chart.grid(row=0, column=1, sticky="nsew")

        tab_widget = self._create_tab_widget(label, closable)
        self.workspaces.append((workspace, tab_widget))

        self.select_workspace(tab_widget)
        self._refresh_plus_button()

    def _refresh_plus_button(self):
        for child in self.tab_bar.winfo_children():
            if getattr(child, "is_plus", False):
                child.destroy()

        plus = ttk.Button(self.tab_bar, text="➕", width=2, bootstyle=SUCCESS,
                          command=self.add_workspace_tab)
        plus.is_plus = True
        plus.pack(side="left", padx=2)

    def select_workspace(self, tab_widget):
        for workspace, tab in self.workspaces:
            if tab is tab_widget:
                workspace.tkraise()
                self.active_workspace = workspace
                tab.configure(style="Selected.TFrame")
            else:
                tab.configure(style="TFrame")

    def close_workspace(self, tab_widget):
        if len(self.workspaces) <= 1:
            print("At least one workspace must remain.")
            return

        for i, (workspace, tab) in enumerate(self.workspaces):
            if tab is tab_widget:
                workspace.destroy()
                tab.destroy()
                del self.workspaces[i]
                break

        if self.workspaces:
            self.select_workspace(self.workspaces[-1][1])

 
class TradingStrategyFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.active_account = None

        # --- Cash variable (defaults to 10,000) ---
        self.cash_var = tk.DoubleVar(value=10000.0)

        # Shared grid: 2 columns across the whole frame
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=3)
        self.rowconfigure(1, weight=1)

        # --- Top row: tabbed workspaces ---
        self.top_tabs = TabbedWorkspaceFrame(self, controller)
        self.top_tabs.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # --- Bottom row: account info + positions ---
        account_group = ttkb.LabelFrame(self, text="Account Info", bootstyle="info")
        account_group.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        # Label bound to cash_var
        self.pnl_var = tk.StringVar(value=f"${self.cash_var.get():,.2f} Cash")
        pnl_label = ttk.Label(
            account_group,
            textvariable=self.pnl_var,
            bootstyle="info",
            font=("Helvetica", 16, "bold")
        )
        pnl_label.pack(pady=(10, 5))

        # Meter (values updated in update_account_info)
        self.pnl_meter = ttkb.Meter(
            master=account_group,
            metersize=200,
            amountused=0,
            amounttotal=1,
            metertype="semi",
            bootstyle="secondary",
            subtext="N/A"
        )
        self.pnl_meter.pack(pady=10)

        # Positions container (unchanged)
        positions_container = ttk.Frame(self)
        positions_container.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        positions_container.columnconfigure(0, weight=1)
        positions_container.rowconfigure(0, weight=1)
        positions_container.rowconfigure(1, weight=0)

        table_frame = ttk.Frame(positions_container)
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        cols = ("Symbol", "Quantity", "Avg Price", "Current Price", "P/L")
        self.positions_table = ttk.Treeview(
            table_frame, columns=cols, show="headings", height=8
        )
        for col in cols:
            self.positions_table.heading(col, text=col)
            self.positions_table.column(col, anchor="center", width=100)
        self.positions_table.grid(row=0, column=0, sticky="nsew")

        self.scrollbar = ttk.Scrollbar(table_frame, command=self.positions_table.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.positions_table["yscrollcommand"] = self.scrollbar.set

        self.run_strategy_button = ttkb.Button(
            self, width=50, text="Run Strategy",
            command=self.run_strategy, bootstyle="primary"
        )
        self.run_strategy_button.grid(row=2, column=0, columnspan=2, padx=2, pady=5)

        # Initialize account info
        self.update_account_info()


    def update_account_info(self):
        """
        Refresh Account Info panel:
        - Label shows cash_var
        - Meter shows P&L relative to equity
        """
        active_acc = self.active_account

        # Load positions if account is active
        if active_acc is not None:
            acc_id = int(active_acc.name)
            positions = persist.load_positions(acc_id)
            pnl_value = positions["pl"].sum()
        else:
            pnl_value = 0

        cash_value = self.cash_var.get()
        final_equity = cash_value + pnl_value

        # Update label
        self.pnl_var.set(f"${cash_value:,.2f} Cash")

        # Update meter
        amountused = abs(pnl_value)
        amounttotal = abs(final_equity) if final_equity != 0 else 1

        self.pnl_meter.configure(
            amountused=min(amountused, amounttotal),
            amounttotal=amounttotal,
            bootstyle="success" if pnl_value >= 0 else "danger",
            subtext="Profit" if pnl_value >= 0 else (
                "Loss" if amountused <= amounttotal else "Overdrawn"
            )
        )
    
    def set_active_account(self, account_meta):
        """
        Set the active account. If valid, update cash_var from metadata.
        Otherwise, default to 10,000.
        """
        if account_meta is not None and not account_meta.empty:
            self.active_account = account_meta
            self.cash_var.set(float(account_meta.get("cash", 10000)))
        else:
            self.active_account = None
            self.cash_var.set(10000.0)

        # Refresh account info panel
        self.update_account_info()
         
    def render_positions_table(self):
        """
        Render the positions DataFrame into the given ttk.Treeview.
        Expects df to have columns: Symbol, Quantity, Avg Price, Current Price, P/L
        """
        # Clear existing rows
        for row in self.positions_table.get_children():
            self.positions_table.delete(row)

        # Only render if an account is active
        active_acc = self.active_account
        if active_acc is None:
            return

        acc_id = int(active_acc.name)  # account_id is the Series.name
        positions = persist.load_positions(acc_id)
        if positions.empty:
            return

        # Insert updated rows
        for _, row in positions.iterrows():
            self.positions_table.insert(
                "",
                "end",
                values=(
                    row["symbol"],
                    int(row["quantity"]),
                    f"{row['avg_price']:.2f}",
                    f"{row['current_price']:.2f}",
                    f"{row['pl']:.2f}"
                )
            )

                     
    def search(self, show_output=True):  
        stock_symbol = self.general_tab.stock_input.get().strip() 
        start_date = self.general_tab.start_date_input.get_date().isoformat()
        end_date = self.general_tab.end_date_input.get_date().isoformat()
        if not stock_symbol or not start_date or not end_date:
            messagebox.showwarning("Input Error", "Please enter a valid stock symbol as query.")
            return
        # API Search
        my_access_token = self.controller.frames[AuthFrame].access_token
        my_api_server = self.controller.frames[AuthFrame].api_server  
        if not my_access_token and not my_api_server:
            print("No access token found, please log in and authenticate first")
            return   
        try:   
            symbol_data = qt_api.get_stock_data(access_token=my_access_token, api_server=my_api_server, symbol_str=stock_symbol)
            if not symbol_data:
                print("No data found for:", stock_symbol)
                return
            symbol_id = symbol_data[0]['symbolId']
            chart_frame = self.chart_frame
            candle_data = qt_api.get_candles_paginated(
                access_token=my_access_token, 
                api_server=my_api_server, 
                symbol_id=symbol_id, 
                start_date=self.general_tab.start_date_input.get_date(), 
                end_date=self.general_tab.end_date_input.get_date(),
                interval= chart_frame.time_interval
            )
            candle_data_pd = pd.DataFrame(candle_data)
            if show_output:
                # Plot candlestick chart
                chart_frame.update_chart(candle_data_pd)
            return candle_data
        except requests.exceptions.HTTPError as err:
            messagebox.showerror("Error", f"HTTP error occurered {err}")           

    
    def is_input_valid_float(self, input, name):
        try:
            float(input)
            return True
        except ValueError:
            messagebox.showerror("Error", f"Please enter a valid {name}")
            return False

    
    def run_strategy(self):
        if self.chart_frame.live_switch_var.get():
            # --- LIVE MODE ---
            if not hasattr(self, "_live_running") or not self._live_running:
                acc_id = int(self.active_account.name)
                # Start live strategy
                session_id = persist.start_trade_session(acc_id, "live")
                self.current_session_id = session_id

                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.backtest_results = pd.DataFrame()

                def _on_live_update(trade_df: pd.DataFrame):
                    if backtest_frame.backtest_results.empty:
                        backtest_frame.backtest_results = trade_df.copy()
                    else:
                        backtest_frame.backtest_results = pd.concat(
                            [backtest_frame.backtest_results, trade_df]
                        )
                    backtest_frame.results_chart.results = backtest_frame.backtest_results
                    backtest_frame.results_chart.update_chart()
                    backtest_frame.render_trade_history()
                    self.render_positions_table()

                self._finalize_live = engine.run_live_strategy(
                    candle_source=self.chart_frame.candle_aggregator,
                    buy_logic=self.strategy_tab.buy_section,
                    sell_logic=self.strategy_tab.sell_section,
                    position_sizer_func=pos_sz.fixed_fraction_position_sizer,
                    position_sizer_param=float(self.execution_tab.position_slider_value.get()),
                    stop_loss_func=risk.StopLoss.average_true_range_stop if self.execution_tab.stop_loss_var.get() else None,
                    starting_capital=float(self.execution_tab.cash_var.get()),
                    allow_short=False,
                    slippage=float(self.execution_tab.slippage_input.get().strip()),
                    fee_rate=float(self.execution_tab.fee_rate_input.get().strip()),
                    fee_min=float(self.execution_tab.minimum_fee_input.get().strip()),
                    lot_size=int(self.execution_tab.lot_size_input.get().strip()),
                    account_id = acc_id,
                    session_id=session_id,
                    ui_callback=_on_live_update,
                )

                self._live_running = True
                self.run_strategy_button.config(text="Stop Strategy")

            else:
                # Stop live strategy
                acc_id = int(self.active_account.name)
                final_df = self._finalize_live()
                persist.end_trade_session(session_id=self.current_session_id)

                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.backtest_results = final_df
                backtest_frame.results_chart.results = final_df
                backtest_frame.results_chart.update_chart()
                backtest_frame.render_trade_history()
                last_cash = float(final_df["cash"].iloc[-1])
                self.execution_tab.cash_var.set(last_cash)
                persist.update_account(account_id=acc_id, cash=last_cash)
                self._live_running = False
                self.run_strategy_button.config(text="Run Strategy")
                del self._finalize_live

        else:
            # --- BACKTEST MODE ---
            acc_id = int(self.active_account.name)
            session_id = persist.start_trade_session(acc_id, "backtest")
            candle_data = pd.DataFrame(self.search(show_output=False))
            backtest_results = engine.backtest_strategy(
                data=candle_data,
                buy_logic=self.strategy_tab.buy_section,
                sell_logic=self.strategy_tab.sell_section,
                position_sizer_func=pos_sz.fixed_fraction_position_sizer,
                position_sizer_param=float(self.execution_tab.position_slider_value.get()),
                stop_loss_func=risk.StopLoss.average_true_range_stop if self.execution_tab.stop_loss_var.get() else None,
                starting_capital=float(self.execution_tab.cash_var.get()),
                allow_short=False,
                slippage=float(self.execution_tab.slippage_input.get().strip()),
                fee_rate=float(self.execution_tab.fee_rate_input.get().strip()),
                fee_min=float(self.execution_tab.minimum_fee_input.get().strip()),
                lot_size=int(self.execution_tab.lot_size_input.get().strip()),
                session_id=session_id,
            )
            if not backtest_results.empty:
                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.backtest_results = backtest_results
                backtest_frame.populate_backtest_display(backtest_results)
                backtest_frame.results_chart.results = backtest_results
                backtest_frame.results_chart.update_chart()
                backtest_frame.render_trade_history()
            persist.end_trade_session(session_id=session_id)
   
class CandlestickChartFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.live_switch_var = tk.BooleanVar(value=False)  
        self.live_switch = ttkb.Checkbutton(
            self, 
            text="Live mode", 
            variable=self.live_switch_var, 
            command=self.toggle_live_mode, 
            bootstyle="success-round-toggle"
        )
        self.live_switch.grid(row=0, column=0, sticky="nsew")
        
        self.show_label_var = tk.BooleanVar(value=False)  # OFF by default
        self.show_label_toggle = ttk.Checkbutton(
            self, 
            text="Show data labels", 
            variable=self.show_label_var, 
            command=self.toggle_show_label, 
            onvalue=True, 
            offvalue=False
        )
        self.show_label_toggle.grid(row=0, column=1, sticky="nsew")
        
        self.candle_chart = cftk_wrap.CandlestickChartNoLabels(self, width = 880, height = 495)
        self.candle_chart.grid(row=1, column=0, columnspan=4, sticky="nsew")
        
        self.timeframe_options = ["OneHour", "OneDay", "OneWeek", "OneMonth"]
        self.time_interval = "OneDay"
        control_frame = ttk.Frame(self)
        control_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=5)
        control_frame.grid_rowconfigure(0, weight=0)
        for i in range(len(self.timeframe_options)):
            control_frame.grid_columnconfigure(i, weight=1)
            self.grid_columnconfigure(i, weight=1)
            
        self.timeframe_buttons = self.create_segmented_control(
            control_frame, self.timeframe_options, self.on_timeframe_change
        )
        self.grid_rowconfigure(1, weight=1)
        
        self.tick_queue = None
        self.streamer = None
        self.candle_aggregator = None
        self._poll_job = None
    
    def toggle_live_mode(self):
        if self.live_switch_var.get(): 
            self.tick_queue = queue.Queue()
            auth_frame = self.controller.frames[AuthFrame]
            self.streamer = qt_stream.QuestradeStreamer(
                access_token = auth_frame.access_token,
                api_server = auth_frame.api_server,
                tick_queue = self.tick_queue
            )
            stock_symbol = self.controller.frames[TradingStrategyFrame].general_tab.stock_input.get().strip()
            self.candle_aggregator = tick_processor.CandleAggregator(stock_symbol, "OneMinute")             
            symbol_data = qt_api.get_stock_data(
                access_token=auth_frame.access_token,
                api_server=auth_frame.api_server, 
                symbol_str=stock_symbol
            )
            symbol_id = symbol_data[0]['symbolId']
            for rb in self.timeframe_control:
                rb.config(state=tk.DISABLED)
            self.streamer.start_stream(symbol_id)
            self._poll_ticks()
            self.periodically_update_chart()
        else:
            if self.streamer:
                self.streamer.stop_stream()
            if self._poll_job:
                root.after_cancel(self._poll_job)
                self._poll_job = None
            self.tick_queue = None
            for rb in self.timeframe_control:
                rb.config(state=tk.NORMAL)
    
    def _poll_ticks(self):
        try:
            while True:
                tick = self.tick_queue.get_nowait()
                self.candle_aggregator.update(tick)
        except queue.Empty:
            pass
        if self.live_switch_var.get():
            self._poll_job = root.after(100, self._poll_ticks)
        
    def toggle_show_label(self):
        if self.show_label_var.get(): 
            self.candle_chart.show_labels = True
        else:
            self.candle_chart.show_labels = False
        self.candle_chart.redraw()
            
    def convert_data_for_chart(self, df):
        # Ensure index is reset so we can enumerate
        df = df.reset_index(drop=True)
        # Create list of tuples: (index, open, high, low, close)
        return [
            (i, float(row['open']), float(row['high']), float(row['low']), float(row['close']))
            for i, row in df.iterrows()
        ]
    
    def update_chart(self, df, animate_last_only = False):
        self.candle_chart.clear()
        self.candle_chart.plot(self.convert_data_for_chart(df), 
                               self.controller.frames[TradingStrategyFrame].general_tab.stock_input.get().strip(), animate_last_only)
        
    def periodically_update_chart(self):
        candles_df = self.candle_aggregator.get_candles()
        if not candles_df.empty and self.live_switch_var.get():
            self.update_chart(candles_df, True)
        root.after(3000, self.periodically_update_chart)  # Update every 3 seconds     
               
    def create_segmented_control(self, parent, options, command=None):
        sg_var = tk.StringVar(value=options[1])
        style = ttk.Style()
        style.configure("Segmented.TRadiobutton", indicatoron=0, relief="raised")
        style.map("Segmented.TRadiobutton", relief=[("selected", "sunken")])

        buttons = []
        for i, option in enumerate(options):
            rb = ttk.Radiobutton(
                parent,
                text=option,
                value=option,
                variable=sg_var,
                command=lambda opt=option: command(opt) if command else None,
                style="Segmented.TRadiobutton"
            )
            rb.grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
            parent.columnconfigure(i, weight=1)
            buttons.append(rb)
        return buttons
    
    def _on_select(self):
        if self.sg_command:
            self.sg_command(self.sg_var.get())
       
    def on_timeframe_change(self, value):
        self.time_interval = value
        trading_frame = self.controller.frames[TradingStrategyFrame]
        trading_frame.search(show_output=True)       
                           
class BackTestingResultsFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.backtest_results = pd.DataFrame()
        
        self.result_headers = [
            'price', 'signal', 'shares', 'cash', 'equity', 'market_value',
            'order', 'exec_price', 'stop_loss', 'fees', 'trade_side', 'pnl',
            'cum_max_equity', 'drawdown', 'returns'
        ]

        # --- Layout config ---
        self.columnconfigure(0, weight=0)   # sidebar fixed width
        self.columnconfigure(1, weight=1)   # main area expands
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        
        # --- Result Settings Tab ---
        notebook = ttk.Notebook(self, style="TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")  
          
        self.result_settings_tab = self.controller.create_tab(notebook, "Result Settings", 
                                   lambda parent: ResultSettingsCollapsibleFrame(parent, self.controller, self.result_headers))
        
        # --- Trade Session History Panel ---
        self.ts_history_frame = tk.Frame(self)
        self.ts_history_frame.grid(row=1, column=0, sticky="ns")
        self.trade_history = ScrolledFrame(self.ts_history_frame, autohide=True, bootstyle="round")
        self.trade_history.pack(fill="y", expand=True)  
        self.render_trade_history()
        
        # --- Main area ---
        main_area = tk.Frame(self, bg="white")
        main_area.grid(row=0, column=1, rowspan = 2, sticky="nsew")
        main_area.grid_columnconfigure(0, weight=1)
        main_area.grid_rowconfigure(1, weight=1)

        # Chart area
        self.results_chart = ResultChartFrame(main_area, controller, self.backtest_results, self.result_settings_tab.result_var)
        self.results_chart.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        # Treeview
        self.backtest_display = ttk.Treeview(main_area, columns=self.result_headers, show="headings")
        self.backtest_display.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")
        self.populate_backtest_display(self.backtest_results, self.result_headers)

        # Scrollbars
        self.scroll_y = ttk.Scrollbar(main_area, orient=tk.VERTICAL, command=self.backtest_display.yview)
        self.scroll_y.grid(row=2, column=1, sticky='ns')
        self.scroll_x = ttk.Scrollbar(main_area, orient=tk.HORIZONTAL, command=self.backtest_display.xview)
        self.scroll_x.grid(row=3, column=0, sticky='ew')

        self.backtest_display.configure(yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set)

        # Let the Treeview expand
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.controller.add_outer_rows_and_cols(main_area)
    
    def populate_backtest_display(self, dataframe, result_headers = None):
        self.clear_backtest_display()

        if self.result_headers:
            result_headers = self.result_headers
        self.backtest_display["columns"] = result_headers
        for col in result_headers:
            self.backtest_display.heading(col, text=col)
            self.backtest_display.column(col, anchor="center")

        for _, row in dataframe.iterrows():
            values = [row[header] for header in result_headers if header in dataframe.columns]
            self.backtest_display.insert("", "end", values=values)

            
    def clear_backtest_display(self):
        for row in self.backtest_display.get_children():
            self.backtest_display.delete(row)
    
    def on_session_click(self, session_id):
        # Load trade stream for session id
        trade_stream = persist.load_trade_stream(session_id=session_id)
        # Populate tree view
        self.populate_backtest_display(trade_stream)
        # Update chart 
        self.results_chart.results = trade_stream      
        self.result_settings_tab.populate_result_text(self.result_settings_tab.get_result_summary(trade_stream))   
        self.results_chart.update_chart() 
        
    def create_session_card(self, parent, session_id, timestamp, stream_type):
        card = tk.Frame(parent, bg="#2e3e4e", padx=10, pady=5)
        card.pack(fill="x", pady=5)

        def format_session_code(session_id: int, stream_type: str) -> str:
            prefix = "LV" if stream_type == "live" else "BT"
            return f"{prefix}-{session_id:03d}"
        
        session_code = format_session_code(session_id, stream_type)
        
        lbl_id = tk.Label(card, text=session_code, font=("TkDefaultFont", 12, "bold"),
                      bg=card["bg"], fg="white")
        lbl_id.pack(side="left")

        lbl_time = tk.Label(card, text=timestamp, font=("TkDefaultFont", 10),
                        bg=card["bg"], fg="white")
        lbl_time.pack(side="right")

        # Bind clicks
        for widget in (card, lbl_id, lbl_time):
            widget.bind("<Button-1>", lambda e, sid=session_id: self.on_session_click(sid))
    
    def render_trade_history(self):
        for widget in self.trade_history.winfo_children():
            widget.destroy()

        # Only render if an account is active
        active_acc = self.controller.frames[TradingStrategyFrame].active_account
        if active_acc is None:
            return

        acc_id = int(active_acc.name)  # account_id is the Series.name
        sessions = persist.load_trade_sessions(acc_id)
    
        for sid, data in sessions.iterrows():
            # Format timestamps
            ended = data["ended_at"] 
            # Stream type
            stream_type = data["stream_type"]
            # Create a clickable card/button for each session
            self.create_session_card(self.trade_history, sid, ended, stream_type)
 

class ResultChartFrame(ttk.Frame):
    def __init__(self, parent, controller, backtest_results, result_var , show_label = False):
        super().__init__(parent)
        self.controller = controller
        self.show_label = show_label
        self.results = backtest_results
        self.result_var = result_var
        self.result_var.trace_add("write", self.update_chart)    
        # Show labels toggle
        self.show_label_var = tk.BooleanVar(value=False)
        self.show_label_toggle = ttk.Checkbutton(
            self,
            text="Show data labels",
            variable=self.show_label_var,
            command=self.toggle_show_label
        )
        self.show_label_toggle.grid(row=0, column=0, sticky="nsew")
        self.create_chart(self.show_label)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
    def toggle_show_label(self):  
        if self.show_label_var.get():
            self.show_label = True
        else:
            self.show_label = False
        self.update_chart()       
           
    def reset_chart(self):
        if self.chart is not None:
            self.chart.destroy()
            self.chart = None
    
    def create_chart(self, show_labels=False):
        self.chart = cftk_wrap.LineChartNoLabels(self, width=800, show_labels=show_labels, height=450)
        self.chart.grid(row=1, column=0, sticky="nsew")
        return self.chart
    
    def update_chart(self, *args):
        if self.results.empty:
            return

        selected = self.result_var.get()

        # Always reset chart before plotting
        self.reset_chart()
        chart = self.create_chart(show_labels=self.show_label)

        series_list = self.controller.frames[BackTestingResultsFrame].result_settings_tab.selected_series

        if series_list:
            datasets = []
            for series in series_list:
                if series in self.results.columns:
                    y_values = pd.to_numeric(self.results[series], errors="coerce").dropna().tolist()
                    if y_values:
                        datasets.append({
                            'data': y_values,
                            'label': series
                        })

            if datasets:
                chart.plot(datasets)  # ChartForgeTK will handle multi-series mode
        else:
            y_values = pd.to_numeric(self.results[selected], errors="coerce").dropna().tolist()
            if y_values:
                chart.plot(y_values)  # single series mode

                    

#--- Collapsible frames for vertical tab controls ---
class CollapsibleFrame(ttk.Frame):
    def __init__(self, parent, title="", *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.show = tk.BooleanVar(value=True)
        self.header = ttk.Checkbutton(
            self, text=title, style="Toolbutton",
            variable=self.show, command=self._toggle
        )
        self.header.pack(fill="x", pady=2)
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)
    
    def _toggle(self):
        if self.show.get():
            self.content.pack(fill="both", expand=True)
        else:
            self.content.forget()
        
class GeneralInfoCollapsibleFrame(CollapsibleFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, title="General")
        self.controller = controller
        # Stock symbol label
        self.stock_label = ttk.Label(self.content, text="Stock Symbol:")
        self.stock_label.pack(anchor="w", pady=(0, 2))

        # Frame to hold entry + search button side by side
        stock_frame = ttk.Frame(self.content)
        stock_frame.pack(fill="x", pady=2)

        self.stock_input = ttk.Entry(stock_frame)
        self.stock_input.insert(0, "AAPL")
        self.stock_input.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.search_btn = ttk.Button(
            stock_frame,
            text="🔍",
            width=3,
            command=lambda: self.controller.frames[TradingStrategyFrame].search()
        )
        self.search_btn.pack(side="left")

        # Start date
        self.start_date_label = ttk.Label(self.content, text="Start Date:")
        self.start_date_label.pack(anchor="w", pady=(5, 2))

        self.start_date_input = DateEntry(
            self.content,
            bootstyle="success",
            dateformat="%Y-%m-%d"
        )
        self.start_date_input.set_date(datetime.date(2025, 9, 1))
        self.start_date_input.pack(fill="x", pady=2)

        # End date
        self.end_date_label = ttk.Label(self.content, text="End Date:")
        self.end_date_label.pack(anchor="w", pady=(5, 2))

        self.end_date_input = DateEntry(
            self.content,
            bootstyle="success",
            dateformat="%Y-%m-%d"
        )
        self.end_date_input.set_date(datetime.date(2025, 9, 30))
        self.end_date_input.pack(fill="x", pady=2)


class StrategyCollapsibleFrame(CollapsibleFrame):
    def __init__(self, parent):
        super().__init__(parent, title="Strategy")   
        # BUY section 
        strategy_list = list(strategies.TradingStrategy.trading_strategies.keys())
        self.buy_section = stb.StrategySection(self.content, title="BUY", strategies = strategy_list, strategy_param_getter = self.get_strategy_params)
        self.buy_section.pack(fill="x", pady=5)
        # SELL section  
        self.sell_section = stb.StrategySection(self.content, title="SELL", strategies = strategy_list, strategy_param_getter = self.get_strategy_params)
        self.sell_section.pack(fill="x", pady=5)
    
    def get_strategy_params(self, name):
        default_params = {
            "DMA Crossover":{ "short_window"   :   20,"long_window"    :   50},
            "S/R Structure": { "distance"   :   5},
            "RSI": { "lookback" : 14, "overbought" : 70, "oversold" : 30},
            "EMA Breakout": { "short_window"   :   20,"long_window"    :   50}
        }
        return default_params.get(name, {})
        
class ExecutionCollasibleFrame(CollapsibleFrame): 
    def __init__(self, parent):
        super().__init__(parent, title="Execution")
        self.slippage_label = ttk.Label(self.content, text="Slippage")
        self.slippage_label.pack(anchor="w")
        self.slippage_input = ttk.Entry(self.content)
        self.slippage_input.insert(0, 0.001)
        self.slippage_input.pack(fill="x",pady=2)
        self.fee_rate_label = ttk.Label(self.content, text="Fee Rate")
        self.fee_rate_label.pack(anchor="w")
        self.fee_rate_input = ttk.Entry(self.content)
        self.fee_rate_input.insert(0, 0.001)
        self.fee_rate_input.pack(fill="x", pady=2)
        self.minimum_fee_label = ttk.Label(self.content, text="Minimum Fee")
        self.minimum_fee_label.pack(anchor="w")
        self.minimum_fee_input = ttk.Entry(self.content)
        self.minimum_fee_input.insert(0,1.0)
        self.minimum_fee_input.pack(fill="x", pady=2)
        self.lot_size_label = ttk.Label(self.content, text="Lot Size")
        self.lot_size_label.pack(anchor="w")
        self.lot_size_input = ttk.Entry(self.content)
        self.lot_size_input.insert(0, 1)
        self.lot_size_input.pack(fill="x", pady=2)
        self.stop_loss_var = tk.BooleanVar(value=False)  # OFF by default
        self.stop_loss_widgets = []  # will hold references to created widgets
        self.position_slider_label = ttk.Label(self.content, text="Position Size")
        self.position_slider_label.pack(anchor="w")
        self.position_slider_value = tk.DoubleVar()
        self.position_slider = ttk.Scale(
            self.content, 
            from_=0, 
            to=1.0, 
            orient="horizontal",
            variable=self.position_slider_value
        )
        self.position_slider.pack(fill="x", pady=2)
        # Set default to max
        self.position_slider_value.set(self.position_slider.cget("to"))

        self.stop_loss_toggle = ttk.Checkbutton(
            self.content, 
            text="Enable Stop Loss", 
            variable=self.stop_loss_var, 
            command=self.toggle_stop_loss, 
            onvalue=True, 
            offvalue=False
        )
        self.stop_loss_toggle.pack(fill="x", pady=2)
    
    def toggle_stop_loss(self):
        if self.stop_loss_var.get(): 
            self.create_stop_loss_widgets()
        else:
            self.remove_stop_loss_widgets()
    
    def create_stop_loss_widgets(self):
        self.stop_loss_widgets = [] #reset list
        
        time_interval_label = ttk.Label(self.content, text="ATR Time Interval: 14")
        time_interval_label.pack(anchor="w")
        self.stop_loss_widgets.append(time_interval_label)

        
    def remove_stop_loss_widgets(self):
        for widget in self.stop_loss_widgets:
            widget.destroy()

class ResultSettingsCollapsibleFrame(CollapsibleFrame):
    def __init__(self, parent, controller, result_headers):
        super().__init__(parent, title="Result Settings")
        self.controller = controller
        # Track selected series for multi-line plotting
        self.selected_series = []
        
        self.result_var = tk.StringVar(value=result_headers[0])
        opt_frame = tk.Frame(self.content, bg="#f0f0f0")
        opt_frame.grid(row=0, column=0, sticky="ns", padx=5, pady=5)

        opt = ttk.Combobox(opt_frame, values=result_headers, textvariable=self.result_var, state="readonly")
        opt.pack(side="left", fill="x", expand=True)

        add_btn = ttk.Button(opt_frame, text="➕", width=2, bootstyle=SUCCESS, command=self.add_series)
        add_btn.pack(side="left", padx=(5, 0))

        # Row 1: Selected series list
        self.series_frame = tk.Frame(self.content, bg="#f0f0f0")
        self.series_frame.grid(row=1, column=0, sticky="ns", padx=5)

        # Result summary (Net Profit, Final Equity, %return)
        self.result_summary = tk.Label(self.content, text ="")
        self.result_summary.grid(row = 2, column = 0, sticky="ns")
        results_summary = { 
            "final_equity"  :   0,
            "profits"       :   0,
            "returns"       :   0,
            "sharpe_ratio"  :   0
        }
        self.result_summary_var =  self.populate_result_text(results_summary)
        
        # Run new test button
        self.run_new_test_button = ttk.Button(self.content, text="Run New Test", command=self.run_new_test)
        self.run_new_test_button.grid(row=3, column=0, padx=5, pady=5, sticky="ns")
        
    # --- Series management ---
    def add_series(self):
        series = self.result_var.get()
        if series not in self.selected_series:
            self.selected_series.append(series)
            self.refresh_series_list()
            self.controller.frames[BackTestingResultsFrame].results_chart.update_chart()

    def remove_series(self, series):
        if series in self.selected_series:
            self.selected_series.remove(series)
            self.refresh_series_list()
            self.controller.frames[BackTestingResultsFrame].results_chart.update_chart()

    def refresh_series_list(self):
        for widget in self.series_frame.winfo_children():
            widget.destroy()

        for s in self.selected_series:
            row = tk.Frame(self.series_frame, bg="#f0f0f0")
            row.pack(fill="x", pady=1)

            lbl = tk.Label(row, text=s, anchor="w", bg="#f0f0f0")
            lbl.pack(side="left", fill="x", expand=True)

            rm_btn = ttk.Button(row, text="❌", width=2, bootstyle= DANGER,
                                command=lambda name=s: self.remove_series(name))
            rm_btn.pack(side="right")
    
    # --- Utility functions ---   
    def populate_result_text(self, results):
        if results:
            self.result_summary.config(
                text=(
                    f"Final Equity ($): {results['final_equity']}\n"
                    f"Profits ($): {results['profits']}\n"
                    f"Returns (%): {results['returns']}\n"
                    f"Sharpe Ratio: {results['sharpe_ratio']}"
                )
            )     
    
    def get_result_summary(self, results):
        result_summary = {}
        if not results.empty:
            initial_equity = results['equity'].iloc[0]
            result_summary['final_equity'] = round(results['equity'].iloc[-1], 2)
            result_summary['profits'] = round(result_summary['final_equity'] - initial_equity, 2)
            result_summary['returns'] = round((result_summary['profits'] / initial_equity) * 100, 2)
            chart_frame = self.controller.frames[TradingStrategyFrame].chart_frame
            time_frame = chart_frame.time_interval
            if chart_frame.live_switch_var.get():
                time_frame = chart_frame.candle_aggregator.time_interval
            result_summary['sharpe_ratio'] = round(engine.compute_sharpe_ratio(returns = results['returns'], 
                                                                               timeframe = time_frame), 2)
        return result_summary
          
    def run_new_test(self):
        self.controller.show_main_frame(TradingStrategyFrame, "trading")
           
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
