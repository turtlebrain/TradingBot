import tkinter as tk
from tkinter import ttk, messagebox
import json
import time
import threading
import random

DATA_FILE = "equities.json"

key = "kTyqb6n1jikHfmw8bCMnOkNQ0xpGAyYQ0"

def fetch_mock_api(symbol):
    return {
        "price" : 100
    }
    
def mock_chatgpt_response(message):
    return f"Mock response to: {message}"
    
class TradingBotInterface:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.equities = self.load_equities() 
        self.system_running = False
        
        self.form_frame = tk.Frame(root)
        self.form_frame.pack(pady = 10)
        
        # Form to add a equity to trading bot
        tk.Label(self.form_frame, text = "Symbol:").grid(row = 0, column = 0)
        self.symbol_entry = tk.Entry(self.form_frame)
        self.symbol_entry.grid(row = 0 , column = 1)
        
        tk.Label(self.form_frame, text = "Levels:").grid(row = 0, column = 2)
        self.levels_entry = tk.Entry(self.form_frame)
        self.levels_entry.grid(row = 0, column = 3)
        
        tk.Label(self.form_frame, text = "Drawdown%:").grid(row = 0, column = 4)
        self.drawdown_entry = tk.Entry(self.form_frame)
        self.drawdown_entry.grid(row = 0, column = 5)
        
        self.add_button = tk.Button(self.form_frame, text="Add Equity", command= self.add_equity)
        self.add_button.grid(row = 0, column = 6)
        
        # Table to trade equities in portfolio
        self.tree = ttk.Treeview(root, columns=("Symbol", "Position", "Entry Price", "Levels", "Status"), show = 'headings')
        for col in ["Symbol", "Position", "Entry Price", "Levels", "Status"]:
            self.tree.heading(col, text = col)
            self.tree.column(col, width = 120)
        self.tree.pack(pady=10)
        
        # Trading bot controls
        self.toggle_system_button = tk.Button(root, text="Toggle Selected System", command = self.toggle_selected_system)
        self.toggle_system_button.pack(pady = 5)
        
        self.remove_button = tk.Button(root, text="Remove Selected Equity", command = self.remove_selected_equity)
        self.remove_button.pack(pady = 5)
        
        # AI Component
        self.chat_frame = tk.Frame(root)
        self.chat_frame.pack(pady = 10)
        
        self.chat_input = tk.Entry(self.chat_frame, width = 50)
        self.chat_input.grid(row = 0, column = 0, padx = 5)
        
        self.send_button = tk.Button(self.chat_frame, text = "Send", command = self.send_message)
        self.send_button.grid(row = 0, column = 1)
        
        self.chat_output = tk.Text(root, height = 5, width = 60, state = tk.DISABLED)
        self.chat_output.pack()
        
        # Load saved data
        self.refresh_table()
        
        # Auto - refreshing
        self.running = True
        self.auto_update_thread = threading.Thread(target = self.auto_update, daemon = True)
        self.auto_update_thread.start()
        
    def add_equity(self):
        levels = self.levels_entry.get()
        drawdown = self.drawdown_entry.get()
        symbol = self.symbol_entry.get().upper()
        
        if not symbol or not levels.isdigit() or not drawdown.replace('.','', 1).isdigit():
            messagebox.showerror("Error", "Invalid Input")
            return
        
        levels = int(levels)
        drawdown = float(drawdown)/100
        entry_price = fetch_mock_api(symbol)['price']
        
        level_prices = {i + 1 : round(entry_price * (1 - drawdown*(i+1)), 2) for i in range(levels)}
        
        self.equities[symbol] = {
            "position" : 0,
            "entry_price" : entry_price,
            "levels": level_prices,
            "status": "Off"
        }
        self.save_equities()
        self.refresh_table()
        
    def toggle_selected_system(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No Equity is Selected")
            return
        
        for item in selected_items:
            symbol = self.tree.item(item)['values'][0]
            self.equities[symbol]['status'] = "On" if self.equities[symbol]['status'] == "Off" else "Off"
            
        self.save_equities()
        self.refresh_table()
        
    def remove_selected_equity(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No Equity Selected")
            return
        
        for item in selected_items:
            symbol = self.tree.item(item)['values'][0]
            if symbol in self.equities:
                del self.equities[symbol]
                
        self.save_equities()
        self.refresh_table()
        
    def send_message(self):
        message = self.chat_input.get()
        if not message:
            return
        
        response = mock_chatgpt_response(message)
        
        self.chat_output.config(state = tk.NORMAL)
        self.chat_output.insert(tk.END, f"You: {message}\n{response}\n\n")
        self.chat_output.config(state = tk.DISABLED)
        self.chat_input.delete(0, tk.END)
        
    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for symbol, data in self.equities.items():
            self.tree.insert("", "end", values = (
                symbol,
                data['position'],
                data['entry_price'],
                str(data['levels']),
                data['status']
            ))
        
    def auto_update(self):
        while self.running:
            time.sleep(5)
            self.update_prices()
            
    def save_equities(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.equities, f)
            
    def load_equities(self):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except(FileNotFoundError, json.JSONDecodeError):
            return {}
        
    def on_close(self):
        self.running = False
        self.save_equities()
        self.root.destroy()
            
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotInterface(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
