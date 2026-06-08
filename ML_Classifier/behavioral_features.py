"""
Behavioral / crowd-psychology feature computation for the stacked meta-learner.

These features proxy observable crowd states from OHLCV bars (and optional
precomputed strategy scores / regime / microstructure context): anchoring to
session open and opening range, herding vs confusion among base strategies,
chase acceleration, capitulation, flow-price divergence, and wick rejection.

Designed for backtest on historical bars without L1 quotes. Quote-OFI
divergence can be added in a later phase via ``context_df``.

Public API:
    compute_score_consensus(score_df)
    compute_opening_range_levels(bars, or_minutes, ...)
    compute_session_open_distance(bars, atr, ...)
    compute_price_accel_atr(close, atr)
    compute_capitulation_score(ret_1, volume_z, vol_15)
    compute_flow_price_diverge(ret_1, ofi_proxy)
    compute_wick_ratios(bars)
    build_behavioral_features(bars, params, score_df, context_df, atr)
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from ML_Classifier.microstructure_features import compute_signed_volume
from trading_indicators import _us_session_keys


_EPS = 1e-9

# Phase 2 v2 pruned behavioral schema.
BEHAVIORAL_V2_COLUMNS = (
    "score_consensus_mean",
    "score_consensus_std",
    "dist_open_atr",
    "or_position",
    "or_available",
    "capitulation_score",
    "flow_price_diverge",
    "consensus_x_vol",
    "open_dist_x_mom",
    "diverge_x_consensus",
)


def or_coverage_pct(behavior_df: pd.DataFrame) -> float:
    """Fraction of rows with a proper (non-proxy) opening-range anchor."""
    if behavior_df is None or behavior_df.empty or "or_available" not in behavior_df.columns:
        return float("nan")
    s = behavior_df["or_available"].dropna()
    if s.empty:
        return float("nan")
    return float(s.mean())

# Regular US cash-session open in minutes from midnight (America/New_York).
_DEFAULT_SESSION_OPEN_MINUTE = 9 * 60 + 30


def _minute_of_day(index: pd.DatetimeIndex, tz: str = "America/New_York") -> pd.Series:
    """Local clock minute-of-day for each timestamp."""
    if index.tz is None:
        idx_local = index.tz_localize("UTC").tz_convert(tz)
    else:
        idx_local = index.tz_convert(tz)
    return pd.Series(idx_local.hour * 60 + idx_local.minute, index=index)


def _atr(bars: pd.DataFrame, window: int) -> pd.Series:
    """True range ATR; mirrors stacked_meta_learner._atr."""
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    prev_close = bars["close"].astype(float).shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _score_columns(score_df: pd.DataFrame) -> List[str]:
    """Numeric columns treated as base-strategy continuous scores."""
    if score_df is None or score_df.empty:
        return []
    return [
        c
        for c in score_df.columns
        if pd.api.types.is_numeric_dtype(score_df[c])
    ]


def _context_series(context_df: Optional[pd.DataFrame], name: str) -> Optional[pd.Series]:
    if context_df is None or context_df.empty or name not in context_df.columns:
        return None
    return context_df[name]


def _ofi_proxy_from_context(
    bars: pd.DataFrame,
    context_df: Optional[pd.DataFrame],
    ofi_bar_window: int,
) -> pd.Series:
    """Prefer bar OFI from microstructure context; else rolling signed-volume ratio."""
    if context_df is not None and not context_df.empty:
        ofi_cols = [c for c in context_df.columns if str(c).startswith("ofi_bar_")]
        if ofi_cols:
            return context_df[ofi_cols[0]].astype(float)

    signed = compute_signed_volume(bars)
    sv_sum = signed.rolling(ofi_bar_window, min_periods=ofi_bar_window).sum()
    av_sum = bars["volume"].astype(float).abs().rolling(
        ofi_bar_window, min_periods=ofi_bar_window
    ).sum()
    return (sv_sum / (av_sum + _EPS)).rename(f"ofi_bar_{ofi_bar_window}")


# ----------------------------------------------------------------------
# Score consensus (herding vs confusion)
# ----------------------------------------------------------------------
def compute_score_consensus(score_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mean and std of base-strategy score columns.

    High std -> conflicting views (chop / confusion); low std + large mean
    magnitude -> aligned crowd (herding).
    """
    cols = _score_columns(score_df)
    out = pd.DataFrame(index=score_df.index)
    if not cols:
        out["score_consensus_mean"] = np.nan
        out["score_consensus_std"] = np.nan
        return out

    block = score_df[cols].astype(float)
    out["score_consensus_mean"] = block.mean(axis=1)
    out["score_consensus_std"] = block.std(axis=1, ddof=0)
    return out


