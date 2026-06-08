import os
import json
import time
from typing import Dict, Any, Optional
import joblib
import pandas as pd

DEFAULT_DIR = "artifacts"  # single folder for model + features + metadata

def ensure_dir(path: str = DEFAULT_DIR) -> None:
    os.makedirs(path, exist_ok=True)

def now_ts() -> str:
    # human-readable timestamp
    return time.strftime("%Y-%m-%d_%H-%M-%S")

def build_paths(version: str) -> Dict[str, str]:
    # centralize all filenames by version
    base = os.path.join(DEFAULT_DIR, version)
    return {
        "base": base,
        "model": os.path.join(base, "model.pkl"),
        "metadata": os.path.join(base, "metadata.json"),
        "feature_params": os.path.join(base, "feature_params.json"),
        "schema": os.path.join(base, "feature_schema.json"),
    }

def save_training_artifacts(result: dict, notes: str = "") -> str:
    """
    Persist the full training result package (pipeline, metrics, schema, params).
    """
    ensure_dir()
    version = now_ts()
    paths = build_paths(version)
    os.makedirs(paths["base"], exist_ok=True)

    joblib.dump(result["pipeline"], paths["model"])

    meta_block = result.get("meta_label") or {}
    if meta_block.get("trained") and meta_block.get("pipeline") is not None:
        joblib.dump(meta_block["pipeline"], os.path.join(paths["base"], "meta_label.pkl"))

    result_copy = {k: v for k, v in result.items() if k != "pipeline"}
    if "meta_label" in result_copy and isinstance(result_copy["meta_label"], dict):
        meta_copy = dict(result_copy["meta_label"])
        meta_copy.pop("pipeline", None)
        result_copy["meta_label"] = meta_copy
    result_copy["notes"] = notes
    with open(paths["metadata"], "w") as f:
        json.dump(result_copy, f, indent=2, default=str)

    return version

def list_versions() -> list:
    ensure_dir()
    return sorted([d for d in os.listdir(DEFAULT_DIR)
                   if os.path.isdir(os.path.join(DEFAULT_DIR, d))])

def latest_version() -> Optional[str]:
    versions = list_versions()
    return versions[-1] if versions else None

def load_artifacts(version: Optional[str] = None) -> dict:
    ver = version or latest_version()
    if not ver:
        raise FileNotFoundError("No persisted models found.")
    paths = build_paths(ver)

    pipeline = joblib.load(paths["model"])

    with open(paths["metadata"], "r") as f:
        meta = json.load(f)

    result = {"pipeline": pipeline, **meta, "version": ver}

    meta_path = os.path.join(paths["base"], "meta_label.pkl")
    if os.path.exists(meta_path):
        meta_pipeline = joblib.load(meta_path)
        meta_block = dict(result.get("meta_label") or {})
        meta_block["pipeline"] = meta_pipeline
        meta_block["trained"] = True
        result["meta_label"] = meta_block

    return result

def align_features_for_inference(feats: "pd.DataFrame", expected_columns: list) -> "pd.DataFrame":
    """
    Reorder and fill missing columns so the model sees the same schema it was trained on.
    Missing columns become zeros; extra columns are dropped.
    """
    # Drop extras
    aligned = feats.reindex(columns=expected_columns)
    # Fill missing with zeros (or choose another default)
    return aligned.fillna(0.0)

def log_inference_step(
    version: str,
    timestamp: str,
    features_row: Dict[str, float],
    prediction: float,
    extra: Optional[Dict[str, Any]] = None
) -> None:
    """
    Append a line to an inference log for audit/replay.
    """
    ensure_dir()
    logfile = os.path.join(DEFAULT_DIR, version, "inference_log.ndjson")
    record = {
        "ts": timestamp,
        "prediction": prediction,
        "features": features_row,
        "extra": extra or {}
    }
    with open(logfile, "a") as f:
        f.write(json.dumps(record) + "\n")
