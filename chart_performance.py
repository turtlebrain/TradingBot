"""
Chart data windowing and decimation helpers.

Phase 3 engine evaluation (only needed if Phase 1+2 are insufficient):
- Pillow bitmap: lowest migration cost within Tkinter; one canvas image per frame.
- pyqtgraph: best native performance for large series; requires PyQt/PySide UI migration.
- Embedded web (Lightweight Charts / Plotly WebGL): best trading UX at 10k+ bars;
  adds embed/packaging complexity. Recommendation: stay on ChartForgeTK with
  viewport bucketing unless TradingView-grade pan/zoom is required.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

OHLC_COLUMNS = ("open", "high", "low", "close")


def slice_visible_window(
    df: pd.DataFrame,
    window_size: Optional[int],
    view_start: int = 0,
) -> Tuple[pd.DataFrame, int]:
    """Return a contiguous slice of ``df`` and the clamped start index."""
    if df.empty or window_size is None:
        return df, 0

    n = len(df)
    window_size = max(1, int(window_size))
    start = max(0, min(int(view_start), max(0, n - window_size)))
    end = min(n, start + window_size)
    return df.iloc[start:end].copy(), start


def bucket_ohlc_df(df: pd.DataFrame, max_buckets: int) -> pd.DataFrame:
    """
    Aggregate OHLC rows into at most ``max_buckets`` candles (one per pixel column).

    Preserves DatetimeIndex when present (uses first timestamp in each bucket).
    """
    if df.empty or max_buckets <= 0 or len(df) <= max_buckets:
        return df

    missing = set(OHLC_COLUMNS) - set(df.columns)
    if missing:
        raise KeyError(f"DataFrame missing OHLC columns: {sorted(missing)}")

    n = len(df)
    bucket_size = int(np.ceil(n / max_buckets))
    rows = []
    index_values = []

    for start in range(0, n, bucket_size):
        chunk = df.iloc[start : start + bucket_size]
        rows.append(
            {
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
            }
        )
        index_values.append(chunk.index[0])

    out = pd.DataFrame(rows, index=index_values)
    out.index.name = df.index.name
    return out


def prepare_ohlc_for_display(
    df: pd.DataFrame,
    window_size: Optional[int],
    view_start: int,
    max_draw_bars: int,
) -> Tuple[pd.DataFrame, int]:
    """Slice to the visible window, then bucket if still wider than ``max_draw_bars``."""
    visible, start = slice_visible_window(df, window_size, view_start)
    if len(visible) > max_draw_bars:
        visible = bucket_ohlc_df(visible, max_draw_bars)
    return visible, start


def downsample_line(values: Sequence[float], max_points: int) -> List[float]:
    """
    Downsample a numeric series to at most ``max_points`` using min/max envelopes
    per bucket so spikes are preserved.
    """
    values_out, _ = downsample_line_with_index(values, None, max_points)
    return values_out


def downsample_line_with_index(
    values: Sequence[float],
    index: Optional[Sequence],
    max_points: int,
) -> Tuple[List[float], Optional[List]]:
    """
    Downsample values and return index labels aligned to each plotted point.

    Each output point gets the timestamp/index from the middle of its source bucket.
    """
    arr = np.asarray(values, dtype=float)
    index_list = list(index) if index is not None else None

    if arr.size <= max_points or max_points <= 0:
        return arr.tolist(), index_list

    bucket_size = int(np.ceil(arr.size / max_points))
    out_vals: List[float] = []
    out_idx: List = []

    for start in range(0, arr.size, bucket_size):
        chunk = arr[start : start + bucket_size]
        mid = min(start + chunk.size // 2, arr.size - 1)
        bucket_label = index_list[mid] if index_list is not None else None

        if chunk.size == 1:
            out_vals.append(float(chunk[0]))
            if index_list is not None:
                out_idx.append(bucket_label)
        else:
            lo, hi = float(chunk.min()), float(chunk.max())
            if lo <= hi:
                out_vals.extend([lo, hi])
            else:
                out_vals.extend([hi, lo])
            if index_list is not None:
                out_idx.extend([bucket_label, bucket_label])

    cap = max_points * 2
    out_vals = out_vals[:cap]
    if index_list is not None:
        out_idx = out_idx[: len(out_vals)]
        return out_vals, out_idx
    return out_vals, None


def downsample_datasets(
    datasets: List[dict],
    max_points: int,
) -> List[dict]:
    """Apply ``downsample_line`` to each dataset's ``data`` list."""
    out = []
    for dataset in datasets:
        copied = dict(dataset)
        copied["data"] = downsample_line(dataset["data"], max_points)
        out.append(copied)
    return out
