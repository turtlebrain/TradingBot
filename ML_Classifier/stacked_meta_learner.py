"""
Stacked meta-learner pipeline.

This module is the single ML mode of the trading bot. It consumes the
continuous scores exposed by the rule-based strategies in
``trading_strategies`` plus a small set of regime features, applies a
gradient-boosted classifier with a purged + embargoed walk-forward CV,
and emits +1/-1/0 trade signals via ``predict_meta_learner``.

Public API:
    build_score_features(df, base_strategies, params)
    build_triple_barrier_labels(df, params)
    train_stacked_meta_learner(df, params)
    predict_meta_learner(df, trained, params)
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss

import trading_strategies as strategies
from ML_Classifier.ml_trading_persistence import save_training_artifacts


_EPS = 1e-9


# ----------------------------------------------------------------------
# Feature engineering
# ----------------------------------------------------------------------
def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _regime_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    log_ret = np.log(df["close"]).diff()

    out["ret_1_log"] = log_ret
    out["ret_5_log"] = np.log(df["close"]).diff(5)
    out["vol_5_log"] = log_ret.rolling(5, min_periods=5).std()
    out["vol_15_log"] = log_ret.rolling(15, min_periods=15).std()

    atr_window = int(params.get("atr_window", 14))
    atr = _atr(df, atr_window)
    out["mom_10_atr"] = (df["close"] - df["close"].shift(10)) / (atr + _EPS)

    if "volume" in df.columns:
        span = int(params.get("vol_span", 60))
        vmean = df["volume"].ewm(span=span, min_periods=10, adjust=False).mean()
        vstd = df["volume"].ewm(span=span, min_periods=10, adjust=False).std()
        out["volume_z"] = ((df["volume"] - vmean) / (vstd + _EPS)).clip(-5, 5)

    if isinstance(df.index, pd.DatetimeIndex):
        session_minutes = int(params.get("session_minutes", 390))
        minute_of_day = df.index.hour * 60 + df.index.minute
        angle = 2 * np.pi * (minute_of_day % session_minutes) / max(session_minutes, 1)
        out["tod_sin"] = np.sin(angle)
        out["tod_cos"] = np.cos(angle)

    return out


def _strategy_score_columns(df: pd.DataFrame, base_strategies: Iterable[dict]) -> pd.DataFrame:
    """
    For each entry in ``base_strategies`` (``{"name": ..., "params": ...}``),
    look up the registered ``*_score`` function, evaluate it on ``df``, and
    return all scores as a single DataFrame. Duplicate strategy names get
    a numeric suffix so distinct parameter sets stay separate.
    """
    cols: Dict[str, pd.Series] = {}
    name_counts: Dict[str, int] = {}
    for spec in base_strategies:
        name = spec.get("name")
        params = spec.get("params", {}) or {}
        scorer = strategies.strategy_scores.get(name)
        if scorer is None:
            continue
        series = scorer(df, params)
        suffix = name_counts.get(name, 0)
        col_name = series.name if suffix == 0 else f"{series.name}_{suffix}"
        cols[col_name] = series
        name_counts[name] = suffix + 1
    if not cols:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(cols, index=df.index)


def build_score_features(
    df: pd.DataFrame,
    base_strategies: Iterable[dict],
    params: dict,
) -> pd.DataFrame:
    """
    Build the meta-learner feature matrix.

    Combines per-strategy continuous scores with regime context, then shifts
    the entire frame by one bar so that no feature leaks information from
    the bar a decision is made on.
    """
    if df is None or df.empty:
        return pd.DataFrame(index=df.index if df is not None else [])

    score_df = _strategy_score_columns(df, base_strategies)
    regime_df = _regime_features(df, params)
    feats = pd.concat([score_df, regime_df], axis=1)
    feats = feats.replace([np.inf, -np.inf], np.nan)
    feats = feats.shift(1)
    return feats


# ----------------------------------------------------------------------
# Triple-barrier labels
# ----------------------------------------------------------------------
def build_triple_barrier_labels(df: pd.DataFrame, params: dict) -> pd.Series:
    """
    Triple-barrier labels with ATR-scaled barriers.

    For each bar t, scan forward up to ``vertical_bars`` bars. Label
    ``+1`` if close touches ``entry + up_barrier_atr * ATR`` first, ``-1``
    if ``entry - down_barrier_atr * ATR`` first, else ``0`` for a vertical
    barrier hit. Tail rows where the full window is unavailable are
    dropped from the returned Series.
    """
    h = int(params.get("vertical_bars", params.get("horizon", 10)))
    up_k = float(params.get("up_barrier_atr", 1.5))
    dn_k = float(params.get("down_barrier_atr", 1.5))
    atr_window = int(params.get("atr_window", 14))

    atr = _atr(df, atr_window)
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr_arr = atr.to_numpy()
    n = len(df)

    labels = np.full(n, np.nan, dtype=float)
    for i in range(n - h):
        a = atr_arr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = close[i]
        up = entry + up_k * a
        dn = entry - dn_k * a
        outcome = 0
        for j in range(1, h + 1):
            hi = high[i + j]
            lo = low[i + j]
            hit_up = hi >= up
            hit_dn = lo <= dn
            if hit_up and hit_dn:
                outcome = 1 if (up - close[i + j - 1]) <= (close[i + j - 1] - dn) else -1
                break
            if hit_up:
                outcome = 1
                break
            if hit_dn:
                outcome = -1
                break
        labels[i] = outcome

    s = pd.Series(labels, index=df.index, name="label")
    return s.dropna().astype(int)


# ----------------------------------------------------------------------
# Purged + embargoed walk-forward CV
# ----------------------------------------------------------------------
def _purged_kfold_indices(n_samples: int, n_splits: int, embargo: int) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Yield (train_idx, test_idx) pairs. Test folds are contiguous slices of
    the time axis. Training rows that fall within ``embargo`` bars of the
    test window are purged.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    fold_size = n_samples // n_splits
    splits: List[Tuple[np.ndarray, np.ndarray]] = []
    indices = np.arange(n_samples)
    for k in range(n_splits):
        test_start = k * fold_size
        test_end = (k + 1) * fold_size if k < n_splits - 1 else n_samples
        test_idx = indices[test_start:test_end]
        purge_lo = max(0, test_start - embargo)
        purge_hi = min(n_samples, test_end + embargo)
        train_mask = (indices < purge_lo) | (indices >= purge_hi)
        train_idx = indices[train_mask]
        if len(train_idx) and len(test_idx):
            splits.append((train_idx, test_idx))
    return splits


def _calibration_mae(y_true: np.ndarray, prob: np.ndarray, n_bins: int = 10) -> float:
    if len(y_true) == 0:
        return float("nan")
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(prob, bins) - 1, 0, n_bins - 1)
    err = []
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        err.append(abs(prob[mask].mean() - y_true[mask].mean()))
    return float(np.mean(err)) if err else float("nan")


def _build_estimator(params: dict):
    base = HistGradientBoostingClassifier(
        learning_rate=float(params.get("learning_rate", 0.05)),
        max_iter=int(params.get("max_iter", 200)),
        max_depth=params.get("max_depth"),
        l2_regularization=float(params.get("l2_regularization", 0.0)),
        random_state=int(params.get("random_state", 42)),
    )
    calibration = str(params.get("calibration", "none")).lower()
    if calibration in ("none", "", "off"):
        return base
    method = "sigmoid" if calibration == "platt" else "isotonic"
    return CalibratedClassifierCV(estimator=base, method=method, cv=3)


# ----------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------
def _binary_up_labels(labels: pd.Series) -> pd.Series:
    """Reduce {-1, 0, +1} triple-barrier labels to a binary up-vs-not-up target."""
    return (labels > 0).astype(int)


def train_stacked_meta_learner(df: pd.DataFrame, params: dict) -> dict:
    if df is None or df.empty:
        raise ValueError("Cannot train on empty data.")

    base_strategies = list(params.get("base_strategies", []))
    if not base_strategies:
        raise ValueError("At least one base strategy is required.")

    feats = build_score_features(df, base_strategies, params)
    feats = feats.dropna()
    raw_labels = build_triple_barrier_labels(df, params)
    y = _binary_up_labels(raw_labels)

    common_idx = feats.index.intersection(y.index)
    if len(common_idx) < int(params.get("min_train_bars", 50)):
        raise ValueError(
            f"Not enough aligned rows to train ({len(common_idx)} bars). "
            "Pull a longer window or reduce vertical_bars."
        )
    X = feats.loc[common_idx]
    y = y.loc[common_idx]

    embargo = int(params.get("embargo", max(int(params.get("horizon", 10)),
                                            int(params.get("vertical_bars", 10)))))
    n_splits = int(params.get("n_splits", 5))
    threshold = float(params.get("decision_threshold", 0.55))
    cost_bp = float(params.get("cost_bp", 5.0))
    cost_frac = cost_bp / 1e4

    fold_metrics = []
    folds = _purged_kfold_indices(len(X), n_splits, embargo)
    for train_idx, test_idx in folds:
        X_train = X.iloc[train_idx]
        y_train = y.iloc[train_idx]
        X_test = X.iloc[test_idx]
        y_test = y.iloc[test_idx]
        est = _build_estimator(params)
        est.fit(X_train, y_train)
        prob_up = est.predict_proba(X_test)[:, 1]

        # Forward returns over the vertical-barrier window for cost-aware metric.
        h = int(params.get("vertical_bars", params.get("horizon", 10)))
        fwd_ret = (df["close"].shift(-h) / df["close"] - 1.0).reindex(X_test.index)

        long_mask = prob_up >= threshold
        short_mask = prob_up <= (1.0 - threshold)
        trade_mask = long_mask | short_mask
        if trade_mask.any():
            sign = np.where(long_mask, 1.0, np.where(short_mask, -1.0, 0.0))
            edge = sign * fwd_ret.to_numpy() - cost_frac * (sign != 0).astype(float)
            avg_edge_bp = float(np.nanmean(edge[trade_mask]) * 1e4)
            hit_rate = float(np.nanmean((edge[trade_mask] > 0).astype(float)))
        else:
            avg_edge_bp = float("nan")
            hit_rate = float("nan")

        y_pred = (prob_up >= 0.5).astype(int)
        fold_metrics.append({
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "brier": float(brier_score_loss(y_test, prob_up)),
            "calibration_mae": _calibration_mae(y_test.to_numpy(), prob_up),
            "trade_rate": float(trade_mask.mean()),
            "avg_edge_bp": avg_edge_bp,
            "hit_rate": hit_rate,
        })

    # Aggregate metrics across folds (NaN-tolerant).
    metrics = {}
    if fold_metrics:
        for k in fold_metrics[0].keys():
            vals = [m[k] for m in fold_metrics if not (m[k] is None or (isinstance(m[k], float) and np.isnan(m[k])))]
            metrics[k] = float(np.mean(vals)) if vals else float("nan")

    final_estimator = _build_estimator(params)
    final_estimator.fit(X, y)

    warmup_bars = _estimate_warmup(base_strategies, params)

    inference_params = {
        "base_strategies": base_strategies,
        "atr_window": int(params.get("atr_window", 14)),
        "vol_span": int(params.get("vol_span", 60)),
        "session_minutes": int(params.get("session_minutes", 390)),
        "decision_threshold": threshold,
    }

    result = {
        "type": "stacked_meta_learner",
        "pipeline": final_estimator,
        "feature_columns": list(X.columns),
        "base_strategies": base_strategies,
        "inference_params": inference_params,
        "decision_threshold": threshold,
        "horizon": int(params.get("horizon", params.get("vertical_bars", 10))),
        "vertical_bars": int(params.get("vertical_bars", params.get("horizon", 10))),
        "embargo": embargo,
        "calibration": str(params.get("calibration", "none")),
        "cost_bp": cost_bp,
        "fold_metrics": fold_metrics,
        "metrics": metrics,
        "warmup_bars": warmup_bars,
    }
    version = save_training_artifacts(result)
    result["version"] = version
    return result


def _estimate_warmup(base_strategies: Iterable[dict], params: dict) -> int:
    """
    Maximum lookback among base strategies plus ATR / regime windows, with
    a small safety margin. Used as a guard in run_live_strategy so the
    meta-learner is never invoked before features are populated.
    """
    candidates = [
        int(params.get("atr_window", 14)),
        int(params.get("vol_span", 60)),
        15,  # vol_15_log
        10,  # mom_10_atr
    ]
    for spec in base_strategies:
        sp = spec.get("params", {}) or {}
        for key in ("long_window", "lookback", "distance", "short_window", "atr_window"):
            v = sp.get(key)
            if v is None:
                continue
            try:
                candidates.append(int(float(v)))
            except (TypeError, ValueError):
                continue
    return int(max(candidates) + 5)


# ----------------------------------------------------------------------
# Inference
# ----------------------------------------------------------------------
def predict_meta_learner(df: pd.DataFrame, trained: dict, params: dict) -> pd.DataFrame:
    """Return prob_up / prob_down / score / signal for every aligned row."""
    if df is None or df.empty:
        return pd.DataFrame(index=df.index if df is not None else [])

    base_strategies = trained.get("base_strategies") or params.get("base_strategies", [])
    feature_cols: List[str] = trained.get("feature_columns", [])
    threshold = float(trained.get("decision_threshold", params.get("decision_threshold", 0.55)))

    feats = build_score_features(df, base_strategies, params)
    if feature_cols:
        feats = feats.reindex(columns=feature_cols)

    valid = feats.dropna()
    out = pd.DataFrame(index=df.index)
    out["prob_up"] = np.nan
    out["prob_down"] = np.nan
    out["score"] = 0.0
    out["signal"] = 0

    if len(valid) == 0:
        return out

    pipeline = trained["pipeline"]
    prob_up = pipeline.predict_proba(valid)[:, 1]
    out.loc[valid.index, "prob_up"] = prob_up
    out.loc[valid.index, "prob_down"] = 1.0 - prob_up
    out.loc[valid.index, "score"] = 2.0 * prob_up - 1.0

    long_mask = prob_up >= threshold
    short_mask = prob_up <= (1.0 - threshold)
    sig = np.where(long_mask, 1, np.where(short_mask, -1, 0))
    out.loc[valid.index, "signal"] = sig
    out["signal"] = out["signal"].fillna(0).astype(int)
    return out
