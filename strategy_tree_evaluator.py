import pandas as pd
import numpy as np
import trading_strategies


def normalize_for_side(signal: pd.Series, side: str) -> pd.Series:
    sig = signal.fillna(0).clip(-1, 1).astype(int)

    if side == "BUY":
        # Disallow -1; map sells to hold
        return sig.where(sig != -1, 0)
    elif side == "SELL":
        # Disallow +1; map buys to hold
        return sig.where(sig != 1, 0)
    else:
        raise ValueError(f"Unknown side: {side}")
    
def combine_series(a: pd.Series, b: pd.Series, op: str, side: str) -> pd.Series:
    if side == "BUY":
        if op == "AND":
            return np.where((a == 1) & (b == 1), 1, 0)
        else:  # OR
            return np.where((a == 1) | (b == 1), 1, 0)

    elif side == "SELL":
        if op == "AND":
            return np.where((a == -1) & (b == -1), -1, 0)
        else:  # OR
            return np.where((a == -1) | (b == -1), -1, 0)

def evaluate_node(node: dict, data: pd.DataFrame, side: str) -> pd.Series:
    if node["type"] == "strategy":
        func = trading_strategies.TradingStrategy.trading_strategies.get(node["name"])
        if func is None:
            return pd.Series(0, index=data.index, name="signal")
        df = func(data, node.get("params", {}))
        return normalize_for_side(df["signal"], side)

    elif node["type"] == "group":
        members = node.get("members", [])
        if not members:
            return pd.Series(0, index=data.index, name="signal")

        # Start with the first member
        result = evaluate_node(members[0], data, side).astype(int)

        # Fold the rest using the group’s logic
        for m in members[1:]:
            next_sig = evaluate_node(m, data, side).astype(int)
            result = pd.Series(
                combine_series(result, next_sig, node["logic"], side),
                index=data.index,
                name="signal",
            )
        return result
    
def evaluate_section(section, data: pd.DataFrame, side: str) -> pd.Series:
    tree = section.serialize()
    if not tree:
        return pd.Series(0, index=data.index, name=f"{side.lower()}_signal")

    # Evaluate the first node
    result = evaluate_node(tree[0], data, side).astype(int)

    # Fold in the rest
    for i in range(1, len(tree)):
        op = tree[i - 1]["logic"]  # operator of previous row
        next_sig = evaluate_node(tree[i], data, side).astype(int)
        result = pd.Series(
            combine_series(result, next_sig, op, side),
            index=data.index,
            name=f"{side.lower()}_signal",
        )

    return result

def aggregate_buy_sell(buy: pd.Series, sell: pd.Series) -> pd.Series:
    buy = buy.fillna(0).clip(0, 1).astype(int)     # {0, 1}
    sell = sell.fillna(0).clip(-1, 0).astype(int)  # {-1, 0}

    final = np.where(
        (buy == 1) & (sell == -1), 0,   # clash → neutral
        np.where(buy == 1, 1, np.where(sell == -1, -1, 0))
    )
    return pd.Series(final, index=buy.index, name="signal")
