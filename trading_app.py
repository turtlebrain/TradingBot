import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import api_requests as qt_api
import json
import ttkbootstrap as ttkb
from ttkbootstrap.widgets import DateEntry
from ttkbootstrap.constants import *
import trading_strategies as strategies
import pandas as pd
import tkinter.font as tkFont
import position_sizing as pos_sz
import risk_control as risk
import backtest_engine as engine
import requests 
import chartforgetk_wrapper as cftk_wrap
import time
import datetime
import threading
import tick_streamer as qt_stream
import strategy_tree_builder as stb
from persistence import save_accounts, load_accounts


class TradingBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.root.geometry("1440x810")
        self.system_running = False

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
        self.streamer = None
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
        self.streamer = qt_stream.QuestradeStreamer(
            access_token = self.access_token,
            api_server = self.api_server
        )
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
                self.streamer.access_token = self.access_token
                self.streamer.api_server = self.api_server
                if self.controller.frames[TradingStrategyFrame].chart_frame.live_switch_var.get():
                    symbol_data = qt_api.get_stock_data(
                        access_token=self.access_token,
                        api_server=self.api_server, 
                        symbol_str=self.controller.frames[TradingStrategyFrame].general_tab.stock_input.get().strip()
                    )
                    symbol_id = symbol_data[0]['symbolId']
                    self.streamer.start_stream(symbol_id)
                self.expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=refresh_token_data.get('expires_in', 0))
                print("Access token refreshed successfully")
            except Exception as e:
                print("Failed to refresh token:", e)
                time.sleep(30)  # Wait a short delay before retrying

class AccountManagerFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.accounts = pd.DataFrame(columns=["created", "last_opened", "capital"])
        
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

        for meta in self.accounts.itertuples():
            row = ttk.Frame(self.list_frame, bootstyle="light")  
            row.pack(fill="x", pady=2, padx=5, ipady=5, ipadx=5)

            def open(n=meta.Index):
                self.open_account(n)

            # Bind click to row and all children
            row.bind("<Button-1>", lambda e: open())
        
            # Create widgets
            name_lbl = ttk.Label(row, text=meta.Index, font=("Poppins", 12, "bold"))
            created_lbl = ttk.Label(row, text=f"Created: {meta.created}", foreground="gray")
            opened_lbl = ttk.Label(row, text=f"Last opened: {meta.last_opened}", foreground="gray")
            rename_btn = ttk.Button(row, text="Rename", width = 8, bootstyle=INFO, command=lambda n=meta.index: self.rename_account(n))
            delete_btn = ttk.Button(row, text="Delete", width = 8, bootstyle=DANGER, command=lambda n=meta.index: self.delete_account(n))

            name_lbl.pack(side="left")
            created_lbl.pack(side="left", padx=10)
            opened_lbl.pack(side="left", padx=10)
            delete_btn.pack(side="right", padx=2)
            rename_btn.pack(side="right", padx=2)

            # Bind click to labels too
            for widget in [name_lbl, created_lbl, opened_lbl]:
                widget.bind("<Button-1>", lambda e: open())
            
    def create_account(self):
        # Prompt for account name and starting capital
        dialog = AccountDialog(self)
        self.wait_window(dialog.top)

        if dialog.result:
            name, capital = dialog.result
            if name in self.accounts:
                messagebox.showerror("Error", f"Account '{name}' already exists.")
                return
    
        # Create account metadata
        created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        last_opened = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        self.accounts.loc[name]=[created, last_opened, capital]

        self.render_accounts()
        # Automatically goes to trading view after being created
        self.on_open_trading_view(self.accounts.loc[name])
            
    def on_open_trading_view(self, meta):
        self.controller.frames[TradingStrategyFrame].execution_tab.starting_capital_input.delete(0, tk.END)
        self.controller.frames[TradingStrategyFrame].execution_tab.starting_capital_input.insert(0, str(meta["capital"]))
        self.controller.show_main_frame(TradingStrategyFrame, "trading")
        
    def open_account(self, name):
        self.accounts.at[name, "last_opened"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        self.on_open_trading_view(self.accounts.loc[name])
    
    def rename_account(self, name):
        new_name = simpledialog.askstring("Rename Account", "Enter new name:")
        if new_name and new_name not in self.accounts.index:
            self.accounts = self.accounts.rename(index={name: new_name})
            self.render_accounts()
    
    def delete_account(self, name):
        if messagebox.askyesno("Delete Account", f"Delete {name}?"):
            self.accounts.drop(name, inplace=True)
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
    
class TradingStrategyFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        # --- Sidebar + main content container ---
        # Use grid for the whole TradingStrategyFrame
        self.columnconfigure(0, weight=0)  # sidebar fixed width
        self.columnconfigure(1, weight=1)  # main content expands
        self.rowconfigure(0, weight=1)

        # Notebook in column 0
        notebook = ttk.Notebook(self, style="TNotebook")
        notebook.grid(row=0, column=0, sticky="ns")  # fill vertically
        
        # Create Tabs
        self.general_tab = self.controller.create_tab(notebook, "General", 
                                   lambda parent: GeneralInfoCollapsibleFrame(parent, self.controller))
        self.strategy_tab = self.controller.create_tab(notebook, "Strategy", 
                                   lambda parent: StrategyCollapsibleFrame(parent))
        self.execution_tab = self.controller.create_tab(notebook, "Execution", ExecutionCollasibleFrame)

        # --- Right-hand content area ---
        right_frame = ttk.Frame(self)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.columnconfigure(1, weight=1)
        right_frame.rowconfigure(0, weight=1)  # chart expands

        # Chart
        self.chart_frame = CandlestickChartFrame(right_frame, controller)
        self.chart_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

        # Positions Table
        cols = ("Symbol", "Quantity", "Avg Price", "Current Price", "P/L")  
        self.positions_table = ttk.Treeview(right_frame, columns = cols, show="headings", height = 8)
        for col in cols:
            self.positions_table.heading(col, text = col)
            self.positions_table.column(col, anchor="center", width=100)
        self.positions_table.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="nsew") 

        self.scrollbar = ttk.Scrollbar(right_frame, command=self.positions_table.yview)
        self.scrollbar.grid(row=1, column=2, sticky='ns')
        self.positions_table['yscrollcommand'] = self.scrollbar.set

        # Run backtest button    
        self.backtest_button = ttk.Button(right_frame, width=50, text="Run Backtest", command=self.run_backtest)
        self.backtest_button.grid(row=2, column=0, columnspan=2, padx=2, pady=2)
                  
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
            
    def get_result_summary(self, results):
        result_summary = {}
        if not results.empty:
            initial_equity = results['equity'].iloc[0]
            result_summary['final_equity'] = round(results['equity'].iloc[-1], 2)
            result_summary['profits'] = round(result_summary['final_equity'] - initial_equity, 2)
            result_summary['returns'] = round((result_summary['profits'] / initial_equity) * 100, 2)
            time_frame = self.chart_frame.time_interval
            if self.chart_frame.live_switch_var.get():
                time_frame = self.controller.frames[AuthFrame].streamer.candle_aggregator.time_interval
            result_summary['sharpe_ratio'] = round(engine.compute_sharpe_ratio(returns = results['returns'], 
                                                                               timeframe = time_frame), 2)
        return result_summary
    
    def run_backtest(self):
        candle_data = {}
        if not self.chart_frame.live_switch_var.get():
            candle_data = self.search(show_output=False)
        else:
            candle_data = self.controller.frames[AuthFrame].streamer.candle_aggregator.get_candles()
        if isinstance(candle_data, list):
            candle_data = pd.DataFrame(candle_data)  
        
        initial_capital = self.execution_tab.starting_capital_input.get().strip()
        if not self.is_input_valid_float(initial_capital, "Starting Capital"):
            return
        slippage = self.execution_tab.slippage_input.get().strip()
        if not self.is_input_valid_float(slippage, "Slippage"):     
            return
        fee_rate = self.execution_tab.fee_rate_input.get().strip()
        if not self.is_input_valid_float(fee_rate, "Fee Rate"):          
            return
        fee_min = self.execution_tab.minimum_fee_input.get().strip()
        if not self.is_input_valid_float(fee_min, "Minimum Fee"):        
            return
        lot_size = self.execution_tab.lot_size_input.get().strip()
        if not lot_size.isdigit():
            return
        sl_func = None
        if self.execution_tab.stop_loss_var.get():
            sl_func = risk.StopLoss.average_true_range_stop
        fixed_fraction = self.execution_tab.position_slider_value.get()
        if not self.is_input_valid_float(fixed_fraction, "Fixed Fraction"):        
            return
        try:
            backtest_results = engine.backtest_strategy(
                data = candle_data, 
                buy_logic = self.strategy_tab.buy_section, 
                sell_logic = self.strategy_tab.sell_section,
                position_sizer_func = pos_sz.fixed_fraction_position_sizer,
                position_sizer_param = float(fixed_fraction),
                stop_loss_func = sl_func,
                starting_capital = float(initial_capital),
                allow_short = False,
                slippage = float(slippage),
                fee_rate = float(fee_rate),
                fee_min = float(fee_min),
                lot_size = int(lot_size)
            )
            if not backtest_results.empty:
                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.backtest_results = backtest_results
                backtest_frame.populate_backtest_display(backtest_results)
                backtest_frame.results_chart.results = backtest_results      
                backtest_frame.populate_result_text(self.get_result_summary(backtest_results))   
                backtest_frame.title_label.configure(text=f"Backtest Results for {self.general_tab.stock_input.get().strip()}")
                backtest_frame.results_chart.update_chart() 
            self.controller.show_main_frame(BackTestingResultsFrame, "performance")
        except ValueError as err:
            messagebox.showerror("Error", err)
   
class CandlestickChartFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.live_switch_var = tk.BooleanVar(value=False)  # OFF by default
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
        self.timeframe_control = self.create_segmented_control(self.timeframe_options, self.on_timeframe_change)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
    
    def toggle_live_mode(self):
        if self.live_switch_var.get(): 
            symbol_data = qt_api.get_stock_data(
                access_token=self.controller.frames[AuthFrame].access_token,
                api_server=self.controller.frames[AuthFrame].api_server, 
                symbol_str=self.controller.frames[TradingStrategyFrame].general_tab.stock_input.get().strip()
            )
            for rb in self.timeframe_control:
                rb.config(state=tk.DISABLED)
            
            symbol_id = symbol_data[0]['symbolId']
            self.controller.frames[AuthFrame].streamer.start_stream(symbol_id)
            self.periodically_update_chart()
        else:
            self.controller.frames[AuthFrame].streamer.stop_stream()
            for rb in self.timeframe_control:
                rb.config(state=tk.NORMAL)
        
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
    
    def update_chart(self, df):
        self.candle_chart.clear()
        self.candle_chart.plot(self.convert_data_for_chart(df), 
                               self.controller.frames[TradingStrategyFrame].general_tab.stock_input.get().strip())
        
    def periodically_update_chart(self):
        candles_df = self.controller.frames[AuthFrame].streamer.candle_aggregator.get_candles()
        if not candles_df.empty and self.live_switch_var.get():
            self.update_chart(candles_df)
        root.after(30000, self.periodically_update_chart)  # Update every 30 seconds     
               
    def create_segmented_control(self, options, command = None):
        self.sg_var = tk.StringVar(value=options[1])
        self.sg_command = command
        style = ttk.Style()
        style.configure("Segmented.TRadiobutton", indicatoron=0, relief="raised")
        style.map("Segmented.TRadiobutton", relief=[("selected", "sunken")])
        buttons = []
        for i, option in enumerate(options):
            rb = ttk.Radiobutton(
                self,
                text=option,
                value=option,
                variable=self.sg_var,
                command=self._on_select,
                style="Segmented.TRadiobutton"
            )
            rb.grid(row=2,column=i, sticky="nsew")
            self.columnconfigure(i, weight=1)
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
        
        col_headers = [
            'price', 'signal', 'shares', 'cash', 'equity', 'market_value',
            'order', 'exec_price', 'stop_loss', 'fees', 'trade_side', 'pnl',
            'cum_max_equity', 'drawdown', 'returns'
        ]

        # Track selected series for multi-line plotting
        self.selected_series = []

        # --- Layout config ---
        self.columnconfigure(0, weight=0)   # sidebar fixed width
        self.columnconfigure(1, weight=1)   # main area expands
        self.rowconfigure(0, weight=1)

        # --- Sidebar ---
        sidebar = tk.Frame(self, bg="#f0f0f0", width=200)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        # Row 0: OptionMenu + Add button
        self.result_var = tk.StringVar(value=col_headers[0])
        opt_frame = tk.Frame(sidebar, bg="#f0f0f0")
        opt_frame.grid(row=0, column=0, sticky="ns", padx=5, pady=5)

        opt = ttk.Combobox(opt_frame, values=col_headers, textvariable=self.result_var, state="readonly")
        opt.pack(side="left", fill="x", expand=True)

        add_btn = ttk.Button(opt_frame, text="➕", width=2, bootstyle=SUCCESS, command=self.add_series)
        add_btn.pack(side="left", padx=(5, 0))

        # Row 1: Selected series list
        self.series_frame = tk.Frame(sidebar, bg="#f0f0f0")
        self.series_frame.grid(row=1, column=0, sticky="ns", padx=5)

        # Show labels toggle
        self.show_label_var = tk.BooleanVar(value=False)
        self.show_label_toggle = ttk.Checkbutton(
            sidebar,
            text="Show data labels",
            variable=self.show_label_var,
            command=self.toggle_show_label
        )
        self.show_label_toggle.grid(row=2, column=0, padx=5, pady=5, sticky="ns")

        # Result summary (Net Profit, Final Equity, %return)
        self.result_summary = tk.Label(sidebar, text ="")
        self.result_summary.grid(row = 3, column = 0, sticky="ns")
        results_summary = { 
            "final_equity"  :   0,
            "profits"       :   0,
            "returns"       :   0,
            "sharpe_ratio"  :   0
        }
        self.result_summary_var =  self.populate_result_text(results_summary)
        
        # Run new test button
        self.run_new_test_button = ttk.Button(sidebar, text="Run New Test", command=self.run_new_test)
        self.run_new_test_button.grid(row=4, column=0, padx=5, pady=5, sticky="ns")
        
        # --- Main area ---
        main_area = tk.Frame(self, bg="white")
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.grid_columnconfigure(0, weight=1)
        main_area.grid_rowconfigure(1, weight=1)
        
        self.title_label = tk.Label(main_area, text=f"Backtest results", bg="white", font=("Poppins", 14))
        self.title_label.grid(row=0, column=0, columnspan=2, pady=2)

        # Chart area
        self.results_chart = ResultChartFrame(main_area, controller, self.backtest_results, self.result_var)
        self.results_chart.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        # Treeview
        self.backtest_display = ttk.Treeview(main_area, columns=col_headers, show="headings")
        for col in col_headers:
            self.backtest_display.heading(col, text=col)
            self.backtest_display.column(col, width=100, anchor="center")
        self.backtest_display.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")

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

    # --- Series management ---
    def add_series(self):
        series = self.result_var.get()
        if series not in self.selected_series:
            self.selected_series.append(series)
            self.refresh_series_list()
            self.results_chart.update_chart()

    def remove_series(self, series):
        if series in self.selected_series:
            self.selected_series.remove(series)
            self.refresh_series_list()
            self.results_chart.update_chart()

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

    
    def toggle_show_label(self):  
        if self.show_label_var.get():
            self.results_chart.show_label = True
        else:
            self.results_chart.show_label = False
        self.results_chart.update_chart()
        
    def populate_backtest_display(self, dataframe):
        for row in self.backtest_display.get_children():
            self.backtest_display.delete(row)
        for _, row in dataframe.iterrows():
            self.backtest_display.insert("", "end", values=list(row))
    
    def populate_result_text(self, results):
        self.result_summary.config(
            text=(
                f"Final Equity ($): {results['final_equity']}\n"
                f"Profits ($): {results['profits']}\n"
                f"Returns (%): {results['returns']}\n"
                f"Sharpe Ratio: {results['sharpe_ratio']}"
            )
        )     
          
    def run_new_test(self):
        self.controller.show_main_frame(TradingStrategyFrame, "trading")

