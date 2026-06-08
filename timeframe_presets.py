"""
Timeframe-specific default presets for meta-learner training and base indicators.

Each preset is keyed by the chart ``time_interval`` string used in the UI
(``OneMinute``, ``OneHour``, ``OneDay``, ``OneWeek``). ``OneHour`` values
match the original app defaults; other intervals are scaled for typical
bar duration on that timeframe.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

# Canonical indicator names (must match ``trading_strategies.trading_strategies`` keys).
INDICATOR_NAMES = (
    "DMA Crossing",
    "EMA Break",
    "RSI",
    "S/R Structure",
    "VWAP Break",
)

# Shared training keys surfaced in the Strategy training-params dialog.
TRAINING_KEYS = (
    "horizon",
    "up_barrier_atr",
    "down_barrier_atr",
    "vertical_bars",
    "embargo",
    "calibration",
    "decision_threshold",
    "n_splits",
    "learning_rate",
    "cost_bp",
    "atr_window",
)

# Behavioral feature / gate keys surfaced in the Strategy behavioral dialog.
BEHAVIORAL_KEYS = (
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
    "ofi_bar_window",
    "consensus_std_chop_threshold",
    "consensus_std_herd_threshold",
    "consensus_mean_herd_threshold",
    "chop_momentum_threshold",
    "gate_opening_threshold_bump",
    "gate_chop_threshold_bump",
    "gate_opening_block",
    "meta_learning_rate",
    "meta_max_iter",
    "meta_max_depth",
    "meta_l2_regularization",
    "behavioral_l2_regularization",
    "behavioral_max_depth",
)

# OneHour — original defaults (unchanged).
_ONE_HOUR_INDICATORS: Dict[str, dict] = {
    "DMA Crossing": {"short_window": 20, "long_window": 50},
    "EMA Break": {"short_window": 20, "long_window": 50},
    "RSI": {"lookback": 14, "overbought": 70, "oversold": 30},
    "S/R Structure": {"distance": 5},
    "VWAP Break": {"lookback": 14},
}

_ONE_HOUR_TRAINING: Dict[str, Any] = {
    "horizon": 10,
    "up_barrier_atr": 1.5,
    "down_barrier_atr": 1.5,
    "vertical_bars": 10,
    "embargo": 10,
    "calibration": "isotonic",
    "decision_threshold": 0.55,
    "n_splits": 5,
    "learning_rate": 0.05,
    "cost_bp": 5.0,
    "atr_window": 14,
}

_ONE_HOUR_BEHAVIORAL: Dict[str, Any] = {
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
    "ofi_bar_window": 10,
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
    "behavioral_l2_regularization": 0.5,
    "behavioral_max_depth": 4,
}

TIMEFRAME_PRESETS: Dict[str, Dict[str, Any]] = {
    "OneMinute": {
        "indicators": {
            "DMA Crossing": {"short_window": 10, "long_window": 30},
            "EMA Break": {"short_window": 9, "long_window": 21},
            "RSI": {"lookback": 9, "overbought": 75, "oversold": 25},
            "S/R Structure": {"distance": 20},
            "VWAP Break": {"lookback": 20},
        },
        "training": {
            "horizon": 45,
            "up_barrier_atr": 1.0,
            "down_barrier_atr": 1.0,
            "vertical_bars": 45,
            "embargo": 45,
            "calibration": "isotonic",
            "decision_threshold": 0.60,
            "n_splits": 5,
            "learning_rate": 0.05,
            "cost_bp": 10.0,
            "atr_window": 30,
        },
        "behavioral": {
            "enable_behavioral": False,
            "enable_behavioral_gate": False,
            "behavioral_in_direction_model": False,
            "enable_meta_label": False,
            "meta_threshold": 0.60,
            "enable_behavioral_consensus": True,
            "enable_behavioral_anchoring": True,
            "enable_behavioral_flow": True,
            "gate_learn_on_train": True,
            "or_minutes": 15,
            "ofi_bar_window": 30,
            "consensus_std_chop_threshold": 0.30,
            "consensus_std_herd_threshold": 0.12,
            "consensus_mean_herd_threshold": 0.20,
            "chop_momentum_threshold": 0.10,
            "gate_opening_threshold_bump": 0.06,
            "gate_chop_threshold_bump": 0.04,
            "gate_opening_block": False,
            "meta_learning_rate": 0.05,
            "meta_max_iter": 150,
            "meta_max_depth": 3,
            "meta_l2_regularization": 0.15,
            "behavioral_l2_regularization": 0.8,
            "behavioral_max_depth": 3,
        },
    },
    "OneHour": {
        "indicators": copy.deepcopy(_ONE_HOUR_INDICATORS),
        "training": copy.deepcopy(_ONE_HOUR_TRAINING),
        "behavioral": copy.deepcopy(_ONE_HOUR_BEHAVIORAL),
    },
    "OneDay": {
        "indicators": {
            "DMA Crossing": {"short_window": 20, "long_window": 50},
            "EMA Break": {"short_window": 12, "long_window": 26},
            "RSI": {"lookback": 14, "overbought": 70, "oversold": 30},
            "S/R Structure": {"distance": 10},
            "VWAP Break": {"lookback": 5},
        },
        "training": {
            "horizon": 5,
            "up_barrier_atr": 1.5,
            "down_barrier_atr": 1.5,
            "vertical_bars": 5,
            "embargo": 5,
            "calibration": "isotonic",
            "decision_threshold": 0.55,
            "n_splits": 5,
            "learning_rate": 0.05,
            "cost_bp": 5.0,
            "atr_window": 14,
        },
        "behavioral": {
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
            "ofi_bar_window": 5,
            "consensus_std_chop_threshold": 0.40,
            "consensus_std_herd_threshold": 0.18,
            "consensus_mean_herd_threshold": 0.30,
            "chop_momentum_threshold": 0.25,
            "gate_opening_threshold_bump": 0.04,
            "gate_chop_threshold_bump": 0.02,
            "gate_opening_block": False,
            "meta_learning_rate": 0.05,
            "meta_max_iter": 150,
            "meta_max_depth": 4,
            "meta_l2_regularization": 0.1,
            "behavioral_l2_regularization": 0.5,
            "behavioral_max_depth": 4,
        },
    },
    "OneWeek": {
        "indicators": {
            "DMA Crossing": {"short_window": 8, "long_window": 21},
            "EMA Break": {"short_window": 8, "long_window": 21},
            "RSI": {"lookback": 14, "overbought": 70, "oversold": 30},
            "S/R Structure": {"distance": 3},
            "VWAP Break": {"lookback": 4},
        },
        "training": {
            "horizon": 4,
            "up_barrier_atr": 1.5,
            "down_barrier_atr": 1.5,
            "vertical_bars": 4,
            "embargo": 4,
            "calibration": "isotonic",
            "decision_threshold": 0.55,
            "n_splits": 4,
            "learning_rate": 0.05,
            "cost_bp": 8.0,
            "atr_window": 14,
        },
        "behavioral": {
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
            "ofi_bar_window": 3,
            "consensus_std_chop_threshold": 0.45,
            "consensus_std_herd_threshold": 0.20,
            "consensus_mean_herd_threshold": 0.35,
            "chop_momentum_threshold": 0.35,
            "gate_opening_threshold_bump": 0.03,
            "gate_chop_threshold_bump": 0.02,
            "gate_opening_block": False,
            "meta_learning_rate": 0.05,
            "meta_max_iter": 120,
            "meta_max_depth": 4,
            "meta_l2_regularization": 0.1,
            "behavioral_l2_regularization": 0.5,
            "behavioral_max_depth": 4,
        },
    },
}

DEFAULT_TIMEFRAME = "OneHour"
FALLBACK_TIMEFRAME = "OneHour"


def normalize_timeframe(timeframe: str) -> str:
    """Return a known preset key, falling back to OneHour for unknown values."""
    if timeframe in TIMEFRAME_PRESETS:
        return timeframe
    return FALLBACK_TIMEFRAME


def get_indicator_presets(timeframe: str, strategy_name: str) -> dict:
    """Default indicator params for ``strategy_name`` on ``timeframe``."""
    tf = normalize_timeframe(timeframe)
    block = TIMEFRAME_PRESETS[tf]["indicators"]
    defaults = block.get(strategy_name)
    if defaults is None:
        return {}
    return copy.deepcopy(defaults)


def get_all_indicator_presets(timeframe: str) -> Dict[str, dict]:
    """Full indicator preset map for ``timeframe``."""
    tf = normalize_timeframe(timeframe)
    return copy.deepcopy(TIMEFRAME_PRESETS[tf]["indicators"])


def get_training_presets(timeframe: str) -> Dict[str, Any]:
    """Meta-learner training-param defaults for ``timeframe``."""
    tf = normalize_timeframe(timeframe)
    return copy.deepcopy(TIMEFRAME_PRESETS[tf]["training"])


def get_behavioral_presets(timeframe: str) -> Dict[str, Any]:
    """Behavioral feature / gate defaults for ``timeframe``."""
    tf = normalize_timeframe(timeframe)
    block = TIMEFRAME_PRESETS[tf].get("behavioral")
    if block is None:
        return copy.deepcopy(_ONE_HOUR_BEHAVIORAL)
    return copy.deepcopy(block)
