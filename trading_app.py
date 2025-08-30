import sys
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from api_requests import build_auth_url, exchange_code_for_tokens, REDIRECT_URI
from api_requests import get_stock_data
import json
from tkcalendar import DateEntry

access_token = ''
api_server = ''

class TradingBotInterface:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.system_running = False
        
        self.form_frame = tk.Frame(root)
        self.form_frame.pack(pady = 10)
        
        # App Interface
        self.login_button = tk.Button(self.form_frame, width = 50, text="Log in", command= self.login)
        self.login_button.grid(row = 0, columnspan = 2, pady = 2)

        self.code_label = tk.Label(self.form_frame, width = 10, text="Enter code:")
        self.code_label.grid(row = 1, column = 0, padx = 2, pady = 2)
        self.code_input = tk.Entry(self.form_frame, width = 30)
        self.code_input.grid(row = 1, column = 1, padx = 2, pady = 2)
        
        self.auth_button = tk.Button(self.form_frame, width = 50, text="Athenticate", command= self.authenticate)
        self.auth_button.grid(row = 2, columnspan = 2, pady = 2)
        
        self.start_date_label = tk.Label(self.form_frame, width = 10, text="Start date:")   
        self.start_date_label.grid(row = 3, column = 0, padx = 2, pady = 2)
        self.start_date_input = DateEntry(self.form_frame, date_pattern='yyyy-mm-dd')
        self.start_date_input.grid(row = 3, column = 1, padx = 2, pady = 2)
        
        self.end_date_label = tk.Label(self.form_frame, width = 10, text="End date:")
        self.end_date_label.grid(row = 4, column = 0, padx = 2, pady = 2)
        self.end_date_input = DateEntry(self.form_frame, date_pattern='yyyy-mm-dd')
        self.end_date_input.grid(row = 4, column = 1, padx = 2, pady = 2)
        
        self.stock_label = tk.Label(self.form_frame, width = 10, text="Stock symbol:")
        self.stock_label.grid(row = 5, column = 0, padx = 2, pady = 2)
        self.stock_input = tk.Entry(self.form_frame, width = 30)
        self.stock_input.grid(row = 5, column = 1, padx = 2, pady = 2)
        
        self.stock_search_label = tk.Label(self.form_frame, width = 10, text="Candlestick:")
        self.stock_search_label.grid(row = 6, column = 0, padx = 2, pady = 2)
        self.stock_search_button = tk.Button(self.form_frame, width = 30, text="Search", command= self.search)
        self.stock_search_button.grid(row = 6, column = 1, padx = 2, pady = 2)
         
        self.chat_output = tk.Text(root, height = 10, width = 50, state = tk.DISABLED)
        self.chat_output.pack(pady = 10)
        
        self.clear_button = tk.Button(root, text="Clear", command= self.clear_form)
        self.clear_button.pack(pady = 5)
                
    def clear_form(self):
        self.chat_output.config(state=tk.NORMAL) 
        self.chat_output.delete(1.0, tk.END) 
        self.chat_output.config(state=tk.DISABLED)
        
    def login(self):
        auth_url = build_auth_url()
        try:
            webbrowser.open(auth_url)
        except:
            pass
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, f"After logging in, you'll be redirected to: {REDIRECT_URI}?code=YOUR_CODE_HERE\n")
        self.chat_output.config(state=tk.DISABLED)
    
    def authenticate(self):
        code = self.code_input.get().strip()
        if not code:
            self.chat_output.insert(tk.END, "No code provided, exiting.")
            sys.exit(1)
        # Exchange code for tokens
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, "Exchanging code for tokens…")
        token_data = exchange_code_for_tokens(code)
        # Show & persist tokens
        self.chat_output.delete(1.0, tk.END)
        self.chat_output.insert(tk.END, "\n Success! Here’s what Questrade returned:\n")
        self.chat_output.insert(tk.END, json.dumps(token_data, indent=2))
        self.chat_output.config(state=tk.DISABLED)
        global access_token, api_server
        api_server = token_data.get('api_server', '')   
        access_token = token_data.get('access_token', '')
                  
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
        symbol_data = get_stock_data(access_token=my_access_token, api_server=my_api_server, symbol_str=stock_symbol)
        if not symbol_data:
            self.chat_output.insert(tk.END, f"No data found for {stock_symbol}.\n")
            self.chat_output.config(state=tk.DISABLED)
            return
        self.chat_output.insert(tk.END, f"{json.dumps(symbol_data, indent=2)}")
        self.chat_output.config(state=tk.DISABLED)
        
    def on_close(self):
        self.running = False
        self.root.destroy()
            
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotInterface(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