class ResultChartFrame(ttk.Frame):
    def __init__(self, parent, controller, backtest_results, result_var , show_label = False):
        super().__init__(parent)
        self.controller = controller
        self.show_label = show_label
        self.results = backtest_results
        self.result_var = result_var
        self.result_var.trace_add("write", self.update_chart)    
        self.create_chart(self.show_label)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
              
    def reset_chart(self):
        # Remove any previous chart widget cleanly
        for child in self.winfo_children():
            child.destroy()
        self.chart = None
    
    def create_chart(self, show_labels=False):
        self.chart = cftk_wrap.LineChartNoLabels(self, width=800, show_labels=show_labels, height=450)
        self.chart.grid(row=0, column=0, sticky="nsew")
        return self.chart
    
    def update_chart(self, *args):
        if self.results.empty:
            return

        selected = self.result_var.get()

        # Always reset chart before plotting
        self.reset_chart()
        chart = self.create_chart(show_labels=self.show_label)

        series_list = self.controller.frames[BackTestingResultsFrame].selected_series

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
        self.start_date_input.set_date(datetime.date(2025, 8, 1))
        self.start_date_input.pack(fill="x", pady=2)

        # End date
        self.end_date_label = ttk.Label(self.content, text="End Date:")
        self.end_date_label.pack(anchor="w", pady=(5, 2))

        self.end_date_input = DateEntry(
            self.content,
            bootstyle="success",
            dateformat="%Y-%m-%d"
        )
        self.end_date_input.set_date(datetime.date(2025, 8, 31))
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
        self.starting_capital_label = ttk.Label(self.content, text="Starting Capital:")
        self.starting_capital_label.pack(anchor="w")
        self.starting_capital_input = ttk.Entry(self.content)
        self.starting_capital_input.insert(0, 10000.0)
        self.starting_capital_input.pack(fill="x", pady=2)
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
        
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
