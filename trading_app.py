import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
import api_requests as qt_api
import json
from tkcalendar import DateEntry
import trading_strategies as strategies

access_token = ''
api_server = ''

class TradingBotApp:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.root.geometry("600x400")
        self.system_running = False
        
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
        
        self.show_frame(TradingStrategyFrame)    
        
    def show_frame(self, frame_calss):
        frame = self.frames[frame_calss]
        frame.tkraise() 
        
    def on_close(self):
        self.running = False
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
        self.code_label.place(relx=0.35, rely=0.5, anchor="center")
        self.code_entry = ttk.Entry(self, width=30)
        self.code_entry.place(relx=0.60, rely=0.5, anchor="center")
        self.auth_button = ttk.Button(self, text="Authenticate", width=50, command=self.authenticate)
        self.auth_button.place(relx=0.5, rely=0.6, anchor="center")
        
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
        self.controller.show_frame(TradingStrategyFrame)

class TradingStrategyFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.stock_label = ttk.Label(self, text="Stock Symbol:")
        self.stock_label.grid(row=0, column=0, padx=2, pady=2)
        self.stock_input = ttk.Entry(self)
        self.stock_input.grid(row=0, column=1, padx=2, pady=2)
        
        self.start_date_label = ttk.Label(self, text="Start Date:")
        self.start_date_label.grid(row=1, column=0, padx=2, pady=2)
        self.start_date_input = DateEntry(self)
        self.start_date_input.grid(row=1, column=1, padx=2, pady=2)
        
        self.end_date_label = ttk.Label(self, text="End Date:")
        self.end_date_label.grid(row=2, column=0, padx=2, pady=2)
        self.end_date_input = DateEntry(self)
        self.end_date_input.grid(row=2, column=1, padx=2, pady=2)
        
        trading_strategy = strategies.TradingStrategy
        self.strategy_label = ttk.Label(self, text="Strategy:")
        self.strategy_label.grid(row=3, column=0, padx=2, pady=2)
        self.strategy_var = tk.StringVar(value="Moving Average Crossover Strategy")
        self.strategy_menu = ttk.OptionMenu(self, self.strategy_var, "Moving Average Crossover Strategy", *trading_strategy.trading_strategies.keys())
        self.strategy_menu.grid(row=3, column=1, padx=2, pady=2)
        
        self.starting_capital_label = ttk.Label(self, text="Starting Capital:")
        self.starting_capital_label.grid(row=4, column=0, padx=2, pady=2)
        self.starting_capital_input = ttk.Entry(self)
        self.starting_capital_input.grid(row=4, column=1, padx=2, pady=2)
        
        self.search_button = ttk.Button(self, text="Search", command= self.search)
        self.search_button.grid(row=5, column=0, padx=2, pady=2)
        self.backtest_button = ttk.Button(self, text="Run Backtest", command=self.run_backtest) 
        self.backtest_button.grid(row=5, column=1, padx=2, pady=2)
        
        self.chat_output = tk.Text(self, state=tk.DISABLED)
        self.chat_output.grid(row=6, columnspan=2, padx=5, pady=5)
        self.scrollbar = ttk.Scrollbar(self, command=self.chat_output.yview)
        self.scrollbar.grid(row=6, column=2, sticky='nsew')
        self.chat_output['yscrollcommand'] = self.scrollbar.set
        
        self.clear_button = ttk.Button(self, text="Clear", command=self.clear_form)
        self.clear_button.grid(row=7, columnspan=2, pady=2)
    
    def clear_form(self):
        self.chat_output.config(state=tk.NORMAL) 
        self.chat_output.delete(1.0, tk.END) 
        self.chat_output.config(state=tk.DISABLED)   
                  
    def search(self):
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
        candle_data = qt_api.get_candlestick_data(access_token=my_access_token, api_server=my_api_server, symbol_id=symbol_id, start_date=self.start_date_input.get_date(), end_date=self.end_date_input.get_date())
        self.chat_output.insert(tk.END, f"Candlestick data:\n{json.dumps(candle_data, indent=2)}\n")
        self.chat_output.config(state=tk.DISABLED)
    
    def run_backtest(self):
        self.controller.show_frame(BackTestingResultsFrame)
                   
class BackTestingResultsFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.results_label = ttk.Label(self, text="Backtesting Results will be shown here.")
        self.results_label.pack(pady=10)
        self.run_new_test_button = ttk.Button(self, text="Run New Test", command=self.run_new_test)
        self.run_new_test_button.pack(pady=10)
        
    def run_new_test(self):
        self.controller.show_frame(TradingStrategyFrame)

if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
