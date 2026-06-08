"""
Post-prediction behavioral gate for the stacked meta-learner.

Classifies each bar into a coarse crowd-behavior regime and optionally
adjusts trade signals by raising the decision threshold in unfavorable
states (opening chaos, chop). Kept separate from feature computation so
Phase 2 can swap rule-based gates for a meta-label classifier.

Public API:
    BEHAVIORAL_REGIMES
    classify_behavioral_regime(feats, params, context_df)
    apply_behavioral_gate(predictions, regime, params)
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from ML_Classifier.behavioral_features import _DEFAULT_SESSION_OPEN_MINUTE
from ML_Classifier.eval_metrics import compute_trade_metrics


BEHAVIORAL_REGIMES: Tuple[str, ...] = ("opening", "chop", "herding", "neutral")

_DEFAULT_PARAMS = {
    "or_minutes": 15,
    "session_open_minute": _DEFAULT_SESSION_OPEN_MINUTE,
    "tz": "America/New_York",
    "consensus_std_chop_threshold": 0.35,
    "consensus_std_herd_threshold": 0.15,
    "consensus_mean_herd_threshold": 0.25,
    "chop_momentum_threshold": 0.15,
    "decision_threshold": 0.55,
    "gate_opening_threshold_bump": 0.05,
    "gate_chop_threshold_bump": 0.03,
    "gate_opening_block": False,
}


def _merged_params(params: Optional[dict]) -> dict:
    out = dict(_DEFAULT_PARAMS)
    if params:
        out.update(params)
    return out


def _minute_of_day(index: pd.DatetimeIndex, tz: str) -> pd.Series:
    if index.tz is None:
        idx_local = index.tz_localize("UTC").tz_convert(tz)
    else:
        idx_local = index.tz_convert(tz)
    return pd.Series(idx_local.hour * 60 + idx_local.minute, index=index)


def _opening_mask(index: pd.DatetimeIndex, params: dict) -> pd.Series:
    """True for bars inside the regular-session opening window."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return pd.Series(False, index=index, dtype=bool)

    tz = str(params.get("tz", _DEFAULT_PARAMS["tz"]))
    session_open = int(params.get("session_open_minute", _DEFAULT_SESSION_OPEN_MINUTE))
    or_end = session_open + int(params.get("or_minutes", 15))
    minute = _minute_of_day(index, tz)
    return (minute >= session_open) & (minute < or_end)


def _context_series(
    context_df: Optional[pd.DataFrame],
    feats: pd.DataFrame,
    name: str,
) -> Optional[pd.Series]:
    if context_df is not None and name in context_df.columns:
        return context_df[name].reindex(feats.index)
    if name in feats.columns:
        return feats[name]
    return None


