import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tableview import Tableview

# -----------------------------
# Mock Data
# -----------------------------
sessions = {
    "TRADE-001": {
        "timestamp": "2025-10-22 10:32:15",
        "trades": [
            ["10:32:15", "AAPL", "BUY", 100, 172.50, +125.00],
            ["10:33:10", "AAPL", "SELL", 50, 173.20, +35.00],
        ],
    },
    "TRADE-002": {
        "timestamp": "2025-10-22 11:05:42",
        "trades": [
            ["11:05:42", "TSLA", "BUY", 20, 245.60, -60.00],
            ["11:06:15", "TSLA", "SELL", 20, 246.10, +10.00],
        ],
    },
}

# -----------------------------
# App Setup
# -----------------------------
root = tb.Window(themename="superhero")
root.title("Trading App Demo")
root.geometry("900x600")

# Layout: left = history, right top = treeview, right bottom = chart placeholder
left_frame = tk.Frame(root)
left_frame.pack(side="left", fill="y", padx=10, pady=10)

right_frame = tk.Frame(root)
right_frame.pack(side="right", fill="both", expand=True)

tree_frame = tk.Frame(right_frame)
tree_frame.pack(side="top", fill="both", expand=True)

chart_frame = tk.Frame(right_frame, height=200, bg="#1e1e1e")
chart_frame.pack(side="bottom", fill="both", expand=True)

# -----------------------------
# Trade Stream Treeview
# -----------------------------
columns = [
    {"text": "Time"},
    {"text": "Symbol"},
    {"text": "Side"},
    {"text": "Qty"},
    {"text": "Price"},
    {"text": "PnL"},
]

trade_table = Tableview(
    master=tree_frame,
    coldata=columns,
    rowdata=[],
    paginated=False,
    searchable=False,
    bootstyle="info",
)
trade_table.pack(fill="both", expand=True)

# -----------------------------
# Chart Placeholder
# -----------------------------
chart_label = tk.Label(
    chart_frame,
    text="📈 Chart will be drawn here for the selected session",
    fg="white",
    bg="#1e1e1e",
    font=("TkDefaultFont", 12, "italic"),
)
chart_label.pack(expand=True)

def update_chart_placeholder(session_id):
    chart_label.config(
        text=f"📈 Chart placeholder for {session_id}\n(Imagine price/time plot here)"
    )

# -----------------------------
# Session Cards
# -----------------------------
sf = ScrolledFrame(left_frame, autohide=True, bootstyle="round")
sf.pack(fill="y", expand=True)

def on_session_click(session_id):
    session = sessions[session_id]
    # Clear existing rows
    trade_table.delete_rows()
    # Insert new rows at the end
    trade_table.insert_rows(index="end", rowdata=session["trades"])
    # Update chart placeholder
    update_chart_placeholder(session_id)

def create_session_card(parent, session_id, timestamp):
    card = tk.Frame(parent, bg="#2e3e4e", padx=10, pady=5)
    card.pack(fill="x", pady=5)

    lbl_id = tk.Label(card, text=session_id, font=("TkDefaultFont", 12, "bold"),
                      bg=card["bg"], fg="white")
    lbl_id.pack(side="left")

    lbl_time = tk.Label(card, text=timestamp, font=("TkDefaultFont", 10),
                        bg=card["bg"], fg="white")
    lbl_time.pack(side="right")

    # Bind clicks
    for widget in (card, lbl_id, lbl_time):
        widget.bind("<Button-1>", lambda e, sid=session_id: on_session_click(sid))

# Populate session cards
for sid, data in sessions.items():
    create_session_card(sf, sid, data["timestamp"])

root.mainloop()