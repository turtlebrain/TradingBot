"""
Microstructure feature computation for the stacked meta-learner.

These are the additional intraday features called out in Phase 1A of the
intraday algo plan: realized volatility, session-phase one-hots, cross-asset
basis z-score, signed-volume / absorption, and order-flow imbalance (OFI).

Two compute modes are supported because Phase 1 backtests run on
``reqHistoricalData`` bars (no L1 history), while Phase 2/3 live trading has
``reqTickByTickData('BidAsk')`` available:

    * "bar"   - OHLCV-only features that work in backtest and live.
    * "quote" - true Cont-Kukanov-Stoikov OFI from L1 quote events. Used
                only in live trading or when a recorded quote stream is
                supplied.

Public API:
    compute_realized_vol(prices_or_returns, window, ...)
    compute_session_phase(index, session, tz)
    compute_basis_zscore(price_a, price_b, window)
    compute_signed_volume(bars)
    compute_ofi_from_bars(bars, window)
    compute_ofi_from_quotes(quotes, window)
    compute_absorption(bars, window)
    build_microstructure_features(bars, params, cross_asset_bars, quotes)
"""

from __future__ import annotations

from typing import List, Optional, Union

import numpy as np
import pandas as pd


_EPS = 1e-9

# Session phase boundaries in minutes from midnight, US/Eastern.
# Covers extended-hours US equities and CME equity-index futures.
# 'overnight' wraps midnight and is handled specially in compute_session_phase.
_US_SESSION_PHASES = {
    "premarket":  (4 * 60,        9 * 60 + 30),
    "open":       (9 * 60 + 30,   10 * 60),
    "mid":        (10 * 60,       14 * 60 + 30),
    "close":      (14 * 60 + 30,  16 * 60),
    "afterhours": (16 * 60,       20 * 60),
    "overnight":  (20 * 60,       4 * 60),
}


# ----------------------------------------------------------------------
# Realized volatility
# ----------------------------------------------------------------------
def compute_realized_vol(
    prices_or_returns: pd.Series,
    window: int,
    use_returns: bool = False,
    annualize: bool = False,
    bars_per_year: int = 252 * 390,
) -> pd.Series:
    """
    Rolling realized volatility from intraday prices or pre-computed returns.

    With ``use_returns=False`` (default) the input is a price series and log
    returns are computed internally. With ``use_returns=True`` the input is
    treated as the returns series directly.

    ``annualize=True`` scales by ``sqrt(bars_per_year)``. The default
    ``bars_per_year`` matches 1-minute US equity bars (252 days * 390 mins).
    """
    if prices_or_returns is None or len(prices_or_returns) == 0:
        return pd.Series(dtype=float, name=f"realized_vol_{window}")

    if use_returns:
        ret = prices_or_returns.astype(float)
    else:
        ret = np.log(prices_or_returns.astype(float)).diff()

    rv = (ret ** 2).rolling(window, min_periods=window).sum().pow(0.5)
    if annualize:
        rv = rv * np.sqrt(bars_per_year)
    return rv.rename(f"realized_vol_{window}")


