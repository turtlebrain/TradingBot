"""
Stacked meta-learner pipeline.

This module is the single ML mode of the trading bot. It consumes:

  * continuous scores from the rule-based strategies in ``trading_strategies``
  * a small set of regime features (rolling vol, momentum, volume z-score,
    time-of-day sin/cos)
  * the Phase 1A intraday microstructure block from
    ``ML_Classifier.microstructure_features`` (realized vol, signed-volume
    absorption, bar-based OFI, optional cross-asset basis z-score, optional
    L1-quote OFI, optional session-phase one-hots)
  * the Phase 1B behavioral block from
    ``ML_Classifier.behavioral_features`` (consensus, anchoring, OR distance,
    chase, capitulation, flow-price divergence, wick ratios) with an optional
    post-prediction gate from ``ML_Classifier.behavioral_gate``

It applies a gradient-boosted classifier with purged + embargoed
walk-forward CV and emits +1/-1/0 trade signals via ``predict_meta_learner``.
The microstructure parameter set is round-tripped through
``inference_params`` so live inference reproduces training-time features
even when callers omit those keys.

Public API:
    build_score_features(df, base_strategies, params,
                         cross_asset_bars=None, quotes=None)
    build_triple_barrier_labels(df, params)
    train_stacked_meta_learner(df, params,
                               cross_asset_bars=None, quotes=None)
    predict_meta_learner(df, trained, params,
                         cross_asset_bars=None, quotes=None)
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss

import trading_strategies as strategies
from ML_Classifier.behavioral_features import (
    BEHAVIORAL_V2_COLUMNS,
    build_behavioral_features,
    or_coverage_pct,
)
from ML_Classifier.behavioral_gate import (
    apply_behavioral_gate,
    classify_behavioral_regime,
    learn_regime_gate_bumps,
)
from ML_Classifier.eval_metrics import (
    compute_metrics_by_regime,
    compute_trade_metrics,
    tune_decision_threshold,
)
from ML_Classifier.meta_label import (
    apply_meta_label,
    build_meta_label_features,
    build_meta_labels,
    train_meta_label,
)
from ML_Classifier.microstructure_features import build_microstructure_features
from ML_Classifier.ml_trading_persistence import save_training_artifacts


_EPS = 1e-9

# Params keys passed through to ML_Classifier.microstructure_features.
# Centralized here so train/predict can round-trip them via inference_params.
_MICROSTRUCTURE_PARAM_KEYS = (
    "enable_microstructure",
    "rv_window",
    "rv_use_returns",
    "rv_annualize",
    "absorption_window",
    "ofi_bar_window",
    "ofi_quote_window",
    "basis_window",
    "session",
    "tz",
    "enable_basis",
    "enable_quote_ofi",
    "enable_session_phase",
)

_MICROSTRUCTURE_DEFAULTS = {
    "enable_microstructure": True,
    "rv_window": 30,
    "absorption_window": 10,
    "ofi_bar_window": 30,
    "basis_window": 60,
    # Cross-asset basis and session-phase one-hots are opt-in:
    # basis requires a second instrument; session_phase overlaps with the
    # tod_sin/tod_cos features already produced by _regime_features.
    "enable_basis": False,
    "enable_session_phase": False,
    "enable_quote_ofi": False,
}


def _microstructure_params(params: dict) -> dict:
    """Subset of ``params`` that is forwarded to ``build_microstructure_features``."""
    out = dict(_MICROSTRUCTURE_DEFAULTS)
    if params:
        for key in _MICROSTRUCTURE_PARAM_KEYS:
            if key in params:
                out[key] = params[key]
    return out


# Params keys passed through to ML_Classifier.behavioral_features / behavioral_gate.
_BEHAVIORAL_PARAM_KEYS = (
    "enable_behavioral",
    "enable_behavioral_gate",
    "behavioral_in_direction_model",
    "enable_meta_label",
    "meta_threshold",
    "enable_behavioral_consensus",
    "enable_behavioral_anchoring",
    "enable_behavioral_flow",
    "gate_learn_on_train",
    "or_minutes",
    "session_open_minute",
    "tz",
    "ofi_bar_window",
    "consensus_std_chop_threshold",
    "consensus_std_herd_threshold",
    "consensus_mean_herd_threshold",
    "chop_momentum_threshold",
    "gate_opening_threshold_bump",
    "gate_chop_threshold_bump",
    "gate_opening_block",
    "gate_opening_threshold_bump_learned",
    "gate_chop_threshold_bump_learned",
    "meta_learning_rate",
    "meta_max_iter",
    "meta_max_depth",
    "meta_l2_regularization",
)

_BEHAVIORAL_DEFAULTS = {
    "enable_behavioral": False,
    "enable_behavioral_gate": False,
    "behavioral_in_direction_model": False,
    "enable_meta_label": False,
    "meta_threshold": 0.55,
    "enable_behavioral_consensus": True,
    "enable_behavioral_anchoring": True,
    "enable_behavioral_flow": True,
    "gate_learn_on_train": True,
    "or_minutes": 15,
    "session_open_minute": 9 * 60 + 30,
    "ofi_bar_window": 30,
    "consensus_std_chop_threshold": 0.35,
    "consensus_std_herd_threshold": 0.15,
    "consensus_mean_herd_threshold": 0.25,
    "chop_momentum_threshold": 0.15,
    "gate_opening_threshold_bump": 0.05,
    "gate_chop_threshold_bump": 0.03,
    "gate_opening_block": False,
    "meta_learning_rate": 0.05,
    "meta_max_iter": 150,
    "meta_max_depth": 4,
    "meta_l2_regularization": 0.1,
    "tz": "America/New_York",
}

_BEHAVIORAL_FEATURE_COLUMNS = BEHAVIORAL_V2_COLUMNS


def _behavioral_params(params: dict) -> dict:
    """Subset of ``params`` forwarded to behavioral feature / gate builders."""
    out = dict(_BEHAVIORAL_DEFAULTS)
    if params:
        for key in _BEHAVIORAL_PARAM_KEYS:
            if key in params:
                out[key] = params[key]
        # Shared with regime / behavioral builders.
        for key in ("atr_window", "vol_span", "decision_threshold"):
            if key in params:
                out[key] = params[key]
    return out


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


def _compute_behavior_block(
    df: pd.DataFrame,
    score_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    micro_df: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    beh_params = _behavioral_params(params)
    if not beh_params.get("enable_behavioral", False):
        return pd.DataFrame(index=df.index)

    context_parts = [regime_df]
    if micro_df is not None and not micro_df.empty:
        context_parts.append(micro_df)
    context_df = pd.concat(context_parts, axis=1)
    atr_window = int(params.get("atr_window", 14))
    return build_behavioral_features(
        df,
        beh_params,
        score_df=score_df,
        context_df=context_df,
        atr=_atr(df, atr_window),
    )


def build_score_features(
    df: pd.DataFrame,
    base_strategies: Iterable[dict],
    params: dict,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build the meta-learner feature matrix.

    Combines per-strategy continuous scores with regime context, the
    intraday microstructure block (Phase 1A), and the behavioral block
    (Phase 1B: consensus, anchoring, OR distance, chase, capitulation,
    divergence, wicks). The whole frame is then shifted by one bar so that
    no feature leaks information from the bar a decision is made on.

    ``cross_asset_bars`` is required to populate the basis z-score column
    when ``enable_basis`` is true. ``quotes`` is required to populate the
    true OFI column when ``enable_quote_ofi`` is true. Both are optional;
    if absent the corresponding feature is simply omitted.
    """
    if df is None or df.empty:
        return pd.DataFrame(index=df.index if df is not None else [])

    score_df = _strategy_score_columns(df, base_strategies)
    regime_df = _regime_features(df, params)

    blocks: List[pd.DataFrame] = [score_df, regime_df]
    micro_df = pd.DataFrame(index=df.index)

    micro_params = _microstructure_params(params)
    if micro_params.get("enable_microstructure", True):
        micro_df = build_microstructure_features(
            df,
            micro_params,
            cross_asset_bars=cross_asset_bars,
            quotes=quotes,
        )
        if not micro_df.empty:
            blocks.append(micro_df)

    beh_params = _behavioral_params(params)
    behavior_df = _compute_behavior_block(df, score_df, regime_df, micro_df, params)
    if (
        beh_params.get("enable_behavioral", False)
        and beh_params.get("behavioral_in_direction_model", False)
        and not behavior_df.empty
    ):
        blocks.append(behavior_df)

    feats = pd.concat(blocks, axis=1)
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
    beh = _behavioral_params(params)
    l2 = float(params.get("l2_regularization", 0.0))
    max_depth = params.get("max_depth")
    if beh.get("enable_behavioral") and beh.get("behavioral_in_direction_model"):
        l2 = float(params.get("l2_regularization", params.get("behavioral_l2_regularization", 0.5)))
        if max_depth is None:
            max_depth = int(params.get("behavioral_max_depth", 4))

    base = HistGradientBoostingClassifier(
        learning_rate=float(params.get("learning_rate", 0.05)),
        max_iter=int(params.get("max_iter", 200)),
        max_depth=max_depth,
        l2_regularization=l2,
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


def _fwd_returns(df: pd.DataFrame, params: dict, index: pd.Index) -> pd.Series:
    h = int(params.get("vertical_bars", params.get("horizon", 10)))
    return (df["close"].shift(-h) / df["close"] - 1.0).reindex(index)


def _build_behavior_context(
    df: pd.DataFrame,
    base_strategies: Iterable[dict],
    params: dict,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Shifted behavioral block and regime/micro context for meta-label / gate."""
    score_df = _strategy_score_columns(df, base_strategies)
    regime_df = _regime_features(df, params)
    micro_df = pd.DataFrame(index=df.index)
    micro_params = _microstructure_params(params)
    if micro_params.get("enable_microstructure", True):
        micro_df = build_microstructure_features(
            df,
            micro_params,
            cross_asset_bars=cross_asset_bars,
            quotes=quotes,
        )
    behavior_df = _compute_behavior_block(df, score_df, regime_df, micro_df, params)
    context_parts = [regime_df]
    if micro_df is not None and not micro_df.empty:
        context_parts.append(micro_df)
    context_df = pd.concat(context_parts, axis=1) if context_parts else pd.DataFrame(index=df.index)
    behavior_df = behavior_df.replace([np.inf, -np.inf], np.nan).shift(1)
    context_df = context_df.replace([np.inf, -np.inf], np.nan).shift(1)
    return behavior_df, context_df


def _signals_from_prob(prob_up: np.ndarray, threshold: float) -> np.ndarray:
    long_mask = prob_up >= threshold
    short_mask = prob_up <= (1.0 - threshold)
    return np.where(long_mask, 1, np.where(short_mask, -1, 0)).astype(int)


def _apply_inference_stack(
    index: pd.Index,
    prob_up: pd.Series,
    behavior_feats: pd.DataFrame,
    context_feats: pd.DataFrame,
    params: dict,
    meta_trained: Optional[dict] = None,
) -> Tuple[pd.DataFrame, pd.Series]:
    """Direction prob -> signal through optional gate and meta-label filter."""
    beh = _behavioral_params(params)
    threshold = float(params.get("decision_threshold", 0.55))

    out = pd.DataFrame(index=index)
    out["prob_up"] = prob_up.astype(float)
    out["prob_down"] = 1.0 - out["prob_up"]
    out["score"] = 2.0 * out["prob_up"] - 1.0
    out["signal"] = _signals_from_prob(out["prob_up"].to_numpy(), threshold)

    regime = pd.Series("neutral", index=index, name="behavioral_regime")
    if beh.get("enable_behavioral", False) and len(behavior_feats) > 0:
        regime = classify_behavioral_regime(
            behavior_feats.reindex(index),
            beh,
            context_df=context_feats.reindex(index) if context_feats is not None else None,
        )
        out["behavioral_regime"] = regime

    use_gate = (
        beh.get("enable_behavioral_gate", False)
        and beh.get("enable_behavioral", False)
        and not beh.get("enable_meta_label", False)
    )
    if use_gate:
        gate_params = {**beh, "decision_threshold": threshold}
        gated = apply_behavioral_gate(out[["prob_up", "signal"]].copy(), regime, gate_params)
        out["signal"] = gated["signal"]
        out["effective_threshold"] = gated["effective_threshold"]
        out["gate_adjusted"] = gated["gate_adjusted"]

    if beh.get("enable_meta_label", False) and meta_trained and meta_trained.get("trained"):
        meta_X = build_meta_label_features(
            out["prob_up"],
            out["signal"],
            regime,
            behavior_feats.reindex(index),
            context_feats.reindex(index) if context_feats is not None else pd.DataFrame(index=index),
        )
        out = apply_meta_label(
            out,
            meta_X,
            meta_trained,
            float(beh.get("meta_threshold", 0.55)),
        )

    out["signal"] = out["signal"].fillna(0).astype(int)
    return out, regime


def train_stacked_meta_learner(
    df: pd.DataFrame,
    params: dict,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> dict:
    if df is None or df.empty:
        raise ValueError("Cannot train on empty data.")

    base_strategies = list(params.get("base_strategies", []))
    if not base_strategies:
        raise ValueError("At least one base strategy is required.")

    feats = build_score_features(
        df,
        base_strategies,
        params,
        cross_asset_bars=cross_asset_bars,
        quotes=quotes,
    )
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

    behavior_full, context_full = _build_behavior_context(
        df, base_strategies, params, cross_asset_bars=cross_asset_bars, quotes=quotes
    )
    behavior_aligned = behavior_full.reindex(common_idx)
    context_aligned = context_full.reindex(common_idx)

    beh_params = _behavioral_params(params)
    embargo = int(params.get("embargo", max(int(params.get("horizon", 10)),
                                            int(params.get("vertical_bars", 10)))))
    n_splits = int(params.get("n_splits", 5))
    cost_bp = float(params.get("cost_bp", 5.0))
    cost_frac = cost_bp / 1e4

    fold_metrics: List[dict] = []
    fold_regime_metrics: List[dict] = []
    fold_tuned_thresholds: List[float] = []
    oos_prob: List[float] = []
    oos_signal: List[int] = []
    oos_fwd: List[float] = []
    oos_regime: List[str] = []

    folds = _purged_kfold_indices(len(X), n_splits, embargo)
    for train_idx, test_idx in folds:
        X_train = X.iloc[train_idx]
        y_train = y.iloc[train_idx]
        X_test = X.iloc[test_idx]
        y_test = y.iloc[test_idx]
        est = _build_estimator(params)
        est.fit(X_train, y_train)
        prob_up = est.predict_proba(X_test)[:, 1]
        test_index = X_test.index
        fwd_ret = _fwd_returns(df, params, test_index).to_numpy()

        tuned_t = tune_decision_threshold(prob_up, fwd_ret, cost_frac)
        fold_tuned_thresholds.append(tuned_t)

        fold_params = dict(params)
        fold_params["decision_threshold"] = tuned_t

        prob_series = pd.Series(prob_up, index=test_index)
        beh_test = behavior_aligned.loc[test_index]
        ctx_test = context_aligned.loc[test_index]
        meta_fold: Optional[dict] = None

        if beh_params.get("enable_meta_label") and beh_params.get("enable_behavioral"):
            prob_train = est.predict_proba(X_train)[:, 1]
            train_index = X_train.index
            fwd_train = _fwd_returns(df, params, train_index).to_numpy()
            train_t = tune_decision_threshold(prob_train, fwd_train, cost_frac)
            train_params = dict(params)
            train_params["decision_threshold"] = train_t
            train_prob_s = pd.Series(prob_train, index=train_index)
            beh_train = behavior_aligned.loc[train_index]
            ctx_train = context_aligned.loc[train_index]
            train_stack, train_regime = _apply_inference_stack(
                train_index, train_prob_s, beh_train, ctx_train, train_params, meta_trained=None
            )
            meta_y = build_meta_labels(df, train_stack["signal"], params, cost_frac)
            meta_X = build_meta_label_features(
                train_stack["prob_up"],
                train_stack["signal"],
                train_regime,
                beh_train,
                ctx_train,
            )
            meta_fold = train_meta_label(meta_X, meta_y, params)

        stacked, regime = _apply_inference_stack(
            test_index, prob_series, beh_test, ctx_test, fold_params, meta_trained=meta_fold
        )
        sig = stacked["signal"].to_numpy()

        m = compute_trade_metrics(
            prob_up, y_test.to_numpy(), fwd_ret, tuned_t, cost_frac, signal=sig
        )
        m["brier"] = float(brier_score_loss(y_test, prob_up))
        m["calibration_mae"] = _calibration_mae(y_test.to_numpy(), prob_up)
        m["decision_threshold"] = tuned_t
        regime_breakdown = compute_metrics_by_regime(sig, fwd_ret, regime, cost_frac)
        m["metrics_by_regime"] = regime_breakdown
        fold_metrics.append(m)
        fold_regime_metrics.append(regime_breakdown)

        oos_prob.extend(prob_up.tolist())
        oos_signal.extend(sig.tolist())
        oos_fwd.extend(fwd_ret.tolist())
        oos_regime.extend(regime.fillna("neutral").astype(str).tolist())

    metrics: dict = {}
    if fold_metrics:
        scalar_keys = ("accuracy", "brier", "calibration_mae", "trade_rate", "avg_edge_bp", "hit_rate")
        for k in scalar_keys:
            vals = [
                m[k] for m in fold_metrics
                if k in m and m[k] is not None and not (isinstance(m[k], float) and np.isnan(m[k]))
            ]
            metrics[k] = float(np.mean(vals)) if vals else float("nan")

    threshold = (
        float(np.mean(fold_tuned_thresholds))
        if fold_tuned_thresholds
        else float(params.get("decision_threshold", 0.55))
    )

    learned_bumps: Dict[str, float] = {}
    if (
        beh_params.get("enable_behavioral_gate")
        and beh_params.get("enable_behavioral")
        and not beh_params.get("enable_meta_label")
        and beh_params.get("gate_learn_on_train", True)
        and oos_prob
    ):
        oos_prob_arr = np.asarray(oos_prob, dtype=float)
        oos_sig_arr = np.asarray(oos_signal, dtype=int)
        oos_fwd_arr = np.asarray(oos_fwd, dtype=float)
        oos_regime_s = pd.Series(oos_regime)
        learned_bumps = learn_regime_gate_bumps(
            oos_prob_arr,
            oos_sig_arr,
            oos_regime_s,
            oos_fwd_arr,
            cost_frac,
            threshold,
            params=beh_params,
        )

    final_estimator = _build_estimator(params)
    final_estimator.fit(X, y)

    meta_label_result: dict = {"trained": False, "pipeline": None, "feature_columns": [], "metrics": {}}
    if beh_params.get("enable_meta_label") and beh_params.get("enable_behavioral"):
        prob_full = final_estimator.predict_proba(X)[:, 1]
        full_params = dict(params)
        full_params["decision_threshold"] = threshold
        prob_full_s = pd.Series(prob_full, index=common_idx)
        full_stack, full_regime = _apply_inference_stack(
            common_idx, prob_full_s, behavior_aligned, context_aligned, full_params, meta_trained=None
        )
        meta_y = build_meta_labels(df, full_stack["signal"], params, cost_frac)
        meta_X = build_meta_label_features(
            full_stack["prob_up"],
            full_stack["signal"],
            full_regime,
            behavior_aligned,
            context_aligned,
        )
        meta_label_result = train_meta_label(meta_X, meta_y, params)

    metrics_by_regime: dict = {}
    if fold_regime_metrics:
        regime_names = set()
        for block in fold_regime_metrics:
            regime_names.update(block.keys())
        for name in regime_names:
            edges = []
            hits = []
            counts = []
            for block in fold_regime_metrics:
                if name not in block:
                    continue
                r = block[name]
                if np.isfinite(r.get("avg_edge_bp", float("nan"))):
                    edges.append(r["avg_edge_bp"])
                if np.isfinite(r.get("hit_rate", float("nan"))):
                    hits.append(r["hit_rate"])
                counts.append(r.get("trade_count", 0))
            if edges or hits:
                metrics_by_regime[name] = {
                    "avg_edge_bp": float(np.mean(edges)) if edges else float("nan"),
                    "hit_rate": float(np.mean(hits)) if hits else float("nan"),
                    "trade_count": int(sum(counts)),
                }

    or_cov = or_coverage_pct(behavior_full) if beh_params.get("enable_behavioral") else float("nan")

    warmup_bars = _estimate_warmup(base_strategies, params)

    inference_params = {
        "base_strategies": base_strategies,
        "atr_window": int(params.get("atr_window", 14)),
        "vol_span": int(params.get("vol_span", 60)),
        "session_minutes": int(params.get("session_minutes", 390)),
        "decision_threshold": threshold,
    }
    inference_params.update(_microstructure_params(params))
    inference_params.update(_behavioral_params(params))
    inference_params.update(learned_bumps)

    training_context = dict(params.get("training_context", {}) or {})

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
        "metrics_by_regime": metrics_by_regime,
        "or_coverage_pct": or_cov,
        "meta_label": meta_label_result,
        "warmup_bars": warmup_bars,
        "training_context": training_context,
    }
    if meta_label_result.get("trained") and meta_label_result.get("metrics"):
        metrics.update({
            k: v for k, v in meta_label_result["metrics"].items()
            if k.startswith("meta_")
        })
    version = save_training_artifacts(result)
    result["version"] = version
    return result


def _estimate_warmup(base_strategies: Iterable[dict], params: dict) -> int:
    """
    Maximum lookback among base strategies plus ATR / regime / microstructure
    windows, with a small safety margin. Used as a guard in
    ``run_live_strategy`` so the meta-learner is never invoked before
    features are populated.
    """
    candidates = [
        int(params.get("atr_window", 14)),
        int(params.get("vol_span", 60)),
        15,  # vol_15_log
        10,  # mom_10_atr
    ]
    micro = _microstructure_params(params)
    if micro.get("enable_microstructure", True):
        candidates.extend([
            int(micro.get("rv_window", 30)),
            int(micro.get("absorption_window", 10)),
            int(micro.get("ofi_bar_window", 30)),
        ])
        if micro.get("enable_basis", False):
            candidates.append(int(micro.get("basis_window", 60)))
        if micro.get("enable_quote_ofi", False):
            candidates.append(int(micro.get("ofi_quote_window", 100)))
    beh = _behavioral_params(params)
    if beh.get("enable_behavioral", False):
        candidates.append(int(beh.get("or_minutes", 15)) + 10)
        candidates.append(int(beh.get("ofi_bar_window", 30)))
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
def predict_meta_learner(
    df: pd.DataFrame,
    trained: dict,
    params: dict,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Return prob_up / prob_down / score / signal for every aligned row.

    Feature-builder params are reconstructed by merging the model's saved
    ``inference_params`` over the caller-supplied ``params`` so the exact
    same feature schema (windows, toggles, etc.) used during training is
    reproduced at inference time. ``cross_asset_bars`` and ``quotes`` are
    forwarded to :func:`build_score_features` for the basis-z and
    quote-OFI features.
    """
    if df is None or df.empty:
        return pd.DataFrame(index=df.index if df is not None else [])

    base_strategies = trained.get("base_strategies") or params.get("base_strategies", [])
    feature_cols: List[str] = trained.get("feature_columns", [])

    effective_params = dict(trained.get("inference_params", {}))
    if params:
        effective_params.update(params)

    feats = build_score_features(
        df,
        base_strategies,
        effective_params,
        cross_asset_bars=cross_asset_bars,
        quotes=quotes,
    )
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
    prob_series = pd.Series(prob_up, index=valid.index)

    meta_trained = trained.get("meta_label")
    beh_params = _behavioral_params(effective_params)
    behavior_feats = pd.DataFrame(index=valid.index)
    context_feats = pd.DataFrame(index=valid.index)
    if beh_params.get("enable_behavioral", False):
        behavior_full, context_full = _build_behavior_context(
            df,
            base_strategies,
            effective_params,
            cross_asset_bars=cross_asset_bars,
            quotes=quotes,
        )
        behavior_feats = behavior_full.reindex(valid.index)
        context_feats = context_full.reindex(valid.index)

    stacked, _regime = _apply_inference_stack(
        valid.index,
        prob_series,
        behavior_feats,
        context_feats,
        effective_params,
        meta_trained=meta_trained,
    )

    for col in stacked.columns:
        if col not in out.columns:
            if stacked[col].dtype == object or str(stacked[col].dtype) == "bool":
                out[col] = None
            else:
                out[col] = np.nan
        out.loc[valid.index, col] = stacked[col].values

    out["signal"] = out["signal"].fillna(0).astype(int)
    return out


def evaluate_config_on_holdout(
    df: pd.DataFrame,
    params: dict,
    config_overrides: dict,
    holdout_frac: float = 0.2,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Train on the leading portion of ``df``, evaluate full inference stack on
    the trailing holdout window. Used by ``scripts/eval_meta_learner.py``.
    """
    if df is None or len(df) < 50:
        raise ValueError("Need at least 50 bars for holdout evaluation.")

    n_holdout = max(int(len(df) * holdout_frac), 20)
    train_df = df.iloc[:-n_holdout].copy()
    holdout_df = df.iloc[-n_holdout:].copy()

    run_params = dict(params)
    run_params.update(config_overrides)
    trained = train_stacked_meta_learner(
        train_df,
        run_params,
        cross_asset_bars=cross_asset_bars,
        quotes=quotes,
    )
    preds = predict_meta_learner(
        holdout_df,
        trained,
        run_params,
        cross_asset_bars=cross_asset_bars,
        quotes=quotes,
    )

    valid = preds.dropna(subset=["prob_up"])
    if len(valid) == 0:
        return {"config": config_overrides, "metrics": {}, "metrics_by_regime": {}}

    cost_bp = float(run_params.get("cost_bp", trained.get("cost_bp", 5.0)))
    cost_frac = cost_bp / 1e4
    fwd = _fwd_returns(holdout_df, run_params, valid.index).to_numpy()
    sig = valid["signal"].fillna(0).astype(int).to_numpy()
    prob = valid["prob_up"].to_numpy()
    y_dummy = (prob >= 0.5).astype(int)

    metrics = compute_trade_metrics(
        prob, y_dummy, fwd, float(trained.get("decision_threshold", 0.55)), cost_frac, signal=sig
    )
    regime = valid.get("behavioral_regime", pd.Series("neutral", index=valid.index))
    by_regime = compute_metrics_by_regime(sig, fwd, regime, cost_frac)
    return {
        "config": config_overrides,
        "metrics": metrics,
        "metrics_by_regime": by_regime,
        "trained_metrics": trained.get("metrics", {}),
    }
