import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
import api_requests as qt_api
import json
from tkcalendar import DateEntry
import trading_strategies as strategies
import pandas as pd
from ChartForgeTK import CandlestickChart
from ChartForgeTK import LineChart
import tkinter.font as tkFont
import position_sizing as pos_sz
import backtest_engine as engine
import requests 

# Global variables to store access token and API server URL
access_token = ''
api_server = ''

class TradingBotApp:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.root.geometry("1280x720")
        self.system_running = False
        
        # Change default font for all widgets to Poppins
        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family="Poppins")
        # Container to hold all frames
        container = ttk.Frame(root)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        
        self.frames = {}
        for F in (LoginFrame, AuthFrame, TradingStrategyFrame, BackTestingResultsFrame):
            frame = F(parent=container, controller=self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")
        
        self.show_frame(LoginFrame)    
        
    def show_frame(self, frame_calss):
        frame = self.frames[frame_calss]
        frame.tkraise() 
    
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
        
    def authenticate(self):
        code = self.code_entry.get().strip()
        if not code:
            messagebox.showwarning("Input Error", "No code provided.")
            return
        token_data = qt_api.exchange_code_for_tokens(code)
        messagebox.showinfo("Tokens", f"Received tokens: {json.dumps(token_data, indent=2)}")
        global access_token, api_server
        api_server = token_data.get('api_server', '')   
        access_token = token_data.get('access_token', '')
        if api_server and access_token:
            initial_df = self.controller.frames[TradingStrategyFrame].search(show_output=False)
            if isinstance(initial_df, list):
                initial_df = pd.DataFrame(initial_df)
                chart_frame = self.controller.frames[TradingStrategyFrame].chart_frame
                chart_frame.candle_chart.clear()
                chart_frame.candle_chart.plot(data=chart_frame.convert_data_for_chart(initial_df))
        self.controller.show_frame(TradingStrategyFrame)

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
        self.strategy_var = tk.StringVar(value = "Double Moving Average Crossover")
        self.general_tab = self.controller.create_tab(notebook, "General", 
                                   lambda parent: GeneralInfoCollapsibleFrame(parent, self.strategy_var))
        self.strategy_tab = self.controller.create_tab(notebook, "Strategy", 
                                   lambda parent: StrategyCollapsibleFrame(parent, self.strategy_var))
        self.execution_tab = self.controller.create_tab(notebook, "Execution", ExecutionCollasibleFrame)

        # --- Right-hand content area ---
        right_frame = ttk.Frame(self)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.columnconfigure(1, weight=1)
        right_frame.rowconfigure(1, weight=1)  # chart expands

        # Buttons
        self.search_button = ttk.Button(right_frame, width=50, text="Search", command=self.search)
        self.search_button.grid(row=0, column=0, padx=2, pady=2)

        self.backtest_button = ttk.Button(right_frame, width=50, text="Run Backtest", command=self.run_backtest)
        self.backtest_button.grid(row=0, column=1, padx=2, pady=2)

        # Chart
        self.chart_frame = CandlestickChartFrame(right_frame, controller)
        self.chart_frame.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

        # Chat output
        self.chat_output = tk.Text(right_frame, height=5, state=tk.DISABLED)
        self.chat_output.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

        self.scrollbar = ttk.Scrollbar(right_frame, command=self.chat_output.yview)
        self.scrollbar.grid(row=2, column=2, sticky='ns')
        self.chat_output['yscrollcommand'] = self.scrollbar.set

        # Clear button
        self.clear_button = ttk.Button(right_frame, text="Clear", command=self.clear_form)
        self.clear_button.grid(row=3, column=0, columnspan=2, pady=2, sticky='ns')


    def clear_form(self):
        self.chat_output.config(state=tk.NORMAL) 
        self.chat_output.delete(1.0, tk.END) 
        self.chat_output.config(state=tk.DISABLED)   
                  
    def search(self, show_output=True):
        self.clear_form()    
        stock_symbol = self.general_tab.stock_input.get().strip() 
        start_date = self.general_tab.start_date_input.get_date().isoformat()
        end_date = self.general_tab.end_date_input.get_date().isoformat()
        if not stock_symbol or not start_date or not end_date:
            messagebox.showwarning("Input Error", "Please enter a valid stock symbol as query.")
            return
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, f"Searching for: {stock_symbol}\n")
        # API Search
        global access_token, api_server
        my_access_token = access_token
        my_api_server = api_server  
        if not my_access_token and not my_api_server:
            self.chat_output.insert(tk.END, "No access token found, please log in and authenticate first.\n")
            self.chat_output.config(state=tk.DISABLED)
            return   
        try:   
            symbol_data = qt_api.get_stock_data(access_token=my_access_token, api_server=my_api_server, symbol_str=stock_symbol)
            if not symbol_data:
                self.chat_output.insert(tk.END, f"No data found for {stock_symbol}.\n")
                self.chat_output.config(state=tk.DISABLED)
                return
            symbol_id = symbol_data[0]['symbolId']
            candle_data = qt_api.get_candles_paginated(access_token=my_access_token, api_server=my_api_server, symbol_id=symbol_id, start_date=self.general_tab.start_date_input.get_date(), end_date=self.general_tab.end_date_input.get_date())
            candle_data_pd = pd.DataFrame(candle_data)
            if show_output:
                self.chat_output.insert(tk.END, f"Candlestick data:\n{json.dumps(candle_data, indent=2)}\n")
                self.chat_output.config(state=tk.DISABLED)
                # Plot candlestick chart
                chart_frame = self.chart_frame
                chart_frame.candle_chart.clear()
                chart_frame.candle_chart.plot(chart_frame.convert_data_for_chart(candle_data_pd))       
            return candle_data
        except requests.exceptions.HTTPError as err:
            self.chat_output.config(state=tk.NORMAL)
            self.chat_output.delete(1.0, tk.END)
            self.chat_output.insert(tk.END, f"HTTEP error occurered {err}.\n")
            self.chat_output.config(state=tk.DISABLED)                 
    
    def is_input_valid_float(self, input, name):
        try:
            float(input)
            return True
        except ValueError:
            self.chat_output.config(state=tk.NORMAL)
            self.chat_output.delete(1.0, tk.END)
            self.chat_output.insert(tk.END, f"Please enter a valid {name} (number only).\n")
            self.chat_output.config(state=tk.DISABLED)
            return False
            
        
    
    def run_backtest(self):
        picked_strategy = self.strategy_var.get()
        strategies_map = strategies.TradingStrategy.trading_strategies
        candle_data = self.search(show_output=False)
        if isinstance(candle_data, list):
            candle_data = pd.DataFrame(candle_data)  
            
        strategy_params = { 
            "short_window"   :   self.strategy_tab.short_entry.get().strip(),
            "long_window"    :   self.strategy_tab.long_entry.get().strip()
        }
        
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
        
        try:
            backtest_results = engine.backtest_strategy(
                data = candle_data, 
                strategy_func = strategies_map[picked_strategy], 
                strategy_param = strategy_params,
                position_sizer = pos_sz.all_in_sizer,
                starting_capital = float(initial_capital),
                allow_short = False,
                slippage = float(slippage),
                fee_rate = float(fee_rate),
                fee_min = float(fee_min),
                lot_size = int(lot_size)
                )
            if not backtest_results.empty:
                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.populate_backtest_display(backtest_results)
                eqc_x_labels = backtest_results.index.tolist()
                eqc_y_values = pd.to_numeric(backtest_results["equity"], errors="coerce").dropna().tolist()
                if eqc_y_values:
                    # Ensure labels are strings if provided
                    if eqc_x_labels is not None:
                        eqc_x_labels = [str(lbl) for lbl in eqc_x_labels]
                        backtest_frame.eq_curve.reset_chart()
                        backtest_frame.eq_curve.create_chart()
                        backtest_frame.eq_curve.equity_chart.plot(eqc_y_values, eqc_x_labels)
            self.controller.show_frame(BackTestingResultsFrame)
        except ValueError as err:
            self.chat_output.config(state=tk.NORMAL)
            self.chat_output.delete(1.0, tk.END)
            self.chat_output.insert(tk.END, f"Error: {err}.\n")
            self.chat_output.config(state=tk.DISABLED)
   
class CandlestickChartFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.candle_chart = CandlestickChart(self, width = 960, height = 540)
        self.candle_chart.grid(row=0, column=0, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
    def convert_data_for_chart(self, df):
        # Ensure index is reset so we can enumerate
        df = df.reset_index(drop=True)
        # Create list of tuples: (index, open, high, low, close)
        return [
            (i, float(row['open']), float(row['high']), float(row['low']), float(row['close']))
            for i, row in df.iterrows()
        ]
                           
class BackTestingResultsFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.results_label = ttk.Label(self, text="Backtesting Results:")
        self.results_label.grid(row=1, column=1, padx=2, pady=2)
        # Equity Curve Chart
        self.eq_curve = EquityChartFrame(self, controller)
        self.eq_curve.grid(row=2, column=1, padx=5,pady=5, sticky="ns")
        # Treeview
        col_headers = ['price', 'signal', 'shares','cash','equity','market_value','order','exec_price','fees','trade_side','pnl','cum_max_equity','drawdown','returns']
        self.backtest_display = ttk.Treeview(self, columns=col_headers, show="headings")
        for col in col_headers:
            self.backtest_display.heading(col, text=col)
            self.backtest_display.column(col, width=100, anchor="center")
        self.backtest_display.grid(row=3, column=1, padx=5, pady=5, sticky="nsew")

        # Scrollbars
        self.scroll_y = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.backtest_display.yview)
        self.scroll_y.grid(row=3, column=2, sticky='ns')
        self.scroll_x = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.backtest_display.xview)
        self.scroll_x.grid(row=4, column=1, sticky='ew')

        self.backtest_display.configure(yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set)

        # Let the Treeview expand
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.run_new_test_button = ttk.Button(self, width=50, text="Run New Test", command=self.run_new_test)
        self.run_new_test_button.grid(row=5, column=1, padx=2, pady=2, sticky="ns")
        self.controller.add_outer_rows_and_cols(self)
    
    def populate_backtest_display(self, dataframe):
        for row in self.backtest_display.get_children():
            self.backtest_display.delete(row)
        for _, row in dataframe.iterrows():
            self.backtest_display.insert("", "end", values=list(row))
        
    def run_new_test(self):
        self.controller.show_frame(TradingStrategyFrame)

class EquityChartFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.equity_chart = None
        self.grid_columnconfigure(0, weight=1)
        
    def reset_chart(self):
        # Remove any previous chart widget cleanly
        for child in self.winfo_children():
            child.destroy()
        self.equity_chart = None
    
    def create_chart(self):
        self.equity_chart = LineChart(self, width=960, height=540)
        self.equity_chart.grid(row=0, column=1, sticky="nsew")
        return self.equity_chart

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
    def __init__(self, parent, strategy_var):
        super().__init__(parent, title = "General")
        self.strategy_var = strategy_var
        self.stock_label = ttk.Label(self.content, text="Stock Symbol:")
        self.stock_label.pack(anchor="w")
        self.stock_input = ttk.Entry(self.content)
        self.stock_input.insert(0, "AAPL")
        self.stock_input.pack(fill="x", pady=2)
        
        self.start_date_label = ttk.Label(self.content, text="Start Date:")
        self.start_date_label.pack(anchor="w")
        self.start_date_input = DateEntry(self.content, year=2025, month=8, day=1)
        self.start_date_input.pack(fill="x",pady=2)
        
        self.end_date_label = ttk.Label(self.content, text="End Date:")
        self.end_date_label.pack(anchor="w")
        self.end_date_input = DateEntry(self.content, year=2025, month=8, day=31)
        self.end_date_input.pack(fill="x", pady=2)
        
        trading_strategy = strategies.TradingStrategy
        self.strategy_label = ttk.Label(self.content, text="Strategy:")
        self.strategy_label.pack(anchor="w")
        self.strategy_menu = ttk.OptionMenu(self.content, self.strategy_var, self.strategy_var.get(), *trading_strategy.trading_strategies.keys())
        self.strategy_menu.pack(fill="x", pady=2)

class StrategyCollapsibleFrame(CollapsibleFrame):
    def __init__(self, parent, strategy_var):
        super().__init__(parent, title="Strategy")    
        self.strategy_var = strategy_var
        self.strategy_var.trace_add("write", self.update_contents)
        self.update_contents()
        
    def clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()
    
    def update_contents(self, *args):
        self.clear_content()
        selected = self.strategy_var.get()
        
        if selected == "Double Moving Average Crossover":
            ttk.Label(self.content, text="Short Window:").pack(anchor="w")
            self.short_entry = ttk.Entry(self.content)
            self.short_entry.pack(fill="x", pady=2)
            self.short_entry.insert(0, 20)
            ttk.Label(self.content, text="Long Window:").pack(anchor="w")
            self.long_entry = ttk.Entry(self.content)
            self.long_entry.pack(fill="x", pady=2)
            self.long_entry.insert(0, 50)

        else:
            ttk.Label(self.content, text=f"{selected} \n is not implemented yet").pack(anchor="w")

        
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
        
        
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