# ----------------------------------------------------------------------
# Session phase (one-hot)
# ----------------------------------------------------------------------
def compute_session_phase(
    index: pd.DatetimeIndex,
    session: str = "us",
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """
    One-hot encoded session phase per timestamp.

    Phases for ``session='us'`` are: premarket, open, mid, close, afterhours,
    overnight. Timestamps are interpreted in ``tz`` (default
    America/New_York). Naive indices are assumed UTC and converted.

    Returns one int column per phase named ``phase_<name>``.
    """
    if session != "us":
        raise ValueError(f"Unknown session: {session!r}")
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas DatetimeIndex")
    if len(index) == 0:
        cols = [f"phase_{p}" for p in _US_SESSION_PHASES]
        return pd.DataFrame(columns=cols, index=index, dtype=int)

    idx_local = index.tz_localize("UTC").tz_convert(tz) if index.tz is None else index.tz_convert(tz)
    minutes = idx_local.hour * 60 + idx_local.minute

    out = pd.DataFrame(index=index)
    for name, (start, end) in _US_SESSION_PHASES.items():
        if start <= end:
            mask = (minutes >= start) & (minutes < end)
        else:
            # Overnight wraps midnight: [start, 24h) U [0, end).
            mask = (minutes >= start) | (minutes < end)
        out[f"phase_{name}"] = np.asarray(mask, dtype=int)
    return out


# ----------------------------------------------------------------------
# Cross-asset basis z-score
# ----------------------------------------------------------------------
def compute_basis_zscore(
    price_a: pd.Series,
    price_b: pd.Series,
    window: int,
) -> pd.Series:
    """
    Rolling z-score of ``log(price_a / price_b)``.

    Useful for detecting transient divergence between correlated instruments
    (MES vs MNQ, SPY vs IVV, /ES vs /SPX). Inputs are aligned by inner join.
    """
    if price_a is None or price_b is None or len(price_a) == 0 or len(price_b) == 0:
        return pd.Series(dtype=float, name=f"basis_z_{window}")

    aligned = pd.concat([price_a, price_b], axis=1, join="inner").dropna()
    if aligned.empty:
        return pd.Series(dtype=float, name=f"basis_z_{window}")

    log_basis = np.log(aligned.iloc[:, 0].astype(float) / aligned.iloc[:, 1].astype(float))
    mu = log_basis.rolling(window, min_periods=window).mean()
    sd = log_basis.rolling(window, min_periods=window).std()
    return ((log_basis - mu) / (sd + _EPS)).rename(f"basis_z_{window}")


# ----------------------------------------------------------------------
# Signed volume (tick rule from bars)
# ----------------------------------------------------------------------
def compute_signed_volume(bars: pd.DataFrame) -> pd.Series:
    """
    Per-bar signed volume using the bar tick rule.

    Approximation: ``sign = +1 if close > open, -1 if close < open, else 0``.
    Used as the building block for the bar-based OFI proxy and absorption.
    Requires columns ``open``, ``close``, ``volume``.
    """
    if bars is None or bars.empty:
        return pd.Series(dtype=float, name="signed_volume")
    required = {"open", "close", "volume"}
    missing = required - set(bars.columns)
    if missing:
        raise KeyError(f"bars missing required columns: {sorted(missing)}")
    sign = np.sign(bars["close"].astype(float) - bars["open"].astype(float))
    return (sign * bars["volume"].astype(float)).rename("signed_volume")


# ----------------------------------------------------------------------
# Order-flow imbalance (OFI)
# ----------------------------------------------------------------------
def compute_ofi_from_bars(bars: pd.DataFrame, window: int) -> pd.Series:
    """
    Bar-based OFI proxy: rolling sum of signed volume normalized by rolling
    sum of absolute volume. Range approximately ``[-1, +1]``.

    Used in Phase 1 backtests where L1 quote history is unavailable (IBKR
    ``reqHistoricalData`` returns OHLCV only). Switch to
    :func:`compute_ofi_from_quotes` during live trading.
    """
    signed = compute_signed_volume(bars)
    sv_sum = signed.rolling(window, min_periods=window).sum()
    av_sum = bars["volume"].abs().rolling(window, min_periods=window).sum()
    return (sv_sum / (av_sum + _EPS)).rename(f"ofi_bar_{window}")


def compute_ofi_from_quotes(quotes: pd.DataFrame, window: int) -> pd.Series:
    """
    True L1 order-flow imbalance per Cont, Kukanov & Stoikov (2014).

    Per quote update ``i``:

        e_i =  I(P_bid_i >= P_bid_{i-1}) * q_bid_i
             - I(P_bid_i <= P_bid_{i-1}) * q_bid_{i-1}
             - I(P_ask_i <= P_ask_{i-1}) * q_ask_i
             + I(P_ask_i >= P_ask_{i-1}) * q_ask_{i-1}

    OFI over the window is the rolling sum of ``e_i``. Positive values mean
    net buy-side pressure; negative values mean sell-side pressure.

    ``quotes`` must contain ``bid_price``, ``bid_size``, ``ask_price``,
    ``ask_size`` columns indexed by event timestamp.
    """
    if quotes is None or quotes.empty:
        return pd.Series(dtype=float, name=f"ofi_quote_{window}")
    required = {"bid_price", "bid_size", "ask_price", "ask_size"}
    missing = required - set(quotes.columns)
    if missing:
        raise KeyError(f"quotes missing required columns: {sorted(missing)}")

    bid_p = quotes["bid_price"].to_numpy(dtype=float)
    bid_s = quotes["bid_size"].to_numpy(dtype=float)
    ask_p = quotes["ask_price"].to_numpy(dtype=float)
    ask_s = quotes["ask_size"].to_numpy(dtype=float)

    bid_p_prev = np.concatenate([bid_p[:1], bid_p[:-1]])
    bid_s_prev = np.concatenate([bid_s[:1], bid_s[:-1]])
    ask_p_prev = np.concatenate([ask_p[:1], ask_p[:-1]])
    ask_s_prev = np.concatenate([ask_s[:1], ask_s[:-1]])

    bid_term = (
        (bid_p >= bid_p_prev).astype(float) * bid_s
        - (bid_p <= bid_p_prev).astype(float) * bid_s_prev
    )
    ask_term = (
        -(ask_p <= ask_p_prev).astype(float) * ask_s
        + (ask_p >= ask_p_prev).astype(float) * ask_s_prev
    )
    e = bid_term + ask_term

    series = pd.Series(e, index=quotes.index, name=f"ofi_quote_{window}")
    return series.rolling(window, min_periods=window).sum()


# ----------------------------------------------------------------------
# Absorption
# ----------------------------------------------------------------------
def compute_absorption(bars: pd.DataFrame, window: int) -> pd.Series:
    """
    Rolling sum of signed volume over ``window`` bars.

    Positive values indicate net buy-side flow being absorbed; negative
    values indicate net sell-side flow. Use short windows on sub-minute
    bars (~30-90 seconds) to capture intraday absorption setups: aggressive
    flow absorbed without much price movement tends to mean-revert.
    """
    return compute_signed_volume(bars).rolling(window, min_periods=window).sum().rename(
        f"absorption_{window}"
    )


# ----------------------------------------------------------------------
# Convenience builder
# ----------------------------------------------------------------------
def build_microstructure_features(
    bars: pd.DataFrame,
    params: Optional[dict] = None,
    cross_asset_bars: Optional[pd.DataFrame] = None,
    quotes: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Assemble every microstructure feature into a single DataFrame indexed
    like ``bars``. Suitable for concatenation with the regime features in
    :func:`ML_Classifier.stacked_meta_learner.build_score_features`.

    Parameters
    ----------
    bars : pd.DataFrame
        OHLCV bars with a DatetimeIndex and ``open``, ``close``, ``volume``.
    params : dict, optional
        Window sizes and toggles. Supported keys::

            rv_window             default 30
            rv_use_returns        default False
            rv_annualize          default False
            basis_window          default 60
            ofi_bar_window        default 30
            ofi_quote_window      default 100
            absorption_window     default 10
            session               default 'us'
            tz                    default 'America/New_York'
            enable_session_phase  default True
            enable_basis          default True   (requires cross_asset_bars)
            enable_quote_ofi      default False  (requires quotes)

    cross_asset_bars : pd.DataFrame, optional
        Bars of the second instrument used for the basis z-score. Only the
        ``close`` column is read. Index frequency should match ``bars``.
    quotes : pd.DataFrame, optional
        L1 quote stream. When ``enable_quote_ofi`` is True and quotes are
        provided, the true Cont-Kukanov-Stoikov OFI is computed and
        forward-filled onto the bar index.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(index=bars.index if bars is not None else [])

    p = params or {}
    cols: List[Union[pd.Series, pd.DataFrame]] = []

    cols.append(
        compute_realized_vol(
            bars["close"],
            int(p.get("rv_window", 30)),
            use_returns=bool(p.get("rv_use_returns", False)),
            annualize=bool(p.get("rv_annualize", False)),
        )
    )

    cols.append(compute_absorption(bars, int(p.get("absorption_window", 10))))
    cols.append(compute_ofi_from_bars(bars, int(p.get("ofi_bar_window", 30))))

    if p.get("enable_quote_ofi", False) and quotes is not None and not quotes.empty:
        quote_ofi = compute_ofi_from_quotes(quotes, int(p.get("ofi_quote_window", 100)))
        cols.append(quote_ofi.reindex(bars.index, method="ffill"))

    if p.get("enable_basis", True) and cross_asset_bars is not None and not cross_asset_bars.empty:
        basis = compute_basis_zscore(
            bars["close"],
            cross_asset_bars["close"],
            int(p.get("basis_window", 60)),
        )
        cols.append(basis.reindex(bars.index))

    if p.get("enable_session_phase", True) and isinstance(bars.index, pd.DatetimeIndex):
        cols.append(
            compute_session_phase(
                bars.index,
                session=str(p.get("session", "us")),
                tz=str(p.get("tz", "America/New_York")),
            )
        )

    feats = pd.concat(cols, axis=1)
    return feats.replace([np.inf, -np.inf], np.nan)
