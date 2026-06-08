"""
Meta-label layer: filter direction-model trades by cost-aware profitability.

Trained on bars where the direction model would trade. Label = 1 if
forward return after costs is positive, else 0.

Public API:
    build_meta_label_features(...)
    build_meta_labels(...)
    train_meta_label(...)
    apply_meta_label(...)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss

_EPS = 1e-9


def build_meta_labels(
    df: pd.DataFrame,
    signal: pd.Series,
    params: dict,
    cost_frac: float,
) -> pd.Series:
    """
    Cost-aware tradability label for non-zero signals.

    Returns NaN where signal == 0 (not used for meta-label training).
    """
    h = int(params.get("vertical_bars", params.get("horizon", 10)))
    fwd_ret = (df["close"].shift(-h) / df["close"] - 1.0).reindex(signal.index)
    sign = signal.astype(float)
    edge = sign * fwd_ret - cost_frac * (sign != 0).astype(float)
    labels = pd.Series(np.nan, index=signal.index, name="meta_label")
    trade_mask = sign != 0
    labels.loc[trade_mask] = (edge.loc[trade_mask] > 0).astype(int)
    return labels.dropna()


def build_meta_label_features(
    prob_up: pd.Series,
    signal: pd.Series,
    regime: pd.Series,
    behavior_feats: pd.DataFrame,
    context_feats: pd.DataFrame,
) -> pd.DataFrame:
    """Feature matrix for the meta-label classifier."""
    out = pd.DataFrame(index=prob_up.index)
    out["prob_up"] = prob_up.astype(float)
    out["prob_extremity"] = (prob_up.astype(float) - 0.5).abs() * 2.0
    out["signal_sign"] = signal.astype(float)

    if behavior_feats is not None and not behavior_feats.empty:
        for col in (
            "score_consensus_std",
            "score_consensus_mean",
            "dist_open_atr",
            "capitulation_score",
            "flow_price_diverge",
            "or_position",
            "or_available",
            "consensus_x_vol",
            "open_dist_x_mom",
            "diverge_x_consensus",
        ):
            if col in behavior_feats.columns:
                out[col] = behavior_feats[col].astype(float)

    if context_feats is not None and not context_feats.empty:
        for col in ("mom_10_atr", "volume_z", "vol_15_log"):
            if col in context_feats.columns:
                out[col] = context_feats[col].astype(float)

    regime_codes = regime.fillna("neutral").astype(str)
    for name in ("opening", "chop", "herding", "neutral"):
        out[f"regime_{name}"] = (regime_codes == name).astype(int)

    return out.replace([np.inf, -np.inf], np.nan)


def _build_meta_estimator(params: dict) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=float(params.get("meta_learning_rate", 0.05)),
        max_iter=int(params.get("meta_max_iter", 150)),
        max_depth=params.get("meta_max_depth", 4),
        l2_regularization=float(params.get("meta_l2_regularization", 0.1)),
        random_state=int(params.get("random_state", 42)),
    )


def train_meta_label(
    X: pd.DataFrame,
    y: pd.Series,
    params: dict,
) -> dict:
    """Fit meta-label classifier on trade rows only."""
    common = X.index.intersection(y.index)
    X = X.loc[common].dropna()
    y = y.loc[X.index].astype(int)

    if len(X) < int(params.get("min_meta_train_rows", 30)):
        return {
            "pipeline": None,
            "feature_columns": list(X.columns) if len(X) else [],
            "metrics": {},
            "trained": False,
        }

    est = _build_meta_estimator(params)
    est.fit(X, y)
    prob = est.predict_proba(X)[:, 1]
    y_pred = (prob >= 0.5).astype(int)

    return {
        "pipeline": est,
        "feature_columns": list(X.columns),
        "metrics": {
            "meta_accuracy": float(accuracy_score(y, y_pred)),
            "meta_brier": float(brier_score_loss(y, prob)),
            "meta_train_rows": int(len(X)),
            "meta_positive_rate": float(y.mean()),
        },
        "trained": True,
    }


def apply_meta_label(
    predictions: pd.DataFrame,
    meta_features: pd.DataFrame,
    meta_trained: dict,
    meta_threshold: float,
) -> pd.DataFrame:
    """Zero signals where meta-label probability is below threshold."""
    out = predictions.copy()
    pipeline = meta_trained.get("pipeline")
    feature_cols: List[str] = meta_trained.get("feature_columns", [])

    out["prob_tradable"] = np.nan
    if pipeline is None or not meta_trained.get("trained", False):
        return out

    valid = meta_features.reindex(columns=feature_cols).dropna()
    if len(valid) == 0:
        return out

    prob_tradable = pipeline.predict_proba(valid)[:, 1]
    out.loc[valid.index, "prob_tradable"] = prob_tradable

    if "signal" not in out.columns:
        out["signal"] = 0

    out["meta_filtered"] = False
    for i, ix in enumerate(valid.index):
        if int(out.at[ix, "signal"]) == 0:
            continue
        if prob_tradable[i] < meta_threshold:
            out.at[ix, "signal"] = 0
            out.at[ix, "meta_filtered"] = True

    return out
