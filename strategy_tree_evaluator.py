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

def evaluate_node(node: dict, data: pd.DataFrame, side: str) -> pd.DataFrame:
    series_name = f"{side}_signal"
    if node["type"] == "strategy":
        func = trading_strategies.TradingStrategy.trading_strategies.get(node["name"])
        if func is None:
            data[series_name] = 0
            return data
        df = func(data, node.get("params", {}))
        df[series_name] = normalize_for_side(df["signal"], side)
        return df

    elif node["type"] == "group":
        members = node.get("members", [])
        if not members:
            data[series_name] = 0
            return data

        # Start with the first member
        result_df = evaluate_node(members[0], data, side)

        # Fold the rest using the group’s logic
        for i in range(1, len(members)):
            op = members[i - 1]["logic"] # operator of previous row
            next_df = evaluate_node(members[i], data, side)
            result_series = pd.Series(
                combine_series(result_df[series_name], next_df[series_name], op, side),
                index=data.index,
                name="signal",
            )
            result_df[series_name] = result_series
        return result_df
    
def evaluate_section(section, data: pd.DataFrame, side: str) -> pd.DataFrame:
    tree = section.serialize()
    series_name = f"{side}_signal"
    if not tree:
        data[series_name] = 0
        return data

    # Evaluate the first node
    result_df = evaluate_node(tree[0], data, side)

    # Fold in the rest
    for i in range(1, len(tree)):
        op = tree[i - 1]["logic"]  # operator of previous row
        next_df = evaluate_node(tree[i], data, side)
        result_series = pd.Series(
            combine_series(result_df[series_name], next_df[series_name], op, side),
            index=data.index,
            name="signal",
        )
        result_df[series_name] = result_series
    return result_df

def aggregate_buy_sell(buy: pd.Series, sell: pd.Series) -> pd.Series:
    buy = buy.fillna(0).clip(0, 1).astype(int)     # {0, 1}
    sell = sell.fillna(0).clip(-1, 0).astype(int)  # {-1, 0}

    final = np.where(
        (buy == 1) & (sell == -1), 0,   # clash → neutral
        np.where(buy == 1, 1, np.where(sell == -1, -1, 0))
    )
    return pd.Series(final, index=buy.index, name="signal")

def evaluate_strategy(buy_section, sell_section, data: pd.DataFrame) -> pd.DataFrame:
    buy_signals = evaluate_section(buy_section, data, "BUY")
    sell_signals = evaluate_section(sell_section, data, "SELL")
    combined_series = aggregate_buy_sell(buy_signals["BUY_signal"], sell_signals["SELL_signal"])
    combined = buy_signals.copy()
    combined["signal"] = combined_series
    return combined