# ----------------------------------------------------------------------
# Opening range and session open anchoring
# ----------------------------------------------------------------------
def compute_opening_range_levels(
    bars: pd.DataFrame,
    or_minutes: int = 15,
    session_open_minute: int = _DEFAULT_SESSION_OPEN_MINUTE,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """
    Per-bar session open, opening-range high/low, and position within OR.

    During the OR window (``session_open_minute`` .. + ``or_minutes``), OR
    levels expand bar-by-bar. After the window closes, final OR high/low
    forward-fill for the rest of the session day.

    Returns columns: ``session_open``, ``or_high``, ``or_low``, ``or_position``.
    """
    out = pd.DataFrame(index=bars.index)
    for col in ("session_open", "or_high", "or_low", "or_position", "or_available"):
        out[col] = np.nan

    if bars is None or bars.empty or not isinstance(bars.index, pd.DatetimeIndex):
        return out

    required = {"open", "high", "low", "close"}
    if not required.issubset(bars.columns):
        return out

    session_key = _us_session_keys(bars.index, tz=tz)
    minute = _minute_of_day(bars.index, tz=tz)
    or_end = session_open_minute + int(or_minutes)

    for _, group in bars.groupby(session_key, sort=False):
        g_idx = group.index
        g_min = minute.loc[g_idx]
        in_or = (g_min >= session_open_minute) & (g_min < or_end)

        out.loc[g_idx, "session_open"] = float(group["open"].iloc[0])

        or_h = np.nan
        or_l = np.nan
        had_or_window = bool(in_or.any())
        proxy_or_end = session_open_minute + int(or_minutes)

        for ix in g_idx:
            if in_or.loc[ix]:
                hi = float(bars.at[ix, "high"])
                lo = float(bars.at[ix, "low"])
                or_h = hi if not np.isfinite(or_h) else max(or_h, hi)
                or_l = lo if not np.isfinite(or_l) else min(or_l, lo)
            elif not had_or_window and g_min.loc[ix] < proxy_or_end:
                # Fallback: data starts after 9:30 — proxy OR from early session bars.
                hi = float(bars.at[ix, "high"])
                lo = float(bars.at[ix, "low"])
                or_h = hi if not np.isfinite(or_h) else max(or_h, hi)
                or_l = lo if not np.isfinite(or_l) else min(or_l, lo)

            if np.isfinite(or_h) and np.isfinite(or_l):
                out.loc[ix, "or_high"] = or_h
                out.loc[ix, "or_low"] = or_l
                out.loc[ix, "or_available"] = 1.0 if had_or_window else 0.0
                close = float(bars.at[ix, "close"])
                rng = or_h - or_l
                if rng > _EPS:
                    out.loc[ix, "or_position"] = np.clip((close - or_l) / rng, 0.0, 1.0)

    return out


def compute_session_open_distance(
    close: pd.Series,
    session_open: pd.Series,
    atr: pd.Series,
) -> pd.Series:
    """Signed distance from session open in ATR units."""
    return ((close.astype(float) - session_open.astype(float)) / (atr.astype(float) + _EPS)).rename(
        "dist_open_atr"
    )


def compute_or_distances(
    close: pd.Series,
    or_high: pd.Series,
    or_low: pd.Series,
    atr: pd.Series,
) -> pd.DataFrame:
    """Distance to OR high/low in ATR units."""
    out = pd.DataFrame(index=close.index)
    atr_safe = atr.astype(float) + _EPS
    out["dist_or_high_atr"] = (close.astype(float) - or_high.astype(float)) / atr_safe
    out["dist_or_low_atr"] = (close.astype(float) - or_low.astype(float)) / atr_safe
    return out


# ----------------------------------------------------------------------
# Chase, capitulation, divergence, wicks
# ----------------------------------------------------------------------
def compute_price_accel_atr(close: pd.Series, atr: pd.Series) -> pd.Series:
    """Second difference of log price, ATR-normalized (chase / FOMO proxy)."""
    log_close = np.log(close.astype(float))
    accel = log_close.diff().diff()
    return (accel / (atr.astype(float) + _EPS)).rename("price_accel_atr")


def compute_capitulation_score(
    ret_1: pd.Series,
    volume_z: pd.Series,
    vol_15: pd.Series,
) -> pd.Series:
    """
    Panic proxy: down move x elevated volume x elevated short-horizon vol.

    ``ret_1`` should be log return (or simple return) for the bar.
    """
    down = (-ret_1.astype(float)).clip(lower=0.0)
    vz = volume_z.astype(float).clip(lower=0.0)
    vol = vol_15.astype(float).clip(lower=0.0)
    return (down * vz * vol).rename("capitulation_score")


def compute_flow_price_diverge(ret_1: pd.Series, ofi_proxy: pd.Series) -> pd.Series:
    """
    Sign agreement between return and order-flow proxy.

    +1 aligned, -1 divergent (disbelief), 0 when either side is flat.
    """
    r_sign = np.sign(ret_1.astype(float))
    f_sign = np.sign(ofi_proxy.astype(float))
    diverge = np.where(
        (r_sign == 0) | (f_sign == 0),
        0.0,
        np.where(r_sign == f_sign, 1.0, -1.0),
    )
    return pd.Series(diverge, index=ret_1.index, name="flow_price_diverge")


def compute_wick_ratios(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Upper and lower wick as a fraction of total bar range.

    Large upper wick -> rejection after upside probe; large lower wick ->
    rejection after downside probe (stop-hunt proxy).
    """
    out = pd.DataFrame(index=bars.index)
    out["upper_wick_ratio"] = np.nan
    out["lower_wick_ratio"] = np.nan

    if bars is None or bars.empty:
        return out

    required = {"open", "high", "low", "close"}
    if not required.issubset(bars.columns):
        return out

    o = bars["open"].astype(float)
    h = bars["high"].astype(float)
    l = bars["low"].astype(float)
    c = bars["close"].astype(float)
    rng = (h - l).replace(0, np.nan)

    body_top = pd.concat([o, c], axis=1).max(axis=1)
    body_bot = pd.concat([o, c], axis=1).min(axis=1)
    out["upper_wick_ratio"] = ((h - body_top) / (rng + _EPS)).clip(0.0, 1.0)
    out["lower_wick_ratio"] = ((body_bot - l) / (rng + _EPS)).clip(0.0, 1.0)
    return out


# ----------------------------------------------------------------------
# Convenience builder
# ----------------------------------------------------------------------
def build_behavioral_features(
    bars: pd.DataFrame,
    params: Optional[dict] = None,
    score_df: Optional[pd.DataFrame] = None,
    context_df: Optional[pd.DataFrame] = None,
    atr: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Assemble behavioral features for concatenation in ``build_score_features``.

    Parameters
    ----------
    bars : pd.DataFrame
        OHLCV bars with DatetimeIndex.
    params : dict, optional
        Supported keys::

            or_minutes              default 15
            session_open_minute     default 570 (9:30 ET)
            tz                      default America/New_York
            atr_window              default 14 (used when ``atr`` not passed)
            ofi_bar_window          default 30 (fallback OFI rolling window)

    score_df : pd.DataFrame, optional
        Base strategy continuous scores (for consensus features).
    context_df : pd.DataFrame, optional
        Regime / microstructure columns to reuse (``volume_z``, ``vol_15_log``,
        ``ret_1_log``, ``ofi_bar_*``).
    atr : pd.Series, optional
        Precomputed ATR; computed from ``bars`` when omitted.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(index=bars.index if bars is not None else [])

    p = params or {}
    tz = str(p.get("tz", "America/New_York"))
    or_minutes = int(p.get("or_minutes", 15))
    session_open_minute = int(p.get("session_open_minute", _DEFAULT_SESSION_OPEN_MINUTE))
    atr_window = int(p.get("atr_window", 14))
    ofi_bar_window = int(p.get("ofi_bar_window", 30))

    if atr is None:
        atr = _atr(bars, atr_window)

    close = bars["close"].astype(float)

    or_levels = compute_opening_range_levels(
        bars,
        or_minutes=or_minutes,
        session_open_minute=session_open_minute,
        tz=tz,
    )
    enable_consensus = bool(p.get("enable_behavioral_consensus", True))
    enable_anchoring = bool(p.get("enable_behavioral_anchoring", True))
    enable_flow = bool(p.get("enable_behavioral_flow", True))

    consensus_df = pd.DataFrame(index=bars.index)
    if enable_consensus and score_df is not None and not score_df.empty:
        consensus_df = compute_score_consensus(score_df)
    else:
        consensus_df["score_consensus_mean"] = np.nan
        consensus_df["score_consensus_std"] = np.nan

    ret_1 = _context_series(context_df, "ret_1_log")
    if ret_1 is None:
        ret_1 = np.log(close).diff()

    volume_z = _context_series(context_df, "volume_z")
    if volume_z is None and "volume" in bars.columns:
        span = int(p.get("vol_span", 60))
        vol = bars["volume"].astype(float)
        vmean = vol.ewm(span=span, min_periods=10, adjust=False).mean()
        vstd = vol.ewm(span=span, min_periods=10, adjust=False).std()
        volume_z = ((vol - vmean) / (vstd + _EPS)).clip(-5, 5)

    vol_15 = _context_series(context_df, "vol_15_log")
    if vol_15 is None:
        vol_15 = np.log(close).diff().rolling(15, min_periods=15).std()

    mom = _context_series(context_df, "mom_10_atr")
    if mom is None:
        mom = (close - close.shift(10)) / (atr.astype(float) + _EPS)

    pruned = pd.DataFrame(index=bars.index)
    pruned["score_consensus_mean"] = consensus_df["score_consensus_mean"]
    pruned["score_consensus_std"] = consensus_df["score_consensus_std"]

    if enable_anchoring:
        pruned["dist_open_atr"] = compute_session_open_distance(
            close, or_levels["session_open"], atr
        )
        pruned["or_position"] = or_levels["or_position"]
        pruned["or_available"] = or_levels["or_available"]

    if enable_flow:
        if volume_z is not None:
            pruned["capitulation_score"] = compute_capitulation_score(ret_1, volume_z, vol_15)
        else:
            pruned["capitulation_score"] = np.nan
        ofi_proxy = _ofi_proxy_from_context(bars, context_df, ofi_bar_window)
        pruned["flow_price_diverge"] = compute_flow_price_diverge(ret_1, ofi_proxy)

    # Explicit interactions (Phase 2 v2).
    if volume_z is not None:
        pruned["consensus_x_vol"] = (
            consensus_df["score_consensus_std"].astype(float) * volume_z.astype(float)
        )
    else:
        pruned["consensus_x_vol"] = np.nan

    dist_open = pruned.get("dist_open_atr")
    if dist_open is not None:
        pruned["open_dist_x_mom"] = dist_open.astype(float) * mom.astype(float)
    else:
        pruned["open_dist_x_mom"] = np.nan

    if "flow_price_diverge" in pruned.columns:
        pruned["diverge_x_consensus"] = (
            pruned["flow_price_diverge"].astype(float)
            * consensus_df["score_consensus_std"].astype(float)
        )
    else:
        pruned["diverge_x_consensus"] = np.nan

    return pruned.replace([np.inf, -np.inf], np.nan)
