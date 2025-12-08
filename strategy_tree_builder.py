import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tooltip_helper import Tooltip
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
        ttk.Button(self, text="Apply", bootstyle=SUCCESS, command=self.apply).grid(
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

        self.logic = ttk.Combobox(self, values=["AND", "OR"], width=4, state="readonly")
        self.logic.current(0)
        self.logic.pack(side=LEFT, padx=2)

        self.group_var = ttk.BooleanVar()
        self.checkbox = ttk.Checkbutton(self, variable=self.group_var)
        self.checkbox.pack(side=LEFT, padx=2)

        self.remove_btn = ttk.Button(self, text="❌", width=2, bootstyle=DANGER, command=self.remove_self)
        self.remove_btn.pack(side=LEFT, padx=2)

    def open_params(self):
        # Open dialog with current params
        ParamDialog(self, self.params, self.set_params)

    def set_params(self, new_values):
        # Save updated params
        self.params = new_values
        print(f"{self.name} updated params: {self.params}")

    def remove_self(self):
        self.destroy()

    def is_selected(self):
        return self.group_var.get()

    def get_logic(self):
        return self.logic.get()

    def get_name(self):
        return self.name

    def to_dict(self):
        return {
            "type": "strategy",
            "name": self.get_name(),       # e.g. "EMA Breakout"
            "logic": self.get_logic(),     # "AND" or "OR"
            "params": getattr(self, "params", {}) or {},
        }


class GroupRow(ttk.Frame):
    counter = 1

    def __init__(self, master, members, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.master = master
        self.group_members = members
        self.name = f"Group {GroupRow.counter}"
        GroupRow.counter += 1

        self.label = ttk.Label(self, text=self.name)
        self.label.pack(side=LEFT, padx=5)

        self.logic = ttk.Combobox(self, values=["AND", "OR"], width=5, state="readonly")
        self.logic.current(0)
        self.logic.pack(side=LEFT, padx=5)

        self.group_var = ttk.BooleanVar()
        self.checkbox = ttk.Checkbutton(self, variable=self.group_var)
        self.checkbox.pack(side=LEFT, padx=5)

        self.remove_btn = ttk.Button(self, text="❌", width=2, bootstyle=DANGER, command=self.remove_self)
        self.remove_btn.pack(side=LEFT, padx=5)

        # Attach tooltip to the label
        Tooltip(self.label, self.get_contents_text)

    def get_contents_text(self):
        """Return a string representation of the group's members."""
        lines = []
        for m in self.group_members:
            if isinstance(m, GroupRow):
                lines.append(m.get_name())
            else:
                lines.append(m.get_name())
        return "Contains:\n" + "\n".join(lines)

    def remove_self(self):
        for child in self.group_members:
            child.pack(fill=X, pady=2)
        self.destroy()

    def is_selected(self):
        return self.group_var.get()

    def get_logic(self):
        return self.logic.get()

    def get_name(self):
        return self.name
    
    def to_dict(self):
        return {
            "type": "group",
            "name": self.get_name(),       # e.g. "Group 1"
            "logic": self.get_logic(),     # operator inside the group
            "members": [m.to_dict() for m in self.group_members],
        }


class StrategySection(ttk.Frame):
    def __init__(self, master, title="Section", strategies=None, strategy_param_getter=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
    
        self.strategies = strategies 
        self.strategy_param_getter = strategy_param_getter 
    
        # Top row: Label + Combo + Add Button
        top_row = ttk.Frame(self)
        top_row.pack(fill=X, pady=5)
    
        ttk.Label(top_row, text=title, font="-size 10 -weight bold").pack(side=LEFT, padx=5)
        self.combo = ttk.Combobox(top_row, values=self.strategies, width=20)
        self.combo.pack(side=LEFT, padx=5)
        ttk.Button(top_row, text="➕", width=2, bootstyle=SUCCESS, command=self.add_strategy).pack(side=LEFT, padx=5)
    
        # Middle row: List box
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=X, pady=5)
    
        # Bottom row: Centered Group button
        bottom_row = ttk.Frame(self)
        bottom_row.pack(fill=X, pady=5)
        ttk.Button(bottom_row, text="Group", bootstyle=SECONDARY, command=self.group_selected).pack(anchor="center")

    def add_strategy(self):
        name = self.combo.get()
        if name:
            params = self.strategy_param_getter(name)
            row = StrategyRow(self.list_frame, name, params)
            row.pack(fill=X, pady=2)

    def group_selected(self):
        children = [c for c in self.list_frame.winfo_children() if isinstance(c, (StrategyRow, GroupRow))]
        selected = [c for c in children if hasattr(c, "is_selected") and c.is_selected()]

        if len(selected) < 2:
            return

        for c in selected:
            c.pack_forget()

        new_group = GroupRow(self.list_frame, selected)
        new_group.pack(fill=X, pady=2)

        for c in [new_group] + selected:
            if hasattr(c, "group_var"):
                c.group_var.set(False)
    
    # Serialization to dict for evaluator
    def serialize(self):
        children = [
            c for c in self.list_frame.winfo_children()
            if hasattr(c, "to_dict")
        ]
        return [c.to_dict() for c in children]

    

