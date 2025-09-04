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

# Global variables to store access token and API server URL
access_token = ''
api_server = ''

class TradingBotApp:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.root.geometry("900x800")
        self.system_running = False
        
        # Change default font for all widgets to Poppins
        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family="Poppins")
        # Container to hold all frames
        container = tk.Frame(root)
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
    
    def add_outer_rows_and_cols(self, frame: tk.Frame):
        cols, rows = frame.grid_size()
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(cols+1, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_rowconfigure(rows+1, weight=1)         
        
    def on_close(self):
        self.running = False
        self.root.quit()
        self.root.destroy()
            
class LoginFrame(tk.Frame):
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
        
class AuthFrame(tk.Frame):
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

class TradingStrategyFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.stock_label = ttk.Label(self, text="Stock Symbol:")
        self.stock_label.grid(row=1, column=1, padx=2, pady=2, sticky='we')
        self.stock_input = ttk.Entry(self)
        self.stock_input.insert(0, "AAPL")
        self.stock_input.grid(row=1, column=2, padx=2, pady=2, sticky='we')
        
        self.start_date_label = ttk.Label(self, text="Start Date:")
        self.start_date_label.grid(row=2, column=1, padx=2, pady=2, sticky='we')
        self.start_date_input = DateEntry(self, year=2025, month=8, day=1)
        self.start_date_input.grid(row=2, column=2, padx=2, pady=2, sticky='we')
        
        self.end_date_label = ttk.Label(self, text="End Date:")
        self.end_date_label.grid(row=3, column=1, padx=2, pady=2, sticky='we')
        self.end_date_input = DateEntry(self, year=2025, month=8, day=31)
        self.end_date_input.grid(row=3, column=2, padx=2, pady=2, sticky='we')
        
        trading_strategy = strategies.TradingStrategy
        self.strategy_label = ttk.Label(self, text="Strategy:")
        self.strategy_label.grid(row=4, column=1, padx=2, pady=2, sticky='we')
        self.strategy_var = tk.StringVar(value="Moving Average Crossover Strategy")
        self.strategy_menu = ttk.OptionMenu(self, self.strategy_var, "Moving Average Crossover Strategy", *trading_strategy.trading_strategies.keys())
        self.strategy_menu.grid(row=4, column=2, padx=2, pady=2, sticky='we')
        
        self.starting_capital_label = ttk.Label(self, text="Starting Capital:")
        self.starting_capital_label.grid(row=5, column=1, padx=2, pady=2, sticky='we')
        self.starting_capital_input = ttk.Entry(self)
        self.starting_capital_input.insert(0, 10000)
        self.starting_capital_input.grid(row=5, column=2, padx=2, pady=2, sticky='we')
        
        self.search_button = ttk.Button(self, width=50, text="Search", command= self.search)
        self.search_button.grid(row=6, column=1, padx=2, pady=2, sticky='ns')
        self.backtest_button = ttk.Button(self, width=50, text="Run Backtest", command=self.run_backtest) 
        self.backtest_button.grid(row=6, column=2, padx=2, pady=2, sticky='ns')
        
        # Chart and chat output area   
        self.chart_frame = CandlestickChartFrame(self, controller)
        self.chart_frame.grid(row=7, column=1, columnspan=2, padx=5, pady=5, sticky = "we")
        self.chat_output = tk.Text(self, height = 5, state=tk.DISABLED)
        self.chat_output.grid(row=8, column=1, columnspan=2, padx=5, pady=5, sticky = "nsew")
        self.scrollbar = ttk.Scrollbar(self, command=self.chat_output.yview)
        self.scrollbar.grid(row=8, column=3, sticky='nsw')
        self.chat_output['yscrollcommand'] = self.scrollbar.set
        
        self.clear_button = ttk.Button(self, text="Clear", command=self.clear_form)
        self.clear_button.grid(row=9, column=1, columnspan=2, pady=2, sticky='ns')
        
        self.controller.add_outer_rows_and_cols(self)

    def clear_form(self):
        self.chat_output.config(state=tk.NORMAL) 
        self.chat_output.delete(1.0, tk.END) 
        self.chat_output.config(state=tk.DISABLED)   
                  
    def search(self, show_output=True):
        self.clear_form()    
        stock_symbol = self.stock_input.get().strip()
        start_date = self.start_date_input.get_date().isoformat()
        end_date = self.end_date_input.get_date().isoformat()
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
        symbol_data = qt_api.get_stock_data(access_token=my_access_token, api_server=my_api_server, symbol_str=stock_symbol)
        if not symbol_data:
            self.chat_output.insert(tk.END, f"No data found for {stock_symbol}.\n")
            self.chat_output.config(state=tk.DISABLED)
            return
        symbol_id = symbol_data[0]['symbolId']
        candle_data = qt_api.get_candles_paginated(access_token=my_access_token, api_server=my_api_server, symbol_id=symbol_id, start_date=self.start_date_input.get_date(), end_date=self.end_date_input.get_date())
        candle_data_pd = pd.DataFrame(candle_data)
        if show_output:
            self.chat_output.insert(tk.END, f"Candlestick data:\n{json.dumps(candle_data, indent=2)}\n")
            self.chat_output.config(state=tk.DISABLED)
            # Plot candlestick chart
            chart_frame = self.chart_frame
            chart_frame.candle_chart.clear()
            chart_frame.candle_chart.plot(chart_frame.convert_data_for_chart(candle_data_pd))       
        return candle_data
    
    def run_backtest(self):
        picked_strategy = self.strategy_var.get()
        strategies_map = strategies.TradingStrategy.trading_strategies
        candle_data = self.search(show_output=False)
        if isinstance(candle_data, list):
            candle_data = pd.DataFrame(candle_data)
        # Build state for position sizer    
        initial_capital = self.starting_capital_input.get().strip()
        if not initial_capital.isdigit():
            self.chat_output.config(state=tk.NORMAL)
            self.chat_output.delete(1.0, tk.END)
            self.chat_output.insert(tk.END, "Please enter a valid starting capital (number only).\n")
            self.chat_output.config(state=tk.DISABLED)
        backtest_results = engine.backtest_strategy(
            data = candle_data, 
            strategy_func = strategies_map[picked_strategy], 
            position_sizer = pos_sz.all_in_sizer,
            starting_capital = float(initial_capital),
            allow_short = False,
            slippage = 0.001,
            fee_rate = 0.001,
            fee_min = 1.0,
            lot_size = 1
            )
        if not backtest_results.empty:
            backtest_frame = self.controller.frames[BackTestingResultsFrame]
            backtest_frame.populate_backtest_display(backtest_results)
            eqc_x_labels = backtest_results.index.tolist()
            eqc_y_values = backtest_results["equity"].tolist()
            backtest_frame.eq_curve.equity_chart.clear()
            backtest_frame.eq_curve.equity_chart.plot(eqc_y_values, eqc_x_labels)
        self.controller.show_frame(BackTestingResultsFrame)
   
class CandlestickChartFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.candle_chart = CandlestickChart(self, width=832, height=468)
        self.candle_chart.grid(row=0, column=1, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        
    def convert_data_for_chart(self, df):
        # Ensure index is reset so we can enumerate
        df = df.reset_index(drop=True)
        # Create list of tuples: (index, open, high, low, close)
        return [
            (i, float(row['open']), float(row['high']), float(row['low']), float(row['close']))
            for i, row in df.iterrows()
        ]
                           
class BackTestingResultsFrame(tk.Frame):
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

class EquityChartFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.equity_chart = LineChart(self, width=832, height=468)
        self.equity_chart.grid(row=0, column=1, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        
    
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