def classify_behavioral_regime(
    feats: pd.DataFrame,
    params: Optional[dict] = None,
    context_df: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """
    Assign each bar to one of ``BEHAVIORAL_REGIMES``.

    Priority (first match wins): ``opening`` -> ``chop`` -> ``herding`` ->
    ``neutral``.

    Parameters
    ----------
    feats : pd.DataFrame
        Behavioral feature block (must include consensus columns when
        available). Index is used for opening-window detection.
    params : dict, optional
        Thresholds and session timing; see ``_DEFAULT_PARAMS``.
    context_df : pd.DataFrame, optional
        Regime columns (e.g. ``mom_10_atr``) not present in ``feats``.
    """
    p = _merged_params(params)
    index = feats.index
    regime = pd.Series("neutral", index=index, dtype=object)

    if len(feats) == 0:
        return regime.rename("behavioral_regime")

    opening = _opening_mask(index, p)
    regime.loc[opening] = "opening"

    consensus_std = feats.get("score_consensus_std")
    consensus_mean = feats.get("score_consensus_mean")
    mom = _context_series(context_df, feats, "mom_10_atr")

    if consensus_std is not None:
        chop_mask = (
            ~opening
            & (consensus_std.astype(float) > float(p["consensus_std_chop_threshold"]))
        )
        if mom is not None:
            chop_mask = chop_mask & (
                mom.astype(float).abs() < float(p["chop_momentum_threshold"])
            )
        regime.loc[chop_mask] = "chop"

    if consensus_std is not None and consensus_mean is not None:
        herd_mask = (
            (regime == "neutral")
            & (consensus_std.astype(float) < float(p["consensus_std_herd_threshold"]))
            & (consensus_mean.astype(float).abs() > float(p["consensus_mean_herd_threshold"]))
        )
        regime.loc[herd_mask] = "herding"

    return regime.rename("behavioral_regime")


def resolve_gate_bumps(params: Optional[dict]) -> Tuple[float, float]:
    """Use walk-forward learned bumps when present, else rule defaults."""
    p = _merged_params(params)
    learned_open = p.get("gate_opening_threshold_bump_learned")
    learned_chop = p.get("gate_chop_threshold_bump_learned")
    opening = float(
        learned_open
        if learned_open is not None
        else p.get("gate_opening_threshold_bump", 0.05)
    )
    chop = float(
        learned_chop
        if learned_chop is not None
        else p.get("gate_chop_threshold_bump", 0.03)
    )
    return opening, chop


def learn_regime_gate_bumps(
    prob_up: np.ndarray,
    signal: np.ndarray,
    regime: pd.Series,
    fwd_ret: np.ndarray,
    cost_frac: float,
    base_threshold: float,
    params: Optional[dict] = None,
    min_trades: int = 5,
) -> Dict[str, float]:
    """
    Grid-search threshold bumps per regime on validation data.

    Returns keys ``gate_opening_threshold_bump_learned`` and
    ``gate_chop_threshold_bump_learned``.
    """
    p = _merged_params(params)
    grid = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]
    regime = regime.reindex(range(len(signal))).fillna("neutral")

    def _best_bump(regime_name: str) -> float:
        mask = regime.values == regime_name
        if mask.sum() < min_trades:
            return float(p.get(f"gate_{regime_name}_threshold_bump", 0.0))
        best_bump = float(p.get(f"gate_{regime_name}_threshold_bump", 0.0))
        best_edge = float("-inf")
        for bump in grid:
            eff = base_threshold + bump
            long_m = prob_up >= eff
            short_m = prob_up <= (1.0 - eff)
            sign = np.where(long_m, 1, np.where(short_m, -1, 0))
            # Only evaluate bars in this regime
            sign_r = np.where(mask, sign, 0)
            m = compute_trade_metrics(
                prob_up, np.zeros(len(prob_up)), fwd_ret, eff, cost_frac, signal=sign_r
            )
            edge = m.get("avg_edge_bp", float("nan"))
            if np.isfinite(edge) and edge > best_edge:
                best_edge = edge
                best_bump = bump
        return best_bump

    return {
        "gate_opening_threshold_bump_learned": _best_bump("opening"),
        "gate_chop_threshold_bump_learned": _best_bump("chop"),
    }


def apply_behavioral_gate(
    predictions: pd.DataFrame,
    regime: pd.Series,
    params: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Adjust ``signal`` using regime-dependent threshold bumps.

    Expects ``predictions`` to contain ``prob_up`` and ``signal`` columns.
    Adds ``behavioral_regime``, ``effective_threshold``, and
    ``gate_adjusted`` (True when threshold differed from base or opening
    block zeroed a would-be trade).

    Herding receives no adjustment in v1 (reserved for Phase 2 ablation).
    """
    p = _merged_params(params)
    out = predictions.copy()
    base_threshold = float(p["decision_threshold"])

    if "prob_up" not in out.columns:
        raise KeyError("predictions must contain 'prob_up'")
    if "signal" not in out.columns:
        out["signal"] = 0

    aligned_regime = regime.reindex(out.index).fillna("neutral")
    effective = pd.Series(base_threshold, index=out.index, dtype=float)

    opening_bump, chop_bump = resolve_gate_bumps(p)
    effective.loc[aligned_regime == "opening"] += opening_bump
    effective.loc[aligned_regime == "chop"] += chop_bump
    effective = effective.clip(0.5, 0.95)

    prob_up = out["prob_up"].astype(float)
    long_mask = prob_up >= effective
    short_mask = prob_up <= (1.0 - effective)
    new_signal = np.where(long_mask, 1, np.where(short_mask, -1, 0)).astype(int)

    if bool(p.get("gate_opening_block", False)):
        blocked = aligned_regime == "opening"
        new_signal = np.where(blocked, 0, new_signal)

    prior_signal = out["signal"].fillna(0).astype(int).to_numpy()
    gate_adjusted = (new_signal != prior_signal) | (
        effective.to_numpy() != base_threshold
    )

    out["behavioral_regime"] = aligned_regime
    out["effective_threshold"] = effective
    out["gate_adjusted"] = gate_adjusted
    out["signal"] = new_signal
    return out
