import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import tkinter as tk


class ParamDialog(tk.Toplevel):
    def __init__(self, master, params: dict, apply_callback, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.title("Parameters")
        self.params = params
        self.apply_callback = apply_callback
        self.entries = {}

        # Build form dynamically
        for i, (name, default) in enumerate(params.items()):
            ttk.Label(self, text=name).grid(row=i, column=0, sticky="w", padx=5, pady=5)
            entry = ttk.Entry(self)
            entry.insert(0, str(default))
            entry.grid(row=i, column=1, padx=5, pady=5)
            self.entries[name] = entry

        # Apply button
        ttk.Button(self, text="Apply", command=self.apply).grid(
            row=len(params), column=0, columnspan=2, pady=10
        )

    def apply(self):
        # Collect values from entries
        new_values = {name: entry.get() for name, entry in self.entries.items()}
        self.apply_callback(new_values)
        self.destroy()


class StrategyRow(ttk.Frame):
    def __init__(self, master, name="Strategy", params=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.master = master
        self.name = name
        self.params = params or {}  # dict of param_name -> default_value

        self.label = ttk.Label(self, text=name)
        self.label.pack(side=LEFT, padx=2)

        # Parameters button
        self.param_btn = ttk.Button(self, text="P", width=2, bootstyle=INFO, command=self.open_params)
        self.param_btn.pack(side=LEFT, padx=2)

        self.remove_btn = ttk.Button(self, text="X", width=2, bootstyle=DANGER, command=self.remove_self)
        self.remove_btn.pack(side=LEFT, padx=2)

    def open_params(self):
        # Open dialog with current params
        ParamDialog(self, self.params, self.set_params)

    def set_params(self, new_values):
        # Save updated params
        self.params = new_values

    def get_params(self):
        return self.params

    def remove_self(self):
        self.destroy()

    def get_name(self):
        return self.name

    def to_dict(self):
        return {
            "name": self.get_name(),
            "params": self.get_params(),
        }


class StrategySection(ttk.Frame):
    def __init__(self, master, title="Section", strategies=None, strategy_param_getter=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)

        self.strategies = strategies
        self.strategy_param_getter = strategy_param_getter

        # Title gets its own row so the picker below can use the full width
        # of narrow side panels (e.g. the 255px Strategy notebook tab).
        ttk.Label(self, text=title, font="-size 10 -weight bold").pack(
            anchor=W, padx=5, pady=(5, 2)
        )

        # Picker row: Combo flex-grows, Add Button pinned on the right
        picker_row = ttk.Frame(self)
        picker_row.pack(fill=X, padx=5, pady=(0, 5))

        self.combo = ttk.Combobox(picker_row, values=self.strategies, state="readonly")
        self.combo.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        if self.strategies:
            self.combo.current(0)

        ttk.Button(
            picker_row, text="+", width=2, bootstyle=SUCCESS, command=self.add_strategy
        ).pack(side=LEFT)

        # Middle row: List box
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=X, padx=5, pady=5)

    def add_strategy(self):
        name = self.combo.get()
        if name:
            params = self.strategy_param_getter(name) if self.strategy_param_getter else {}
            row = StrategyRow(self.list_frame, name, params)
            row.pack(fill=X, pady=2)

    def get_selected_strategies(self):
        """Return list of dicts with name + params for each StrategyRow in list_frame."""
        return self.serialize()

    def serialize(self):
        """Flat list of {name, params} for every StrategyRow currently in the list."""
        return [
            c.to_dict()
            for c in self.list_frame.winfo_children()
            if isinstance(c, StrategyRow)
        ]
