import sys
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from api_requests import build_auth_url, exchange_code_for_tokens, REDIRECT_URI
import json

    
class TradingBotInterface:
    
    def __init__(self, root):
        self.root = root
        self.root.title("AI trading Bot")
        self.system_running = False
        
        self.form_frame = tk.Frame(root)
        self.form_frame.pack(pady = 10)
        
        # Interface to Authenticate on Questrade 
        self.add_button = tk.Button(self.form_frame, text="Log in", command= self.login)
        self.add_button.grid(row = 0)

        self.chat_input = tk.Entry(self.form_frame, width = 75)
        self.chat_input.grid(row = 1, column = 0, padx = 5)
         
        self.chat_output = tk.Text(root, height = 10, width = 75, state = tk.DISABLED)
        self.chat_output.pack(pady = 10)
                
        self.add_button = tk.Button(self.form_frame, text="Athenticate", command= self.authenticate)
        self.add_button.grid(row = 1, column = 6)

     
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
        code = self.chat_input.get().strip()
        if not code:
            self.chat_output.insert(tk.END, "No code provided, exiting.")
            sys.exit(1)
        # Exchange code for tokens
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, "Exchanging code for tokens…")
        token_data = exchange_code_for_tokens(code)
        # Show & persist tokens
        self.chat_output.delete(1.0, tk.END)
        self.chat_output.insert(tk.END, "\n🚀 Success! Here’s what Questrade returned:\n")
        self.chat_output.insert(tk.END, json.dumps(token_data, indent=2))
        self.chat_output.config(state=tk.DISABLED)
        
    def on_close(self):
        self.running = False
        self.root.destroy()
            
if __name__ == '__main__':
    root = tk.Tk()
    app = TradingBotInterface(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
        
