"""
Shared evaluation metrics for meta-learner training and CLI scripts.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score


def tune_decision_threshold(
    prob_up: np.ndarray,
    fwd_ret: np.ndarray,
    cost_frac: float,
    grid: Optional[np.ndarray] = None,
) -> float:
    """Pick threshold maximizing avg_edge_bp on validation trades."""
    if grid is None:
        grid = np.arange(0.50, 0.86, 0.02)

    best_t = 0.55
    best_edge = float("-inf")
    for t in grid:
        long_mask = prob_up >= t
        short_mask = prob_up <= (1.0 - t)
        trade_mask = long_mask | short_mask
        if not trade_mask.any():
            continue
        sign = np.where(long_mask, 1.0, np.where(short_mask, -1.0, 0.0))
        edge = sign * fwd_ret - cost_frac * (sign != 0).astype(float)
        avg = float(np.nanmean(edge[trade_mask]))
        if avg > best_edge:
            best_edge = avg
            best_t = float(t)
    return best_t


def compute_trade_metrics(
    prob_up: np.ndarray,
    y_true: np.ndarray,
    fwd_ret: np.ndarray,
    threshold: float,
    cost_frac: float,
    signal: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    """Cost-aware metrics for taken trades."""
    if signal is None:
        long_mask = prob_up >= threshold
        short_mask = prob_up <= (1.0 - threshold)
        sign = np.where(long_mask, 1, np.where(short_mask, -1, 0))
    else:
        sign = signal.astype(int)
        long_mask = sign > 0
        short_mask = sign < 0

    trade_mask = sign != 0
    y_pred = (prob_up >= 0.5).astype(int)

    out: Dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, y_pred)) if len(y_true) else float("nan"),
        "trade_rate": float(trade_mask.mean()) if len(trade_mask) else float("nan"),
    }

    if trade_mask.any():
        edge = sign.astype(float) * fwd_ret - cost_frac * (sign != 0).astype(float)
        taken = edge[trade_mask]
        out["avg_edge_bp"] = float(np.nanmean(taken) * 1e4)
        out["hit_rate"] = float(np.mean(taken > 0))
    else:
        out["avg_edge_bp"] = float("nan")
        out["hit_rate"] = float("nan")

    return out


def compute_metrics_by_regime(
    signal: np.ndarray,
    fwd_ret: np.ndarray,
    regime: pd.Series,
    cost_frac: float,
) -> Dict[str, Dict[str, float]]:
    """Per-regime edge/hit_rate for manual diagnosis."""
    out: Dict[str, Dict[str, float]] = {}
    regime = regime.reindex(range(len(signal))).fillna("neutral")
    for name in regime.unique():
        mask = (regime.values == name) & (signal != 0)
        if not mask.any():
            continue
        sign = signal[mask].astype(float)
        edge = sign * fwd_ret[mask] - cost_frac
        out[str(name)] = {
            "trade_count": int(mask.sum()),
            "avg_edge_bp": float(np.nanmean(edge) * 1e4),
            "hit_rate": float(np.mean(edge > 0)),
        }
    return out
