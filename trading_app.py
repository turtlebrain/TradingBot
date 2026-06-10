import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from Brokers.broker_factory import get_broker
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
import chart_performance as chart_perf
import time
import datetime
import calendar
import threading
import tick_streamer as qt_stream
import strategy_tree_builder as stb
import persistence as persist
import timeframe_presets as tf_presets
import tick_processor
import queue
import ML_Classifier.ml_trading_persistence as ml_persist
from ML_Classifier.stacked_meta_learner import train_stacked_meta_learner


class TradingBotApp:
    def __init__(self, root):
        self.root = root
        style = ttkb.Style("flatly") 
        style.master = root         
        self.root.title("TradingBot")
        self.root.geometry("1440x900")
        self.system_running = False

        # Broker is selected by the user before login.
        self.selected_broker_name = None
        self.broker = None   
        
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
        for F in (BrokerSelectionFrame, LoginFrame, AuthFrame, AccountManagerFrame, TradingStrategyFrame, BackTestingResultsFrame):
            frame = F(parent=container, controller=self)
            self.frames[F] = frame
            frame.grid(row=1, column=0, sticky="nsew")

        # Start at broker selection
        self.show_frame(BrokerSelectionFrame)
     
    def show_frame(self, frame_calss):
        frame = self.frames[frame_calss]
        if hasattr(frame, "on_show"):
            frame.on_show()
        frame.tkraise() 

    def select_broker(self, broker_name):
        self.selected_broker_name = broker_name
        self.broker = None
        self.show_frame(LoginFrame)

    def get_selected_broker(self):
        if not self.selected_broker_name:
            raise RuntimeError("Please choose a broker before logging in.")
        if self.broker is None:
            self.broker = get_broker(self.selected_broker_name)
        return self.broker
    
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
        if self.broker:
            if hasattr(self.broker, "disconnect"):
                try:
                    self.broker.disconnect()
                except Exception:
                    pass
            if hasattr(self.broker, "log"):
                self.broker.log.end_session()
        self.root.quit()

    def is_ibkr(self) -> bool:
        return self.selected_broker_name == "ibkr"

    def is_session_ready(self) -> bool:
        if self.is_ibkr():
            return self.broker is not None and getattr(self.broker, "connected", False)
        auth = self.frames[AuthFrame]
        return bool(auth.access_token and auth.api_server)

class BrokerSelectionFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, padding=40)
        self.controller = controller

        content = ttk.Frame(self)
        content.place(relx=0.5, rely=0.5, anchor="center")

        title = ttk.Label(content, text="Choose your broker", font=("Poppins", 24, "bold"))
        title.grid(row=0, column=0, columnspan=2, pady=(0, 12))

        subtitle = ttk.Label(
            content,
            text="Select the broker API you want to connect before continuing to the main app.",
            font=("Poppins", 11),
            wraplength=560,
            justify="center"
        )
        subtitle.grid(row=1, column=0, columnspan=2, pady=(0, 28))

        self._create_broker_option(
            content,
            row=2,
            column=0,
            broker_name="questrade",
            title="Questrade",
            description="Use the existing browser login and authorization-code flow.",
        )
        self._create_broker_option(
            content,
            row=2,
            column=1,
            broker_name="ibkr",
            title="IBKR",
            description="Use Interactive Brokers. Backend connection setup will run after this choice.",
        )

    def _create_broker_option(self, parent, row, column, broker_name, title, description):
        card = ttk.Frame(parent, padding=24, relief="ridge", borderwidth=1)
        card.grid(row=row, column=column, padx=12, sticky="nsew")
        parent.columnconfigure(column, weight=1)

        ttk.Label(card, text=title, font=("Poppins", 16, "bold")).pack(pady=(0, 8))
        ttk.Label(card, text=description, wraplength=240, justify="center").pack(pady=(0, 18))
        ttk.Button(
            card,
            text=f"Continue with {title}",
            width=28,
            bootstyle=PRIMARY,
            command=lambda: self.controller.select_broker(broker_name)
        ).pack()

class LoginFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        content = ttk.Frame(self)
        content.place(relx=0.5, rely=0.5, anchor="center")

        self.broker_label = ttk.Label(content, text="", font=("Poppins", 14, "bold"))
        self.broker_label.pack(pady=(0, 12))

        self.login_button = ttk.Button(content, width=50, text="Log in", command=self.login)
        self.login_button.pack(pady=(0, 8))

        self.change_broker_button = ttk.Button(
            content,
            width=50,
            text="Change broker",
            bootstyle=SECONDARY,
            command=lambda: self.controller.show_frame(BrokerSelectionFrame)
        )
        self.change_broker_button.pack()
        self.pack_propagate(False)

    def on_show(self):
        broker_name = self.controller.selected_broker_name
        broker_label = broker_name.upper() if broker_name == "ibkr" else "Questrade"
        self.broker_label.configure(text=f"Selected broker: {broker_label}")
        self.login_button.configure(text=f"Log in with {broker_label}")

    def login(self):
        # Use the broker abstraction
        try:
            broker = self.controller.get_selected_broker()
            auth_info = broker.authenticate()
        except Exception as e:
            if self.controller.broker and hasattr(self.controller.broker, "disconnect"):
                try:
                    self.controller.broker.disconnect()
                except Exception:
                    pass
            self.controller.broker = None
            messagebox.showerror("Login Error", f"Unable to start broker login: {e}")
            return
        auth_url = auth_info.get("auth_url")

        if auth_url:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass
            # Use broker's configured redirect_uri for messaging (optional: expose via broker)
            redirect_uri = getattr(broker, "redirect_uri", "YOUR_REDIRECT_URI")
            messagebox.showinfo("Login", f"After logging in, you'll be redirected to: {redirect_uri}?code=YOUR_CODE_HERE")
            self.controller.show_frame(AuthFrame)
        else:
            # For non-OAuth brokers (e.g., IBKR session), you may already be connected
            messagebox.showinfo("Login", "Broker connected (no OAuth required).")
            self.controller.after_auth()
        
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

        # Session state
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

        # Call the broker to complete OAuth
        try:
            token_data = self.controller.broker.complete_auth(code)
        except NotImplementedError:
            messagebox.showerror("Auth Error", "This broker does not use code-based auth.")
            return
        except Exception as e:
            messagebox.showerror("Auth Error", f"Failed to authenticate: {e}")
            return

        messagebox.showinfo("Tokens", f"Received tokens: {json.dumps(token_data, indent=2)}")

        # Store for UI and streamer
        self.api_server = token_data.get('api_server', '')
        self.access_token = token_data.get('access_token', '')
        self.refresh_token = token_data.get('refresh_token', '')
        self.expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=token_data.get('expires_in', 0)
        )

        # Optional: persist into controller for app-wide access
        self.controller.session = {
            "api_server": self.api_server,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expiry_time": self.expiry_time,
        }

        if self.api_server and self.access_token:
            # Start background thread for auto-refresh
            self.thread = threading.Thread(target=self.auto_refresh_tokens, daemon=True)
            self.thread.start()

        self.controller.after_auth()

    def auto_refresh_tokens(self):
        while True:
            with self.lock:
                if self.expiry_time:
                    time_to_wait = max(0, (self.expiry_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds() - 120)
                else:
                    time_to_wait = 60

            time.sleep(time_to_wait)
            try:
                # Use broker to refresh (abstracted method name)
                refresh_data = self.controller.broker.refresh_token(self.refresh_token)

                self.api_server = refresh_data.get('api_server', '')
                self.access_token = refresh_data.get('access_token', '')
                self.refresh_token = refresh_data.get('refresh_token', '')

                # Schedule UI-safe update
                self.after(0, self._update_streamer)

                self.expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                    seconds=refresh_data.get("expires_in", 0)
                )
            except Exception as e:
                print("Failed to refresh token:", e)
                time.sleep(30)

    def _update_streamer(self):
        # Update the active chart streamer safely on the UI thread
        streamer = self.controller.frames[TradingStrategyFrame].top_tabs.get_active_chart().streamer
        if streamer:
            streamer.access_token = self.access_token
            streamer.api_server = self.api_server
            streamer.reconnect()
            print("Access token refreshed successfully")


class AccountManagerFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.accounts = persist.load_accounts()
        
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.render_accounts()
        
        ttk.Button(self, text="New Account", width=25, bootstyle=INFO, command=self.create_account).pack(pady=10)
    
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
            rename_btn = ttk.Button(row, text="Rename", width = 8, command=lambda n=meta.name: self.rename_account(n))
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
        trading_frame = self.controller.frames[TradingStrategyFrame]
        backtest_frame = self.controller.frames[BackTestingResultsFrame]

        # Activate account and refresh account info
        trading_frame.set_active_account(meta)
        trading_frame.update_account_info()

        # Clear charts via TabbedWorkspaceFrame and refresh positions
        trading_frame.top_tabs.clear_all_charts()
        trading_frame.render_positions_table()

        # Reset backtesting results
        backtest_frame.results_chart.chart.clear()
        backtest_frame.clear_backtest_display()
        backtest_frame.render_trade_history()

        # Show trading frame
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

        ttk.Button(top, text="Create", command=self.on_ok).pack(padx=10, pady=10)

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

        # Store tuples: (workspace_frame, tab_widget, chart_frame, general_tab, strategy_tab, execution_tab)
        self.workspaces = []
        self.active_workspace = None

        self.add_workspace_tab()

    def add_workspace_tab(self):
        idx = len(self.workspaces) + 1
        label = f"🗂{idx}"
        closable = idx > 1

        workspace = ttk.Frame(self.workspace_area)
        workspace.grid(row=0, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=0)
        workspace.columnconfigure(1, weight=1)
        workspace.rowconfigure(0, weight=1)

        # Sidebar Notebook
        notebook = ttk.Notebook(workspace, width = 255, style="TNotebook")
        notebook.grid(row=0, column=0, sticky="ns")

        general_tab = GeneralInfoCollapsibleFrame(notebook, self.controller)
        strategy_tab = StrategyCollapsibleFrame(notebook, self.controller)
        execution_tab = ExecutionCollasibleFrame(notebook)

        notebook.add(general_tab, text="General")
        notebook.add(strategy_tab, text="Strategy")
        notebook.add(execution_tab, text="Execution")

        # Chart
        chart = CandlestickChartFrame(workspace, self.controller)
        chart.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        tab_widget = self._create_tab_widget(label, closable)
        self.workspaces.append((workspace, tab_widget, chart, general_tab, strategy_tab, execution_tab))

        # Align strategy-tab defaults with this chart's interval. Call the tab
        # directly — during TradingStrategyFrame.__init__ the frame is not yet
        # registered on controller.frames.
        strategy_tab.apply_timeframe_presets(chart.time_interval)

        self.select_workspace(tab_widget)
        self._refresh_plus_button()



    def _create_tab_widget(self, title, closable=True):
        tab = ttk.Frame(self.tab_bar)
        tab.pack(side="left", padx=2, pady=2)

        lbl = ttk.Label(tab, text=title, width=6, anchor="center")
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e, t=tab: self.select_workspace(t))

        # Keep references so we can re-render the title (e.g. prepend [CA])
        # without losing the original base title.
        tab.title_label = lbl
        tab.base_title = title
        tab.base_width = 6

        if closable:
            btn = ttk.Button(tab, text="✖", width=2, bootstyle=DANGER,
                             command=lambda t=tab: self.close_workspace(t))
            btn.pack(side="right")

        return tab

    def _refresh_plus_button(self):
        for child in self.tab_bar.winfo_children():
            if getattr(child, "is_plus", False):
                child.destroy()

        plus = ttk.Button(self.tab_bar, text="➕", width=2, bootstyle=SUCCESS,
                          command=self.add_workspace_tab)
        plus.is_plus = True
        plus.pack(side="left", padx=2)

    def select_workspace(self, tab_widget):
        """
        Raise the selected workspace and mark it active.
        """
        for workspace, tab, chart, general_tab, strategy_tab, execution_tab in self.workspaces:
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

        for i, (workspace, tab, chart, general_tab, strategy_tab, execution_tab) in enumerate(self.workspaces):
            if tab is tab_widget:
                # Ask chart to clean up first
                chart.shutdown()

                # Now destroy UI
                workspace.destroy()
                tab.destroy()
                del self.workspaces[i]
                break

        if self.workspaces:
            self.select_workspace(self.workspaces[-1][1])
            
   # --- Helpers for active workspace ---
    def get_active_chart(self):
        for workspace, tab, chart, *_ in self.workspaces:
            if workspace is self.active_workspace:
                return chart
        return None

    def get_active_general_tab(self):
        for workspace, tab, chart, general_tab, *_ in self.workspaces:
            if workspace is self.active_workspace:
                return general_tab
        return None

    def get_active_strategy_tab(self):
        for workspace, tab, chart, _, strategy_tab, _ in self.workspaces:
            if workspace is self.active_workspace:
                return strategy_tab
        return None

    def get_active_execution_tab(self):
        for workspace, tab, chart, _, _, execution_tab in self.workspaces:
            if workspace is self.active_workspace:
                return execution_tab
        return None

    def get_strategy_tab_for_chart(self, chart):
        """Return the StrategyCollapsibleFrame tied to the workspace ``chart``."""
        for workspace, tab, c, _, strategy_tab, _ in self.workspaces:
            if c is chart:
                return strategy_tab
        return None

    def clear_active_chart(self):
        """Clear the chart in the currently active workspace."""
        if not self.active_workspace:
            return
        for workspace, tab, chart, general_tab, strategy_tab, execution_tab in self.workspaces:
            if workspace is self.active_workspace:
                chart.candle_chart.clear()
                break
            
            
    def clear_all_charts(self):
        """Clear charts in all workspaces."""
        for workspace, tab, chart, general_tab, strategy_tab, execution_tab in self.workspaces:
            chart.candle_chart.clear()

    # --- Cross-asset workspace helpers ---
    # A "cross-asset" workspace is a chart tab the user has flagged to be used
    # as a second-symbol input (e.g. SPY when training MES) for strategies that
    # consume cross_asset_bars. At most one workspace can be marked at a time,
    # and the active (primary) workspace cannot reference itself.
    def get_cross_asset_workspace(self):
        """Return the (workspace, tab, chart, general_tab, strategy_tab, execution_tab)
        tuple for the workspace currently marked as cross-asset, or None."""
        for entry in self.workspaces:
            _, _, chart, *_ = entry
            var = getattr(chart, "cross_asset_var", None)
            if var is not None and var.get():
                return entry
        return None

    def get_cross_asset_chart(self):
        entry = self.get_cross_asset_workspace()
        return entry[2] if entry else None

    def get_cross_asset_general_tab(self):
        entry = self.get_cross_asset_workspace()
        return entry[3] if entry else None

    def clear_cross_asset_marks_except(self, chart_to_keep):
        """Unmark cross-asset on every workspace except the one whose chart is
        chart_to_keep. Used to enforce the one-at-a-time invariant whenever the
        user flips the toggle on in a new workspace."""
        for workspace, tab, chart, *_ in self.workspaces:
            if chart is chart_to_keep:
                continue
            var = getattr(chart, "cross_asset_var", None)
            if var is not None and var.get():
                var.set(False)
                self._set_tab_cross_asset_prefix(tab, False)

    def set_cross_asset_prefix_for_chart(self, chart, mark_on):
        """Update the tab label (add or remove the [CA] prefix) for the workspace
        whose chart is the given one. Called by CandlestickChartFrame.toggle_cross_asset."""
        for workspace, tab, c, *_ in self.workspaces:
            if c is chart:
                self._set_tab_cross_asset_prefix(tab, mark_on)
                return

    def _set_tab_cross_asset_prefix(self, tab_widget, mark_on):
        """Idempotently add or remove the [CA] prefix on a tab label, widening
        the label slot so the longer text doesn't get truncated."""
        lbl = getattr(tab_widget, "title_label", None)
        base_title = getattr(tab_widget, "base_title", None)
        if lbl is None or base_title is None:
            return
        prefix = "[CA]"
        new_text = f"{prefix}{base_title}" if mark_on else base_title
        base_width = getattr(tab_widget, "base_width", 6)
        new_width = max(len(new_text) + 1, base_width)
        lbl.configure(text=new_text, width=new_width)

 
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
        account_group.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # Label bound to cash_var
        self.pnl_var = tk.StringVar(value=f"${self.cash_var.get():,.2f} Cash")
        pnl_label = ttk.Label(
            account_group,
            textvariable=self.pnl_var,
            bootstyle="info",
            font=("Helvetica", 16, "bold")
        )
        pnl_label.pack(pady=(5, 5))

        # Meter (values updated in update_account_info)
        self.pnl_meter = ttkb.Meter(
            master=account_group,
            metersize=245,
            amountused=0,
            amounttotal=1,
            metertype="semi",
            bootstyle="secondary",
            subtext="N/A"
        )
        self.pnl_meter.pack()

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

        if active_acc is not None:
            acc_id = int(active_acc.name)

            # Load account and positions
            accounts_df = persist.load_accounts()
            acc_row = accounts_df.loc[acc_id]
            cash_value = float(acc_row["cash"])
            realized_pnl = float(acc_row.get("realized_pnl", 0.0))

            positions_df = persist.load_positions(acc_id)
            unrealized_pnl_total = positions_df["unrealized_pnl"].sum() if not positions_df.empty else 0.0

            # Total P&L = realized + unrealized
            pnl_value = realized_pnl + unrealized_pnl_total

            # Equity = cash + realized P&L + unrealized P&L
            final_equity = cash_value + pnl_value
        else:
            pnl_value = 0.0
            cash_value = float(self.cash_var.get())
            final_equity = cash_value

        # --- Update label ---
        self.pnl_var.set(f"${cash_value:,.2f} Cash")

        # --- Update meter ---
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

    def apply_timeframe_presets(self, timeframe, source_chart=None):
        """Push timeframe-specific training + indicator defaults to one workspace.

        Updates the Strategy tab tied to ``source_chart`` (or the active chart
        when omitted). Called when a chart interval changes or a workspace is
        first created.
        """
        chart = source_chart or self.top_tabs.get_active_chart()
        if chart is None:
            return
        strategy_tab = self.top_tabs.get_strategy_tab_for_chart(chart)
        if strategy_tab is not None:
            strategy_tab.apply_timeframe_presets(timeframe)
    
    
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
                    f"{row['unrealized_pnl']:.2f}"
                )
            )

                     
    def _normalize_candle_df(self, candle_data) -> pd.DataFrame:
        """Normalize a raw broker candle payload (list of dicts) into a
        DataFrame indexed by UTC timestamps and sorted ascending.

        Shared between the primary search path and cross-asset fetches so
        feature builders see the same shape regardless of which workspace
        the candles came from. Returns an empty DataFrame when the payload
        itself is empty; raises ValueError when the payload is non-empty
        but cannot be normalized (missing or unparseable timestamp column)
        so callers can surface the specific failure to the user.
        """
        candle_df = pd.DataFrame(candle_data)
        if candle_df.empty:
            return candle_df

        timestamp_col = None
        for candidate in ("start", "startTime", "date", "timestamp", "time"):
            if candidate in candle_df.columns:
                timestamp_col = candidate
                break
        if timestamp_col is None:
            raise ValueError(
                "Candle data is missing a timestamp field. "
                f"Available fields: {list(candle_df.columns)}"
            )

        candle_df["timestamp"] = pd.to_datetime(
            candle_df[timestamp_col], utc=True, errors="coerce"
        )
        candle_df = candle_df.dropna(subset=["timestamp"])
        if candle_df.empty:
            raise ValueError("Unable to parse candle timestamps from broker response.")

        candle_df.set_index("timestamp", inplace=True)
        candle_df.sort_index(inplace=True)
        return candle_df

    def search(self, show_output=True, workspace=None):
        """Fetch candles for a workspace and return a normalized DataFrame.

        workspace=None  -> use the active workspace (existing behaviour).
        workspace=<tuple from TabbedWorkspaceFrame> -> use that workspace's
            general tab (symbol/dates) and chart (timeframe). This is how
            cross-asset fetches read from an inactive tab without forcing
            the user to switch tabs.

        The chart attached to the chosen workspace is redrawn only when
        show_output is True. Returns an empty DataFrame on any failure
        (and surfaces the failure via a dialog), so callers can simply
        check ``.empty``.
        """
        if workspace is None:
            general_tab = self.top_tabs.get_active_general_tab()
            chart = self.top_tabs.get_active_chart()
        else:
            _, _, chart, general_tab, *_ = workspace

        if general_tab is None or chart is None:
            messagebox.showerror("Internal Error", "Could not resolve target workspace.")
            return pd.DataFrame()

        stock_symbol = general_tab.stock_input.get().strip()
        start_date_obj = general_tab.start_date_input.get_date()
        end_date_obj = general_tab.end_date_input.get_date()
        if not stock_symbol or start_date_obj is None or end_date_obj is None:
            messagebox.showwarning("Input Error", "Please enter a valid stock symbol as query.")
            return pd.DataFrame()

        if not self.controller.is_session_ready():
            messagebox.showwarning(
                "Not connected",
                "Please log in and connect your broker session first."
            )
            return pd.DataFrame()

        try:
            symbol_data = self.controller.broker.get_symbols(query=stock_symbol)
            if not symbol_data:
                print("No data found for:", stock_symbol)
                return pd.DataFrame()
            first_symbol = symbol_data[0]
            candle_key = first_symbol.get("symbolId") or first_symbol.get("conId") or stock_symbol
            candle_data = self.controller.broker.get_candles(
                symbol=candle_key,
                start=start_date_obj,
                end=end_date_obj,
                interval=chart.time_interval,
            )

            try:
                candle_df = self._normalize_candle_df(candle_data)
            except ValueError as parse_err:
                messagebox.showerror("Data Error", str(parse_err))
                return pd.DataFrame()

            if candle_df.empty:
                messagebox.showwarning(
                    "No Data",
                    f"No candle data returned for {stock_symbol} in the selected range."
                )
                return candle_df

            if show_output:
                chart.update_chart(candle_df)
            return candle_df
        except requests.exceptions.HTTPError as err:
            messagebox.showerror("Error", f"HTTP error occurered {err}")
            return pd.DataFrame()
        except Exception as err:
            messagebox.showerror("Error", f"Broker error: {err}")
            return pd.DataFrame()

    
    def is_input_valid_float(self, input, name):
        try:
            float(input)
            return True
        except ValueError:
            messagebox.showerror("Error", f"Please enter a valid {name}")
            return False

    
    def run_strategy(self):
        is_live = self.top_tabs.get_active_chart().live_switch_var.get()
        strategy_tab = self.top_tabs.get_active_strategy_tab()

        signal_logic, strategy_descriptor, warmup_bars = strategy_tab.build_signal_logic()

        if is_live:
            if not hasattr(self, "_live_running") or not self._live_running:
                acc_id = int(self.active_account.name)
                candles = self.top_tabs.get_active_chart().candle_aggregator
                stock_symbol = candles.symbol

                session_id = persist.start_trade_session(
                    acc_id, stock_symbol, "live", strategy_descriptor, strategy_descriptor
                )
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
                    self.render_positions_table()
                    self.update_account_info()

                self._finalize_live = engine.run_live_strategy(
                    candle_source=candles,
                    signal_logic=signal_logic,
                    position_sizer_func=pos_sz.fixed_fraction_position_sizer,
                    position_sizer_param=float(self.top_tabs.get_active_execution_tab().position_slider_value.get()),
                    stop_loss_func=risk.StopLoss.average_true_range_stop if self.top_tabs.get_active_execution_tab().stop_loss_var.get() else None,
                    starting_capital=float(self.cash_var.get()),
                    allow_short=False,
                    slippage=float(self.top_tabs.get_active_execution_tab().slippage_input.get().strip()),
                    fee_rate=float(self.top_tabs.get_active_execution_tab().fee_rate_input.get().strip()),
                    fee_min=float(self.top_tabs.get_active_execution_tab().minimum_fee_input.get().strip()),
                    lot_size=int(self.top_tabs.get_active_execution_tab().lot_size_input.get().strip()),
                    account_id=acc_id,
                    session_id=session_id,
                    ui_callback=_on_live_update,
                    warmup_bars=warmup_bars,
                )

                self._live_running = True
                self.run_strategy_button.config(text="Stop Strategy")
            else:
                acc_id = int(self.active_account.name)
                final_df = self._finalize_live()
                persist.end_trade_session(session_id=self.current_session_id)

                backtest_frame = self.controller.frames[BackTestingResultsFrame]
                backtest_frame.backtest_results = final_df
                backtest_frame.results_chart.results = final_df
                backtest_frame.results_chart.update_chart()
                backtest_frame.render_trade_history()

                last_cash = float(final_df["cash"].iloc[-1])
                self.cash_var.set(last_cash)

                last_realized = float(final_df["pnl"].cumsum().iloc[-1]) if "pnl" in final_df.columns else 0.0
                persist.update_account(
                    account_id=acc_id,
                    cash=last_cash,
                    realized_pnl=last_realized,
                    equity=last_cash + last_realized
                )

                self.update_account_info()
                self._live_running = False
                self.run_strategy_button.config(text="Run Strategy")
                del self._finalize_live
        else:
            # Read all UI values on the main thread before spawning background work
            acc_id = int(self.active_account.name)
            stock_symbol = self.top_tabs.get_active_general_tab().stock_input.get().strip()
            execution_tab = self.top_tabs.get_active_execution_tab()
            position_sizer_param = float(execution_tab.position_slider_value.get())
            stop_loss_enabled = execution_tab.stop_loss_var.get()
            starting_capital = float(self.cash_var.get())
            slippage = float(execution_tab.slippage_input.get().strip())
            fee_rate = float(execution_tab.fee_rate_input.get().strip())
            fee_min = float(execution_tab.minimum_fee_input.get().strip())
            lot_size = int(execution_tab.lot_size_input.get().strip())

            session_id = persist.start_trade_session(
                acc_id, stock_symbol, "backtest", strategy_descriptor, strategy_descriptor
            )
            candle_data = pd.DataFrame(self.search(show_output=False))

            self.run_strategy_button.config(text="Running…", state="disabled")

            def _run_backtest():
                try:
                    results = engine.backtest_strategy(
                        data=candle_data,
                        signal_logic=signal_logic,
                        position_sizer_func=pos_sz.fixed_fraction_position_sizer,
                        position_sizer_param=position_sizer_param,
                        stop_loss_func=risk.StopLoss.average_true_range_stop if stop_loss_enabled else None,
                        starting_capital=starting_capital,
                        allow_short=False,
                        slippage=slippage,
                        fee_rate=fee_rate,
                        fee_min=fee_min,
                        lot_size=lot_size,
                        session_id=session_id,
                    )
                    self.controller.root.after(0, lambda r=results: _finish(r))
                except Exception as e:
                    self.controller.root.after(0, lambda err=e: _on_error(err))

            def _finish(results):
                if not results.empty:
                    backtest_frame = self.controller.frames[BackTestingResultsFrame]
                    backtest_frame.backtest_results = results
                    backtest_frame.populate_backtest_display(results)
                    backtest_frame.results_chart.results = results
                    backtest_frame.results_chart.update_chart()
                    backtest_frame.render_trade_history()
                persist.end_trade_session(session_id=session_id)
                self.run_strategy_button.config(text="Run Strategy", state="normal")

            def _on_error(err):
                messagebox.showerror("Strategy Error", str(err))
                persist.end_trade_session(session_id=session_id)
                self.run_strategy_button.config(text="Run Strategy", state="normal")

            threading.Thread(target=_run_backtest, daemon=True).start()

   
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

        # Cross-asset toggle: flags this workspace as the secondary symbol for
        # strategies that consume cross_asset_bars (e.g. SPY basis for MES).
        # Mutually exclusive with live mode and one-at-a-time across workspaces.
        self.cross_asset_var = tk.BooleanVar(value=False)
        self.cross_asset_toggle = ttkb.Checkbutton(
            self,
            text="Mark as cross-asset",
            variable=self.cross_asset_var,
            command=self.toggle_cross_asset,
            bootstyle="info-round-toggle"
        )
        self.cross_asset_toggle.grid(row=0, column=2, sticky="nsew")

        viewport_frame = ttk.Frame(self)
        viewport_frame.grid(row=0, column=3, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(viewport_frame, text="Visible bars:").pack(side="left", padx=(0, 4))
        self.visible_mode_var = tk.StringVar(value="500")
        self.visible_mode_combo = ttk.Combobox(
            viewport_frame,
            textvariable=self.visible_mode_var,
            values=["500", "1000", "All"],
            width=8,
            state="readonly",
        )
        self.visible_mode_combo.pack(side="left")
        self.visible_mode_combo.bind("<<ComboboxSelected>>", self._on_viewport_change)
        ttk.Button(viewport_frame, text="◀", width=3, command=self._scroll_chart_left).pack(side="left", padx=(6, 2))
        ttk.Button(viewport_frame, text="▶", width=3, command=self._scroll_chart_right).pack(side="left")

        self.candle_chart = cftk_wrap.CandlestickChartNoLabels(self, width = 1075, height = 415)
        self.candle_chart.grid(row=1, column=0, columnspan=5, sticky="nsew")
        
        self.timeframe_options = ["OneMinute", "OneHour", "OneDay", "OneWeek"]
        self.time_interval = "OneDay"
        control_frame = ttk.Frame(self)
        control_frame.grid(row=2, column=0, columnspan=5, sticky="ew")
        control_frame.grid_rowconfigure(0, weight=0)
        for i in range(len(self.timeframe_options)):
            control_frame.grid_columnconfigure(i, weight=1)
            self.grid_columnconfigure(i, weight=1)
            
        self.timeframe_buttons = self.create_segmented_control(
            control_frame, self.timeframe_options, self.time_interval, self.on_timeframe_change
        )
        self.grid_rowconfigure(1, weight=1)
        
        self.tick_queue = None
        self.streamer = None
        self.candle_aggregator = None
        self._poll_job = None
        self._update_job = None
        self._full_df = pd.DataFrame()
        self._view_start = 0
        self._last_rendered_len = None
        self._chart_title = ""
    
    def toggle_live_mode(self):
        if self.live_switch_var.get():
            if self.controller.is_ibkr():
                messagebox.showwarning(
                    "Live mode unavailable",
                    "IBKR live streaming is not implemented yet. "
                    "Use Search to load historical candles."
                )
                self.live_switch_var.set(False)
                return
            # A workspace flagged as cross-asset is treated as a read-only
            # secondary input; live streaming would mutate its candles and
            # contaminate the primary strategy's feature build.
            if self.cross_asset_var.get():
                messagebox.showwarning(
                    "Live mode unavailable",
                    "This workspace is marked as cross-asset. "
                    "Unmark it before enabling live mode."
                )
                self.live_switch_var.set(False)
                return
            self.tick_queue = queue.Queue()
            auth_frame = self.controller.frames[AuthFrame]
            self.streamer = qt_stream.QuestradeStreamer(
                access_token = auth_frame.access_token,
                api_server = auth_frame.api_server,
                tick_queue = self.tick_queue
            )
            stock_symbol = self.controller.frames[TradingStrategyFrame].top_tabs.get_active_general_tab().stock_input.get().strip()
            self.candle_aggregator = tick_processor.CandleAggregator(stock_symbol, "OneMinute")             
            symbol_data = self.controller.broker.get_symbols(query=stock_symbol)
            symbol_id = symbol_data[0]['symbolId']
            for rb in self.timeframe_buttons:
                rb.config(state=tk.DISABLED)
            self.streamer.start_stream(symbol_id)
            self._poll_ticks()
            self.periodically_update_chart()
        else:
            if self.streamer:
                self.streamer.stop_stream()
            if self._poll_job:
                self.after_cancel(self._poll_job)
                self._poll_job = None
            if self._update_job:
                self.after_cancel(self._update_job)
                self._update_job = None
            self.tick_queue = None
            for rb in self.timeframe_buttons:
                rb.config(state=tk.NORMAL)

    def toggle_cross_asset(self):
        """Flip this workspace's cross-asset flag and keep the workspace tabs
        in sync (one-at-a-time, [CA] prefix on the tab label).

        Tk fires the ``command`` after the BooleanVar has already been flipped,
        so ``cross_asset_var.get()`` reflects the *target* state."""
        top_tabs = self.controller.frames[TradingStrategyFrame].top_tabs
        if self.cross_asset_var.get():
            # Block when live: streaming would mutate the bars we want to use
            # as a stable secondary input.
            if self.live_switch_var.get():
                messagebox.showwarning(
                    "Cross-asset unavailable",
                    "Disable live mode before marking this workspace as cross-asset."
                )
                self.cross_asset_var.set(False)
                return
            # Enforce one cross-asset workspace at a time.
            top_tabs.clear_cross_asset_marks_except(self)
            top_tabs.set_cross_asset_prefix_for_chart(self, True)
        else:
            top_tabs.set_cross_asset_prefix_for_chart(self, False)

    def shutdown(self):
        """Gracefully stop live streaming and background jobs."""
        if self.live_switch_var.get():
            # Turn off live mode first
            try:
                self.toggle_live_mode()  # or explicitly stop streamer/aggregator
                print("Live mode disabled before closing chart.")
            except Exception as e:
                print(f"Error disabling live mode: {e}")

        # Cancel any polling jobs
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None

        # Close streamer/aggregator if they exist
        if self.streamer is not None:
            try:
                self.streamer.stop_stream()
            except Exception as e:
                print(f"Error closing streamer: {e}")
            self.streamer = None

        if self.candle_aggregator is not None:
            try:
                self.candle_aggregator.clear_subscribers()
            except Exception as e:
                print(f"Error stopping aggregator: {e}")
            self.candle_aggregator = None

    
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
            
    def _max_draw_bars(self):
        return max(100, self.candle_chart.width - 2 * self.candle_chart.padding)

    def _window_size_from_mode(self):
        mode = self.visible_mode_var.get()
        if mode == "All":
            return None
        return int(mode)

    def _prepare_display_df(self, df):
        self._full_df = df.copy()
        window_size = self._window_size_from_mode()
        if window_size is None:
            self._view_start = 0
        else:
            max_start = max(0, len(self._full_df) - window_size)
            if self._view_start > max_start:
                self._view_start = max_start
        display_df, self._view_start = chart_perf.prepare_ohlc_for_display(
            self._full_df,
            window_size,
            self._view_start,
            self._max_draw_bars(),
        )
        return display_df

    def _on_viewport_change(self, _event=None):
        if self._full_df.empty:
            return
        if self.visible_mode_var.get() != "All":
            window_size = self._window_size_from_mode()
            self._view_start = max(0, len(self._full_df) - window_size)
        self.update_chart(self._full_df, force_full=True)

    def _scroll_chart_left(self):
        if self._full_df.empty or self.visible_mode_var.get() == "All":
            return
        step = max(1, self._window_size_from_mode() // 4)
        self._view_start = max(0, self._view_start - step)
        self.update_chart(self._full_df, force_full=True)

    def _scroll_chart_right(self):
        if self._full_df.empty or self.visible_mode_var.get() == "All":
            return
        window_size = self._window_size_from_mode()
        step = max(1, window_size // 4)
        max_start = max(0, len(self._full_df) - window_size)
        self._view_start = min(max_start, self._view_start + step)
        self.update_chart(self._full_df, force_full=True)

    def convert_data_for_chart(self, df):
        n = len(df)
        if n == 0:
            return []
        idx = range(n)
        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        return list(zip(idx, opens, highs, lows, closes))

    def update_chart(self, df, animate_last_only=False, force_full=False):
        if force_full or not animate_last_only:
            if self.visible_mode_var.get() != "All":
                window_size = self._window_size_from_mode()
                if self._full_df.empty or len(df) != len(self._full_df):
                    self._view_start = max(0, len(df) - window_size)

        display_df = self._prepare_display_df(df)
        if display_df.empty:
            return

        chart_data = self.convert_data_for_chart(display_df)
        title = self.controller.frames[TradingStrategyFrame].top_tabs.get_active_general_tab().stock_input.get().strip()
        self._chart_title = title

        if (
            animate_last_only
            and not force_full
            and self._last_rendered_len == len(display_df)
            and chart_data
            and self.candle_chart.update_last_candle(chart_data[-1], len(chart_data) - 1)
        ):
            return

        self.candle_chart.clear()
        self.candle_chart.timestamps = list(display_df.index)
        self.candle_chart.plot(chart_data, title, animate_last_only)
        self._last_rendered_len = len(display_df)
        
    def periodically_update_chart(self):
        candles_df = self.candle_aggregator.get_candles()
        if not candles_df.empty and self.live_switch_var.get():
            self.update_chart(candles_df, True)
    
        # reschedule only if live mode is still on
        if self.live_switch_var.get():
            self._update_job = self.after(3000, self.periodically_update_chart)
        else:
            self._update_job = None
               
    def create_segmented_control(self, parent, options, default, command=None):
        ind = options.index(default) if default in options else 0
        sg_var = tk.StringVar(value=options[ind])
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
        trading_frame.apply_timeframe_presets(value, source_chart=self)
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
        acc_id = int(self.controller.frames[TradingStrategyFrame].active_account.name)
        trade_session = persist.load_trade_sessions(acc_id).loc[session_id]
        self.results_chart.results = trade_stream
        self.results_chart.stock_symbol = trade_session['symbol'] if not trade_session.empty else ""
        self.results_chart._view_start = 0
        self.results_chart._full_results = pd.DataFrame()
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
        self.stock_symbol = ""
        self._full_results = pd.DataFrame()
        self._view_start = 0
        self.chart = None
        # Show labels toggle
        self.show_label_var = tk.BooleanVar(value=False)
        self.show_label_toggle = ttk.Checkbutton(
            self,
            text="Show data labels",
            variable=self.show_label_var,
            command=self.toggle_show_label
        )
        self.show_label_toggle.grid(row=0, column=0, sticky="nsew")

        viewport_frame = ttk.Frame(self)
        viewport_frame.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(viewport_frame, text="Visible bars:").pack(side="left", padx=(0, 4))
        self.visible_mode_var = tk.StringVar(value="500")
        self.visible_mode_combo = ttk.Combobox(
            viewport_frame,
            textvariable=self.visible_mode_var,
            values=["500", "1000", "All"],
            width=8,
            state="readonly",
        )
        self.visible_mode_combo.pack(side="left")
        self.visible_mode_combo.bind("<<ComboboxSelected>>", self._on_viewport_change)
        ttk.Button(viewport_frame, text="◀", width=3, command=self._scroll_chart_left).pack(side="left", padx=(6, 2))
        ttk.Button(viewport_frame, text="▶", width=3, command=self._scroll_chart_right).pack(side="left")

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
        self.chart.grid(row=1, column=0, columnspan=2, sticky="nsew")
        return self.chart

    def _max_draw_points(self):
        if self.chart is None:
            return 800
        return max(100, self.chart.width - 2 * self.chart.padding)

    def _window_size_from_mode(self):
        mode = self.visible_mode_var.get()
        if mode == "All":
            return None
        return int(mode)

    def _prepare_display_results(self, df):
        self._full_results = df.copy()
        window_size = self._window_size_from_mode()
        if window_size is None:
            self._view_start = 0
        else:
            max_start = max(0, len(self._full_results) - window_size)
            if self._view_start > max_start:
                self._view_start = max_start
        visible, self._view_start = chart_perf.slice_visible_window(
            self._full_results,
            window_size,
            self._view_start,
        )
        return visible

    def _on_viewport_change(self, _event=None):
        if self._full_results.empty:
            return
        if self.visible_mode_var.get() != "All":
            window_size = self._window_size_from_mode()
            self._view_start = max(0, len(self._full_results) - window_size)
        self.update_chart()

    def _scroll_chart_left(self):
        if self._full_results.empty or self.visible_mode_var.get() == "All":
            return
        step = max(1, self._window_size_from_mode() // 4)
        self._view_start = max(0, self._view_start - step)
        self.update_chart()

    def _scroll_chart_right(self):
        if self._full_results.empty or self.visible_mode_var.get() == "All":
            return
        window_size = self._window_size_from_mode()
        step = max(1, window_size // 4)
        max_start = max(0, len(self._full_results) - window_size)
        self._view_start = min(max_start, self._view_start + step)
        self.update_chart()

    def _labels_for_rows(self, df, row_index):
        """Return x-axis labels aligned with ``row_index``; never treat row ids as epoch times."""
        if df is None or df.empty:
            return None

        row_index = pd.Index(row_index)

        if "ts" in df.columns:
            ts = pd.to_datetime(df.loc[row_index, "ts"], errors="coerce")
            if ts.notna().any():
                if len(ts) <= 1 or ts.dropna().nunique() > 1:
                    return list(ts)

        subset_index = df.loc[row_index].index
        if isinstance(subset_index, pd.DatetimeIndex):
            return list(subset_index)

        if pd.api.types.is_integer_dtype(subset_index):
            return None

        try:
            parsed = pd.to_datetime(subset_index, errors="coerce")
            if parsed.notna().all():
                return list(parsed)
        except Exception:
            pass
        return None

    def _series_for_chart(self, y_values, df, row_index):
        """Return y values and matching timestamps, downsampled when needed."""
        max_points = self._max_draw_points()
        raw_labels = self._labels_for_rows(df, row_index)
        if len(y_values) <= max_points:
            return y_values, raw_labels
        y_out, idx_out = chart_perf.downsample_line_with_index(y_values, raw_labels, max_points)
        if idx_out is not None:
            idx_out = list(pd.to_datetime(idx_out, errors="coerce"))
        return y_out, idx_out

    def _extract_timestamps(self, index):
        """Convert labels to datetimes; ignore plain integer indices (row ids)."""
        if index is None:
            return None
        try:
            idx = pd.Index(index)
            if pd.api.types.is_integer_dtype(idx):
                return None
            return list(pd.to_datetime(index, errors="coerce"))
        except Exception:
            return None

    def update_chart(self, *args):
        if self.results.empty:
            return

        if self.chart is None:
            self.create_chart(show_labels=self.show_label)
        else:
            self.chart.show_labels = self.show_label

        if self.visible_mode_var.get() != "All":
            window_size = self._window_size_from_mode()
            if self._full_results.empty or len(self.results) != len(self._full_results):
                self._view_start = max(0, len(self.results) - window_size)

        selected = self.result_var.get()
        display_results = self._prepare_display_results(self.results)
        chart = self.chart
        chart.title = self.stock_symbol
        series_list = self.controller.frames[BackTestingResultsFrame].result_settings_tab.selected_series

        if series_list:
            datasets = []
            common_valid = pd.Series(True, index=display_results.index)
            for series in series_list:
                if series in display_results.columns:
                    common_valid &= pd.to_numeric(display_results[series], errors="coerce").notna()

            filtered = display_results.loc[common_valid]
            chart_timestamps = None

            for series in series_list:
                if series in filtered.columns:
                    numeric = pd.to_numeric(filtered[series], errors="coerce").dropna()
                    y_values = numeric.tolist()
                    if y_values:
                        y_values, timestamps = self._series_for_chart(
                            y_values, filtered, numeric.index
                        )
                        if chart_timestamps is None:
                            chart_timestamps = timestamps
                        datasets.append({
                            'data': y_values,
                            'label': series
                        })

            if datasets:
                chart.timestamps = chart_timestamps
                chart.clear()
                chart.plot(datasets)
        else:
            numeric = pd.to_numeric(display_results[selected], errors="coerce").dropna()
            y_values = numeric.tolist()
            if y_values:
                y_values, timestamps = self._series_for_chart(
                    y_values, display_results, numeric.index
                )
                chart.timestamps = timestamps
                chart.clear()
                chart.plot(y_values)

                    

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
        today = datetime.date.today()
        prev_month = 12 if today.month == 1 else today.month - 1
        prev_year = today.year - 1 if today.month == 1 else today.year
        prev_month_last_day = calendar.monthrange(prev_year, prev_month)[1]
        one_month_prior = datetime.date(
            prev_year,
            prev_month,
            min(today.day, prev_month_last_day)
        )
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
            bootstyle="info",
            dateformat="%Y-%m-%d"
        )
        self.start_date_input.set_date(one_month_prior)
        self.start_date_input.pack(fill="x", pady=2)

        # End date
        self.end_date_label = ttk.Label(self.content, text="End Date:")
        self.end_date_label.pack(anchor="w", pady=(5, 2))

        self.end_date_input = DateEntry(
            self.content,
            bootstyle="info",
            dateformat="%Y-%m-%d"
        )
        self.end_date_input.set_date(today)
        self.end_date_input.pack(fill="x", pady=2)


class StrategyCollapsibleFrame(CollapsibleFrame):
    """
    Strategy panel for the stacked meta-learner workflow.

    The panel hosts:
      - Base Strategies picker (flat StrategySection)
      - Training Parameters dialog
      - Train button
      - Model Version selector (filtered to type=stacked_meta_learner)
      - Cost-aware Training Results display

    ``build_signal_logic`` is the integration point with the backtest and
    live engines; it returns the meta-learner adapter as a single callable.

    Training and indicator defaults are keyed by chart timeframe; see
    ``timeframe_presets.py``. ``apply_timeframe_presets`` is invoked when the
    user switches interval or opens a new workspace tab.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, title="Strategy")
        self.controller = controller

        self.meta_model_result = None
        self._current_timeframe = tf_presets.DEFAULT_TIMEFRAME

        initial_training = tf_presets.get_training_presets(self._current_timeframe)
        initial_behavioral = tf_presets.get_behavioral_presets(self._current_timeframe)

        # Training params backed by Tk variables so the dialog edits persist.
        self._training_vars = {
            "horizon": tk.IntVar(value=initial_training["horizon"]),
            "up_barrier_atr": tk.DoubleVar(value=initial_training["up_barrier_atr"]),
            "down_barrier_atr": tk.DoubleVar(value=initial_training["down_barrier_atr"]),
            "vertical_bars": tk.IntVar(value=initial_training["vertical_bars"]),
            "embargo": tk.IntVar(value=initial_training["embargo"]),
            "calibration": tk.StringVar(value=initial_training["calibration"]),
            "decision_threshold": tk.DoubleVar(value=initial_training["decision_threshold"]),
            "n_splits": tk.IntVar(value=initial_training["n_splits"]),
            "learning_rate": tk.DoubleVar(value=initial_training["learning_rate"]),
            "cost_bp": tk.DoubleVar(value=initial_training["cost_bp"]),
            "atr_window": tk.IntVar(value=initial_training["atr_window"]),
        }

        self._behavioral_vars = {
            "enable_behavioral": tk.BooleanVar(value=initial_behavioral["enable_behavioral"]),
            "enable_behavioral_gate": tk.BooleanVar(value=initial_behavioral["enable_behavioral_gate"]),
            "behavioral_in_direction_model": tk.BooleanVar(
                value=initial_behavioral.get("behavioral_in_direction_model", False)
            ),
            "enable_meta_label": tk.BooleanVar(value=initial_behavioral.get("enable_meta_label", False)),
            "meta_threshold": tk.DoubleVar(value=initial_behavioral.get("meta_threshold", 0.55)),
            "enable_behavioral_consensus": tk.BooleanVar(
                value=initial_behavioral.get("enable_behavioral_consensus", True)
            ),
            "enable_behavioral_anchoring": tk.BooleanVar(
                value=initial_behavioral.get("enable_behavioral_anchoring", True)
            ),
            "enable_behavioral_flow": tk.BooleanVar(
                value=initial_behavioral.get("enable_behavioral_flow", True)
            ),
            "gate_learn_on_train": tk.BooleanVar(value=initial_behavioral.get("gate_learn_on_train", True)),
            "or_minutes": tk.IntVar(value=initial_behavioral["or_minutes"]),
            "ofi_bar_window": tk.IntVar(value=initial_behavioral["ofi_bar_window"]),
            "consensus_std_chop_threshold": tk.DoubleVar(
                value=initial_behavioral["consensus_std_chop_threshold"]
            ),
            "consensus_std_herd_threshold": tk.DoubleVar(
                value=initial_behavioral["consensus_std_herd_threshold"]
            ),
            "consensus_mean_herd_threshold": tk.DoubleVar(
                value=initial_behavioral["consensus_mean_herd_threshold"]
            ),
            "chop_momentum_threshold": tk.DoubleVar(
                value=initial_behavioral["chop_momentum_threshold"]
            ),
            "gate_opening_threshold_bump": tk.DoubleVar(
                value=initial_behavioral["gate_opening_threshold_bump"]
            ),
            "gate_chop_threshold_bump": tk.DoubleVar(
                value=initial_behavioral["gate_chop_threshold_bump"]
            ),
            "gate_opening_block": tk.BooleanVar(value=initial_behavioral["gate_opening_block"]),
            "meta_learning_rate": tk.DoubleVar(value=initial_behavioral.get("meta_learning_rate", 0.05)),
            "meta_max_iter": tk.IntVar(value=initial_behavioral.get("meta_max_iter", 150)),
            "meta_max_depth": tk.IntVar(value=initial_behavioral.get("meta_max_depth", 4)),
            "meta_l2_regularization": tk.DoubleVar(
                value=initial_behavioral.get("meta_l2_regularization", 0.1)
            ),
        }

        self._build_strategy_panel()

    def _build_strategy_panel(self):
        self.scrolled_panel = ScrolledFrame(self.content, autohide=True, bootstyle="round")
        self.scrolled_panel.pack(fill="both", expand=True)
        panel = self.scrolled_panel

        # --- Base Strategies picker ---
        strategy_list = list(strategies.trading_strategies.keys())
        self.base_section = stb.StrategySection(
            panel,
            title="Base Strategies",
            strategies=strategy_list,
            strategy_param_getter=self.get_strategy_params,
        )
        self.base_section.pack(fill="x", pady=5)

        # --- Behavioral features / gate ---
        behavioral_frame = ttk.LabelFrame(panel, text="Behavioral")
        behavioral_frame.pack(fill="x", padx=5, pady=5)

        toggles = ttk.Frame(behavioral_frame)
        toggles.pack(fill="x", padx=5, pady=(4, 2))
        ttk.Checkbutton(
            toggles,
            text="Behavioral features",
            variable=self._behavioral_vars["enable_behavioral"],
            command=self._on_behavioral_features_toggle,
        ).pack(anchor="w")
        self._behavioral_gate_cb = ttk.Checkbutton(
            toggles,
            text="Behavioral gate (learned; off when meta-label on)",
            variable=self._behavioral_vars["enable_behavioral_gate"],
            command=self._update_behavioral_status_label,
        )
        self._behavioral_gate_cb.pack(anchor="w")
        self._meta_label_cb = ttk.Checkbutton(
            toggles,
            text="Meta-label filter",
            variable=self._behavioral_vars["enable_meta_label"],
            command=self._on_meta_label_toggle,
        )
        self._meta_label_cb.pack(anchor="w")

        beh_btn_row = ttk.Frame(behavioral_frame)
        beh_btn_row.pack(fill="x", padx=5, pady=(0, 4))
        self._behavioral_b_btn = ttk.Button(
            beh_btn_row,
            text="B",
            width=3,
            bootstyle=INFO,
            command=self.open_behavioral_param_dialog,
        )
        self._behavioral_b_btn.pack(side="left")
        ttk.Label(
            beh_btn_row,
            text="Advanced behavioral params",
        ).pack(side="left", padx=(6, 0))

        self.behavioral_status_label = ttk.Label(
            behavioral_frame,
            text="Behavioral: ---",
            anchor="w",
            justify="left",
            wraplength=220,
        )
        self.behavioral_status_label.pack(fill="x", padx=10, pady=(0, 4))
        self._sync_behavioral_ui_state()

        # --- Train + Params button row ---
        btn_row = ttk.Frame(panel)
        btn_row.pack(fill="x", pady=5)

        ttk.Button(
            btn_row, text="P", width=3, bootstyle=INFO,
            command=self.open_param_dialog,
        ).pack(side="left", padx=(5, 5))
        ttk.Button(
            btn_row, text="Train Model",
            command=self.on_train_model,
        ).pack(side="left")

        # --- Model Version Selector ---
        version_row = ttk.Frame(panel)
        version_row.pack(fill="x", pady=5)

        ttk.Label(version_row, text="Model Version:", width=12, anchor="w").pack(side="left", padx=(5, 5))

        self.version_var = tk.StringVar()
        self.version_dropdown = ttk.Combobox(
            version_row,
            textvariable=self.version_var,
            state="readonly",
            width=25,
        )
        self.version_dropdown.pack(side="left", padx=(0, 5))
        self.version_dropdown.bind("<<ComboboxSelected>>", self.on_version_selected)

        # --- Training Results ---
        self.results_frame = ttk.LabelFrame(panel, text="Training Results")
        self.results_frame.pack(fill="x", pady=5)

        # Metrics laid out as one row per metric inside a grid so we always fit
        # within the narrow sidebar width regardless of value length: the metric
        # name is pinned to the left, the value to the right, and the row
        # stretches to whatever width the LabelFrame happens to be.
        self.result_labels = {}
        metric_keys = [
            ("trade_rate", "Trade rate"),
            ("avg_edge_bp", "Avg edge (bp)"),
            ("hit_rate", "Hit rate"),
            ("brier", "Brier"),
            ("calibration_mae", "Calib MAE"),
            ("accuracy", "Accuracy"),
        ]
        metrics_block = ttk.Frame(self.results_frame)
        metrics_block.pack(fill="x", padx=5, pady=2)
        metrics_block.columnconfigure(0, weight=1)
        metrics_block.columnconfigure(1, weight=0)
        for i, (key, label_text) in enumerate(metric_keys):
            ttk.Label(metrics_block, text=label_text, anchor="w").grid(
                row=i, column=0, sticky="ew", padx=(5, 4), pady=1
            )
            value_lbl = ttk.Label(metrics_block, text="---", anchor="e")
            value_lbl.grid(row=i, column=1, sticky="e", padx=(4, 5), pady=1)
            self.result_labels[key] = value_lbl

        # "Trained on" describes the saved model's training context (primary
        # symbol/timeframe/date range). Filled in from artifact metadata when a
        # version is selected, or from the current workspace when training runs.
        # wraplength lets the long combined string flow onto a second line
        # instead of clipping against the sidebar's right edge.
        self.trained_on_label = ttk.Label(
            self.results_frame,
            text="Trained on: ---",
            anchor="w",
            justify="left",
            wraplength=220,
        )
        self.trained_on_label.pack(fill="x", padx=10, pady=(6, 0))

        # Cross-asset status: tells the user whether the last training run used a
        # cross-asset secondary feed and how many bars overlapped after alignment.
        # Stays blank until on_train_model populates it via show_training_results.
        self.cross_asset_status_label = ttk.Label(
            self.results_frame,
            text="Cross-asset: none",
            anchor="w",
            justify="left",
            wraplength=220,
        )
        self.cross_asset_status_label.pack(fill="x", padx=10, pady=(0, 2))

        self.behavioral_detail_label = ttk.Label(
            self.results_frame,
            text="",
            anchor="w",
            justify="left",
            wraplength=220,
        )
        self.behavioral_detail_label.pack(fill="x", padx=10, pady=(0, 4))

        # Populate model versions only after result labels are initialized,
        # because selection can immediately trigger result rendering.
        self.populate_version_selector()

    # ------------------------------------------------------------------
    # Timeframe-aware defaults (see timeframe_presets.py)
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_preset_to_vars(preset: dict, var_map: dict) -> None:
        for key, var in var_map.items():
            if key not in preset:
                continue
            value = preset[key]
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.StringVar):
                var.set(str(value))
            elif isinstance(var, tk.DoubleVar):
                var.set(float(value))
            else:
                var.set(int(value))

    def apply_timeframe_presets(self, timeframe: str) -> None:
        """Load training + behavioral + indicator defaults for ``timeframe``."""
        tf = tf_presets.normalize_timeframe(timeframe)
        self._current_timeframe = tf

        self._apply_preset_to_vars(tf_presets.get_training_presets(tf), self._training_vars)
        self._apply_preset_to_vars(tf_presets.get_behavioral_presets(tf), self._behavioral_vars)
        self._sync_behavioral_ui_state()

        if hasattr(self, "base_section"):
            self.base_section.apply_indicator_presets(
                tf_presets.get_all_indicator_presets(tf)
            )

    def _collect_behavioral_params(self) -> dict:
        params = {k: var.get() for k, var in self._behavioral_vars.items()}
        if not params.get("enable_behavioral", False):
            params["enable_behavioral_gate"] = False
            params["enable_meta_label"] = False
        if params.get("enable_meta_label"):
            params["enable_behavioral_gate"] = False
        return params

    def _on_meta_label_toggle(self) -> None:
        if self._behavioral_vars["enable_meta_label"].get():
            if not self._behavioral_vars["enable_behavioral"].get():
                self._behavioral_vars["enable_meta_label"].set(False)
            else:
                self._behavioral_vars["enable_behavioral_gate"].set(False)
        self._sync_behavioral_ui_state()

    def _on_behavioral_features_toggle(self) -> None:
        if not self._behavioral_vars["enable_behavioral"].get():
            self._behavioral_vars["enable_behavioral_gate"].set(False)
            self._behavioral_vars["enable_meta_label"].set(False)
        self._sync_behavioral_ui_state()

    def _sync_behavioral_ui_state(self) -> None:
        """Gate and meta-label require behavioral features; gate excludes meta-label."""
        features_on = bool(self._behavioral_vars["enable_behavioral"].get())
        meta_on = bool(self._behavioral_vars["enable_meta_label"].get())
        widget_state = "normal" if features_on else "disabled"

        if hasattr(self, "_behavioral_gate_cb"):
            gate_state = "normal" if features_on and not meta_on else "disabled"
            self._behavioral_gate_cb.config(state=gate_state)
        if hasattr(self, "_meta_label_cb"):
            self._meta_label_cb.config(state=widget_state)
        if hasattr(self, "_behavioral_b_btn"):
            self._behavioral_b_btn.config(state=widget_state)

        if not features_on:
            self._behavioral_vars["enable_behavioral_gate"].set(False)
            self._behavioral_vars["enable_meta_label"].set(False)
        if meta_on:
            self._behavioral_vars["enable_behavioral_gate"].set(False)

        self._update_behavioral_status_label()

    def _update_behavioral_status_label(self) -> None:
        if not hasattr(self, "behavioral_status_label"):
            return
        if not self._behavioral_vars["enable_behavioral"].get():
            self.behavioral_status_label.config(
                text=f"Behavioral: off ({self._current_timeframe})",
            )
            return
        gate = "on" if self._behavioral_vars["enable_behavioral_gate"].get() else "off"
        meta = "on" if self._behavioral_vars["enable_meta_label"].get() else "off"
        or_min = self._behavioral_vars["or_minutes"].get()
        meta_t = self._behavioral_vars["meta_threshold"].get()
        self.behavioral_status_label.config(
            text=(
                f"Behavioral: features on | gate {gate} | meta {meta} "
                f"(t={meta_t:.2f}) | OR {or_min}m ({self._current_timeframe})"
            ),
        )

    def _hydrate_behavioral_from_inference_params(self, inference_params: dict) -> None:
        """Sync behavioral UI from a loaded model's saved inference params."""
        if not inference_params:
            return
        subset = {k: inference_params[k] for k in self._behavioral_vars if k in inference_params}
        if subset:
            self._apply_preset_to_vars(subset, self._behavioral_vars)
        self._sync_behavioral_ui_state()

    # ------------------------------------------------------------------
    # Default per-strategy parameters surfaced by the StrategySection picker.
    # ------------------------------------------------------------------
    def get_strategy_params(self, name):
        return tf_presets.get_indicator_presets(self._current_timeframe, name)

    # ------------------------------------------------------------------
    # Version selector
    # ------------------------------------------------------------------
    def _stacked_versions(self):
        """Return only persisted versions whose metadata advertises type=stacked_meta_learner."""
        out = []
        for v in ml_persist.list_versions():
            try:
                paths = ml_persist.build_paths(v)
                with open(paths["metadata"], "r") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            if meta.get("type") == "stacked_meta_learner":
                out.append(v)
        return out

    def populate_version_selector(self):
        versions = self._stacked_versions()
        self.version_dropdown["values"] = versions
        if versions:
            self.version_var.set(versions[-1])
            self.on_version_selected()
        else:
            self.version_var.set("")

    def on_version_selected(self, event=None):
        selected_version = self.version_var.get()
        if not selected_version:
            return
        try:
            self.meta_model_result = ml_persist.load_artifacts(selected_version)
        except FileNotFoundError:
            self.meta_model_result = None
            return

        # Hydrate the status labels from the saved training context. Older
        # artifacts (trained before Option C landed) simply lack the field;
        # .get() returns {} and the labels fall back to their default text.
        ctx = self.meta_model_result.get("training_context") or {}
        ca_info = None
        if ctx.get("cross_asset_symbol"):
            ca_info = {
                "symbol": ctx["cross_asset_symbol"],
                "aligned_bars": ctx.get("cross_asset_aligned_bars"),
                # primary_bars absent on load: show "trained with N aligned bars"
            }
        self.show_training_results(
            self.meta_model_result.get("metrics", {}),
            cross_asset_info=ca_info,
            training_context=ctx,
            artifact=self.meta_model_result,
        )
        self._hydrate_behavioral_from_inference_params(
            self.meta_model_result.get("inference_params", {})
        )

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def _collect_training_params(self):
        params = {k: var.get() for k, var in self._training_vars.items()}
        params.update(self._collect_behavioral_params())
        params["base_strategies"] = self.base_section.serialize()
        return params

    def on_train_model(self):
        params = self._collect_training_params()
        if not params["base_strategies"]:
            messagebox.showwarning(
                "Train Model",
                "Add at least one base strategy before training the meta-learner.",
            )
            return

        ts_frame = self.controller.frames[TradingStrategyFrame]
        top_tabs = ts_frame.top_tabs

        primary_general = top_tabs.get_active_general_tab()
        primary_chart = top_tabs.get_active_chart()
        if primary_general is None or primary_chart is None:
            messagebox.showerror("Train Model", "No active workspace.")
            return
        primary_symbol = primary_general.stock_input.get().strip()

        # Cross-asset detection runs BEFORE any network calls so we can surface
        # a clear validation error without burning a broker fetch.
        ca_entry = top_tabs.get_cross_asset_workspace()
        ca_symbol = None
        if ca_entry is not None:
            _, _, ca_chart, ca_general, *_ = ca_entry
            ca_symbol = ca_general.stock_input.get().strip()

            if not ca_symbol:
                messagebox.showwarning(
                    "Train Model",
                    "Cross-asset workspace has no symbol. Enter one or unmark "
                    "cross-asset before training.",
                )
                return

            # Self-reference would collapse the basis z-score to a constant
            # (log(price/price) == 0), giving the model a useless feature.
            if ca_symbol.upper() == primary_symbol.upper():
                messagebox.showwarning(
                    "Train Model",
                    f"Cross-asset workspace references the same symbol as the primary "
                    f"('{primary_symbol}'). Change the cross-asset symbol or unmark "
                    f"cross-asset before training.",
                )
                return

            # Different timeframes would produce a sparse intersection and a
            # basis series full of NaNs; force the user to match them.
            if ca_chart.time_interval != primary_chart.time_interval:
                messagebox.showwarning(
                    "Train Model",
                    f"Cross-asset timeframe ({ca_chart.time_interval}) must match the "
                    f"primary timeframe ({primary_chart.time_interval}). Switch "
                    f"timeframes or unmark cross-asset before training.",
                )
                return

        try:
            df = ts_frame.search(show_output=False)
        except Exception as e:
            messagebox.showerror("Training failed", f"Could not fetch primary candles: {e}")
            return
        if df.empty:
            # search() already surfaced its own dialog; abort silently.
            return

        cross_asset_bars = None
        cross_asset_status = None
        if ca_entry is not None:
            try:
                cross_asset_bars = ts_frame.search(show_output=False, workspace=ca_entry)
            except Exception as e:
                messagebox.showerror(
                    "Training failed",
                    f"Could not fetch cross-asset candles: {e}",
                )
                return
            if cross_asset_bars.empty:
                return

            aligned_count = len(df.index.intersection(cross_asset_bars.index))
            cross_asset_status = {
                "symbol": ca_symbol,
                "primary_bars": len(df),
                "ca_bars": len(cross_asset_bars),
                "aligned_bars": aligned_count,
            }

            # Activate the basis z-score microstructure feature for this run
            # and persist the choice in inference_params.
            params["enable_basis"] = True

        # Snapshot of the training context. Persisted with the artifact so a
        # future inference run can detect symbol / timeframe / CA-symbol drift
        # against the current workspace. Today it drives the status labels;
        # item 4 (and an eventual strict-mode flag) will use it to validate.
        training_context = {
            "primary_symbol": primary_symbol,
            "primary_timeframe": primary_chart.time_interval,
            "train_start": primary_general.start_date_input.get_date().isoformat(),
            "train_end": primary_general.end_date_input.get_date().isoformat(),
            "cross_asset_symbol": ca_symbol,  # None if no CA workspace
            "cross_asset_aligned_bars": (
                cross_asset_status["aligned_bars"] if cross_asset_status else None
            ),
        }
        params["training_context"] = training_context

        try:
            model = train_stacked_meta_learner(
                df, params, cross_asset_bars=cross_asset_bars
            )
        except Exception as e:
            messagebox.showerror("Training failed", str(e))
            return

        self.meta_model_result = model
        self.show_training_results(
            model.get("metrics", {}),
            cross_asset_info=cross_asset_status,
            training_context=training_context,
            artifact=model,
        )
        self.populate_version_selector()
        if model.get("version"):
            self.version_var.set(model["version"])
        self._hydrate_behavioral_from_inference_params(model.get("inference_params", {}))

    def show_training_results(self, metrics, cross_asset_info=None, training_context=None, artifact=None):
        """Render metrics + training-context labels for either a just-trained
        model (``cross_asset_info`` carries the live aligned-bar counts) or a
        loaded artifact (``cross_asset_info`` may carry only the saved
        ``aligned_bars`` from training). ``training_context`` populates the
        "Trained on:" header line. ``artifact`` supplies regime/meta/OR detail."""
        for key, label in self.result_labels.items():
            value = metrics.get(key)
            if value is None:
                label.config(text="---")
            elif isinstance(value, float):
                label.config(text=f"{value:.4f}")
            else:
                label.config(text=str(value))

        if hasattr(self, "trained_on_label"):
            if training_context:
                symbol = training_context.get("primary_symbol") or "?"
                tf = training_context.get("primary_timeframe") or "?"
                start = training_context.get("train_start")
                end = training_context.get("train_end")
                date_part = f" ({start}..{end})" if start and end else ""
                self.trained_on_label.config(text=f"Trained on: {symbol} {tf}{date_part}")
            else:
                self.trained_on_label.config(text="Trained on: ---")

        if hasattr(self, "cross_asset_status_label"):
            if cross_asset_info is None:
                self.cross_asset_status_label.config(text="Cross-asset: none")
            else:
                symbol = cross_asset_info.get("symbol") or "?"
                aligned = cross_asset_info.get("aligned_bars")
                primary = cross_asset_info.get("primary_bars")
                if primary:
                    # Live training run: we know the denominator, so show the
                    # alignment ratio so the user can spot a poor pairing fast.
                    pct = (100.0 * aligned / primary) if aligned is not None else 0.0
                    text = (
                        f"Cross-asset: {symbol} | aligned bars "
                        f"{aligned}/{primary} ({pct:.1f}%)"
                    )
                elif aligned is not None:
                    # Loaded artifact: only the training-time aligned count was
                    # saved; no denominator survives so render without the pct.
                    text = f"Cross-asset: {symbol} | trained with {aligned} aligned bars"
                else:
                    text = f"Cross-asset: {symbol}"
                self.cross_asset_status_label.config(text=text)

        if hasattr(self, "behavioral_detail_label"):
            lines = []
            art = artifact or {}
            or_cov = art.get("or_coverage_pct")
            if or_cov is not None:
                try:
                    if or_cov == or_cov:
                        lines.append(f"OR coverage: {100.0 * float(or_cov):.1f}%")
                except (TypeError, ValueError):
                    pass
            meta_block = art.get("meta_label") or {}
            meta_m = meta_block.get("metrics") or {}
            if meta_m.get("meta_train_rows") is not None:
                lines.append(f"Meta train rows: {meta_m['meta_train_rows']}")
            if metrics.get("meta_positive_rate") is not None:
                lines.append(f"Meta positive rate: {metrics['meta_positive_rate']:.3f}")
            by_regime = art.get("metrics_by_regime") or {}
            if by_regime:
                snippets = []
                for name in ("opening", "chop", "herding", "neutral"):
                    if name not in by_regime:
                        continue
                    r = by_regime[name]
                    edge = r.get("avg_edge_bp")
                    if edge is None or (isinstance(edge, float) and edge != edge):
                        continue
                    snippets.append(f"{name} {edge:+.1f}bp")
                if snippets:
                    lines.append("Regime edge: " + ", ".join(snippets))
            self.behavioral_detail_label.config(
                text="\n".join(lines) if lines else "",
            )

    # ------------------------------------------------------------------
    # Param dialog
    # ------------------------------------------------------------------
    def open_param_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Training Parameters")
        dialog.grab_set()

        rows = [
            ("Horizon (bars)", "horizon", "int"),
            ("Up barrier (xATR)", "up_barrier_atr", "float"),
            ("Down barrier (xATR)", "down_barrier_atr", "float"),
            ("Vertical barrier (bars)", "vertical_bars", "int"),
            ("Embargo (bars)", "embargo", "int"),
            ("Calibration", "calibration", "calibration"),
            ("Decision threshold", "decision_threshold", "float"),
            ("CV splits", "n_splits", "int"),
            ("Learning rate", "learning_rate", "float"),
            ("Round-trip cost (bp)", "cost_bp", "float"),
            ("ATR window", "atr_window", "int"),
        ]

        for i, (label_text, var_key, kind) in enumerate(rows):
            ttk.Label(dialog, text=label_text).grid(row=i, column=0, sticky="w", padx=10, pady=3)
            if kind == "calibration":
                widget = ttk.Combobox(
                    dialog,
                    textvariable=self._training_vars[var_key],
                    values=["none", "platt", "isotonic"],
                    state="readonly",
                    width=12,
                )
            else:
                widget = ttk.Entry(dialog, textvariable=self._training_vars[var_key], width=14)
            widget.grid(row=i, column=1, sticky="w", padx=10, pady=3)

        ttk.Button(dialog, text="Close", command=dialog.destroy).grid(
            row=len(rows), column=0, columnspan=2, pady=10
        )

    def open_behavioral_param_dialog(self):
        if not self._behavioral_vars["enable_behavioral"].get():
            return

        dialog = tk.Toplevel(self)
        dialog.title("Behavioral Parameters")
        dialog.grab_set()

        feature_rows = [
            ("Opening range (minutes)", "or_minutes", "int"),
            ("OFI bar window", "ofi_bar_window", "int"),
            ("Chop consensus std threshold", "consensus_std_chop_threshold", "float"),
            ("Herd consensus std threshold", "consensus_std_herd_threshold", "float"),
            ("Herd consensus mean threshold", "consensus_mean_herd_threshold", "float"),
            ("Chop momentum threshold", "chop_momentum_threshold", "float"),
        ]
        group_rows = [
            ("Consensus feature group", "enable_behavioral_consensus", "bool"),
            ("Anchoring / OR group", "enable_behavioral_anchoring", "bool"),
            ("Flow / divergence group", "enable_behavioral_flow", "bool"),
            ("Include behavioral in direction model", "behavioral_in_direction_model", "bool"),
        ]
        meta_rows = [
            ("Meta-label threshold", "meta_threshold", "float"),
            ("Meta learning rate", "meta_learning_rate", "float"),
            ("Meta max iter", "meta_max_iter", "int"),
            ("Meta max depth", "meta_max_depth", "int"),
            ("Meta L2 regularization", "meta_l2_regularization", "float"),
        ]
        gate_rows = [
            ("Opening gate threshold bump", "gate_opening_threshold_bump", "float"),
            ("Chop gate threshold bump", "gate_chop_threshold_bump", "float"),
        ]

        row_idx = 0
        ttk.Label(dialog, text="Feature thresholds", font=("", 9, "bold")).grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4)
        )
        row_idx += 1
        for label_text, var_key, kind in feature_rows:
            ttk.Label(dialog, text=label_text).grid(
                row=row_idx, column=0, sticky="w", padx=10, pady=3
            )
            if kind == "bool":
                ttk.Checkbutton(dialog, variable=self._behavioral_vars[var_key]).grid(
                    row=row_idx, column=1, sticky="w", padx=10, pady=3
                )
            else:
                ttk.Entry(dialog, textvariable=self._behavioral_vars[var_key], width=14).grid(
                    row=row_idx, column=1, sticky="w", padx=10, pady=3
                )
            row_idx += 1

        ttk.Label(dialog, text="Feature groups", font=("", 9, "bold")).grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )
        row_idx += 1
        for label_text, var_key, kind in group_rows:
            ttk.Label(dialog, text=label_text).grid(
                row=row_idx, column=0, sticky="w", padx=10, pady=3
            )
            ttk.Checkbutton(dialog, variable=self._behavioral_vars[var_key]).grid(
                row=row_idx, column=1, sticky="w", padx=10, pady=3
            )
            row_idx += 1

        meta_enabled = bool(self._behavioral_vars["enable_meta_label"].get())
        ttk.Label(dialog, text="Meta-label params", font=("", 9, "bold")).grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )
        row_idx += 1
        meta_widgets = []
        for label_text, var_key, kind in meta_rows:
            lbl = ttk.Label(dialog, text=label_text)
            lbl.grid(row=row_idx, column=0, sticky="w", padx=10, pady=3)
            if kind == "bool":
                w = ttk.Checkbutton(dialog, variable=self._behavioral_vars[var_key])
            else:
                w = ttk.Entry(dialog, textvariable=self._behavioral_vars[var_key], width=14)
            w.grid(row=row_idx, column=1, sticky="w", padx=10, pady=3)
            meta_widgets.extend((lbl, w))
            row_idx += 1

        meta_state = "normal" if meta_enabled else "disabled"
        for widget in meta_widgets:
            widget.config(state=meta_state)
        if not meta_enabled:
            ttk.Label(
                dialog,
                text="Enable Meta-label filter to edit meta-label params.",
                foreground="gray",
            ).grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))
            row_idx += 1

        gate_enabled = bool(self._behavioral_vars["enable_behavioral_gate"].get())
        ttk.Label(dialog, text="Gate thresholds", font=("", 9, "bold")).grid(
            row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )
        row_idx += 1
        gate_widgets = []
        for label_text, var_key, _kind in gate_rows:
            lbl = ttk.Label(dialog, text=label_text)
            lbl.grid(row=row_idx, column=0, sticky="w", padx=10, pady=3)
            entry = ttk.Entry(dialog, textvariable=self._behavioral_vars[var_key], width=14)
            entry.grid(row=row_idx, column=1, sticky="w", padx=10, pady=3)
            gate_widgets.extend((lbl, entry))
            row_idx += 1

        block_cb = ttk.Checkbutton(
            dialog,
            text="Block all trades during opening window",
            variable=self._behavioral_vars["gate_opening_block"],
        )
        block_cb.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        gate_widgets.append(block_cb)
        row_idx += 1

        gate_state = "normal" if gate_enabled else "disabled"
        for widget in gate_widgets:
            widget.config(state=gate_state)
        if not gate_enabled:
            ttk.Label(
                dialog,
                text="Enable Behavioral gate to edit gate thresholds.",
                foreground="gray",
            ).grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))
            row_idx += 1

        ttk.Label(
            dialog,
            text=f"Presets keyed to timeframe: {self._current_timeframe}",
        ).grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))
        row_idx += 1

        def _close():
            self._sync_behavioral_ui_state()
            dialog.destroy()

        ttk.Button(dialog, text="Close", command=_close).grid(
            row=row_idx, column=0, columnspan=2, pady=10
        )

    # ------------------------------------------------------------------
    # Engine integration
    # ------------------------------------------------------------------
    # Flip to True once a model is promoted past the PoC phase: drift between
    # the loaded model and the current workspace then becomes a hard refusal
    # instead of a warning. Hard blockers (e.g. missing required cross-asset
    # workspace) refuse the run regardless of this flag.
    STRICT_MODEL_VALIDATION = False

    def _check_model_workspace_compatibility(self, trained, ca_entry):
        """Compare a loaded/trained model against the current workspace.

        Returns ``(blocker_msg, drift_msg)``:

        * ``blocker_msg`` non-None -> hard refusal regardless of
          ``STRICT_MODEL_VALIDATION``; the model cannot run in the current
          configuration (e.g. it requires the basis feature but no
          cross-asset workspace is marked).
        * ``drift_msg`` non-None -> soft drift between the saved training
          context and the current workspace; warn-only today, refused when
          ``STRICT_MODEL_VALIDATION`` is True.
        * Both None -> all clear.
        """
        feature_cols = trained.get("feature_columns") or []
        model_uses_basis = any(str(c).startswith("basis_z_") for c in feature_cols)

        if model_uses_basis and ca_entry is None:
            return (
                "This model has the cross-asset basis feature in its schema. "
                "Mark a workspace as cross-asset before running the strategy, "
                "otherwise every prediction would be NaN-blocked.",
                None,
            )

        ctx = trained.get("training_context") or {}
        expected_primary_symbol = ctx.get("primary_symbol")
        expected_primary_tf = ctx.get("primary_timeframe")
        expected_ca_symbol = ctx.get("cross_asset_symbol")

        ts_frame = self.controller.frames[TradingStrategyFrame]
        top_tabs = ts_frame.top_tabs
        primary_general = top_tabs.get_active_general_tab()
        primary_chart = top_tabs.get_active_chart()
        primary_symbol = (
            primary_general.stock_input.get().strip() if primary_general else ""
        )
        primary_tf = primary_chart.time_interval if primary_chart else ""

        ca_symbol = None
        if ca_entry is not None:
            _, _, _, ca_general, *_ = ca_entry
            ca_symbol = ca_general.stock_input.get().strip()

        drifts = []
        if (
            expected_primary_symbol
            and primary_symbol
            and primary_symbol.upper() != expected_primary_symbol.upper()
        ):
            drifts.append(
                f"Primary symbol differs from training "
                f"(model={expected_primary_symbol}, workspace={primary_symbol})."
            )
        if (
            expected_primary_tf
            and primary_tf
            and primary_tf != expected_primary_tf
        ):
            drifts.append(
                f"Primary timeframe differs "
                f"(model={expected_primary_tf}, workspace={primary_tf})."
            )
        if (
            expected_ca_symbol
            and ca_symbol
            and ca_symbol.upper() != expected_ca_symbol.upper()
        ):
            drifts.append(
                f"Cross-asset symbol differs "
                f"(model={expected_ca_symbol}, workspace={ca_symbol})."
            )
        if expected_ca_symbol and ca_entry is None and not model_uses_basis:
            # Edge case: training context recorded a CA pairing but the
            # feature didn't actually land in the schema (e.g. enable_basis
            # was off at training time). Surface as drift, not blocker.
            drifts.append(
                f"Model context recorded cross-asset={expected_ca_symbol} but "
                "no cross-asset workspace is marked."
            )

        drift_msg = "\n".join(drifts) if drifts else None
        return (None, drift_msg)

    def build_signal_logic(self):
        """Return ``(signal_logic, strategy_descriptor, warmup_bars)`` for the engine.

        Cross-asset bars (when the marked CA workspace exists) are fetched at
        build time and captured in the returned closure so the engine never
        has to know about secondary feeds. Compatibility between the loaded
        model and the current workspace is validated up front: hard blockers
        always refuse, drift warnings warn-or-block based on
        ``STRICT_MODEL_VALIDATION``.

        Falls back to a no-op signal_logic on any refusal so the engine still
        sees a well-formed callable and the run completes cleanly.
        """

        def _empty_logic():
            def _empty(df: pd.DataFrame) -> pd.DataFrame:
                return pd.DataFrame(index=df.index)

            return _empty, {"type": "stacked_meta_learner", "version": None}, 0

        trained = self.meta_model_result
        if trained is None:
            messagebox.showwarning(
                "Run Strategy",
                "Train or load a model before running the strategy.",
            )
            return _empty_logic()

        ts_frame = self.controller.frames[TradingStrategyFrame]
        top_tabs = ts_frame.top_tabs
        ca_entry = top_tabs.get_cross_asset_workspace()

        blocker_msg, drift_msg = self._check_model_workspace_compatibility(
            trained, ca_entry
        )
        if blocker_msg:
            messagebox.showerror("Run Strategy", blocker_msg)
            return _empty_logic()
        if drift_msg:
            if self.STRICT_MODEL_VALIDATION:
                messagebox.showerror(
                    "Run Strategy",
                    f"Model / workspace mismatch (strict mode):\n\n{drift_msg}",
                )
                return _empty_logic()
            messagebox.showwarning(
                "Run Strategy",
                f"Model / workspace drift detected:\n\n{drift_msg}\n\n"
                "Proceeding anyway. Set STRICT_MODEL_VALIDATION to True to "
                "refuse drifted runs.",
            )

        # Fetch CA bars at build time so any failure is surfaced before the
        # backtest thread starts; the engine never sees the secondary feed.
        cross_asset_bars = None
        if ca_entry is not None:
            try:
                cross_asset_bars = ts_frame.search(
                    show_output=False, workspace=ca_entry
                )
            except Exception as e:
                messagebox.showerror(
                    "Run Strategy",
                    f"Could not fetch cross-asset bars: {e}",
                )
                return _empty_logic()
            if cross_asset_bars.empty:
                # search() already showed its own "No Data" dialog.
                return _empty_logic()

        params = dict(trained.get("inference_params", trained))
        params.update(self._collect_behavioral_params())

        feature_cols = trained.get("feature_columns") or []
        model_needs_behavioral = any(
            str(c).startswith(
                (
                    "score_consensus_",
                    "dist_open_atr",
                    "dist_or_",
                    "capitulation_",
                    "flow_price_",
                    "consensus_x_",
                    "open_dist_x_",
                    "diverge_x_",
                )
            )
            or str(c)
            in (
                "or_position",
                "or_available",
                "price_accel_atr",
                "upper_wick_ratio",
                "lower_wick_ratio",
            )
            for c in feature_cols
        )
        if model_needs_behavioral and not params.get("enable_behavioral", False):
            messagebox.showwarning(
                "Run Strategy",
                "This model was trained with behavioral features. Re-enable "
                "'Behavioral features' or load a model trained without them.",
            )
            return _empty_logic()

        def signal_logic(df: pd.DataFrame) -> pd.DataFrame:
            return strategies.meta_learner_signals(
                df, trained, params, cross_asset_bars=cross_asset_bars
            )

        ctx = trained.get("training_context") or {}
        descriptor = {
            "type": "stacked_meta_learner",
            "version": trained.get("version"),
            "threshold": trained.get("decision_threshold"),
            "base_strategies": trained.get("base_strategies", []),
            "cross_asset_symbol": ctx.get("cross_asset_symbol"),
            "used_cross_asset_bars": cross_asset_bars is not None,
        }
        warmup_bars = int(trained.get("warmup_bars", 0))
        return signal_logic, descriptor, warmup_bars

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
        self.selected_series = []

        # --- Row 0: Selector + Add Button ---
        selector_row = ttk.Frame(self.content)
        selector_row.pack(fill="x", pady=5)

        self.result_var = tk.StringVar(value=result_headers[0])
        opt = ttk.Combobox(selector_row, values=result_headers,
                           textvariable=self.result_var, state="readonly", width=25)
        opt.pack(side="left", padx=5, fill="x", expand=True)

        add_btn = ttk.Button(selector_row, text="➕", width=2,
                             bootstyle=SUCCESS, command=self.add_series)
        add_btn.pack(side="left", padx=5)

        # --- Row 1: Selected Series List ---
        self.series_frame = ttk.Frame(self.content)
        self.series_frame.pack(fill="x", pady=5)

        # --- Row 2: Result Summary ---
        summary_frame = ttk.LabelFrame(self.content, text="Summary")
        summary_frame.pack(fill="x", pady=5)

        self.result_summary = ttk.Label(summary_frame, text="", anchor="w", justify="left")
        self.result_summary.pack(fill="x", padx=5, pady=5)

        results_summary = {
            "final_equity": 0,
            "profits": 0,
            "returns": 0,
            "sharpe_ratio": 0
        }
        self.result_summary_var = self.populate_result_text(results_summary)

        # --- Row 3: Run New Test Button ---
        action_row = ttk.Frame(self.content)
        action_row.pack(fill="x", pady=10)

        self.run_new_test_button = ttk.Button(action_row, text="Run New Test",
                                              bootstyle=PRIMARY, command=self.run_new_test)
        self.run_new_test_button.pack(anchor="center")
        
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
            active_chart = self.controller.frames[TradingStrategyFrame].top_tabs.get_active_chart()
            time_frame = active_chart.time_interval
            if active_chart.live_switch_var.get():
                time_frame = active_chart.candle_aggregator.time_interval
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
