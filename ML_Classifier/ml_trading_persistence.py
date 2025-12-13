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

def save_training_artifacts(
    clf: Any,
    feature_params: Dict[str, Any],
    feature_columns: list,
    notes: Optional[str] = None
) -> str:
    """
    Persist classifier and its feature context.
    Returns the version string for later retrieval.
    """
    ensure_dir()
    version = now_ts()
    paths = build_paths(version)

    # Create versioned subdirectory
    os.makedirs(paths["base"], exist_ok=True)

    # Save model
    joblib.dump(clf, paths["model"])

    # Save feature params (what the builder used)
    with open(paths["feature_params"], "w") as f:
        json.dump(feature_params, f, indent=2)

    # Save feature schema (columns used in training)
    with open(paths["schema"], "w") as f:
        json.dump({"columns": feature_columns}, f, indent=2)

    # Save metadata for audit/selection UI
    metadata = {
        "version": version,
        "created_at": version,
        "notes": notes or "",
        "files": {k: v for k, v in paths.items() if k != "base"}
    }
    with open(paths["metadata"], "w") as f:
        json.dump(metadata, f, indent=2)

    return version

def list_versions() -> list:
    ensure_dir()
    return sorted([d for d in os.listdir(DEFAULT_DIR)
                   if os.path.isdir(os.path.join(DEFAULT_DIR, d))])

def latest_version() -> Optional[str]:
    versions = list_versions()
    return versions[-1] if versions else None

def load_artifacts(version: Optional[str] = None) -> Dict[str, Any]:
    """
    Load model + feature context for inference.
    If version is None, loads the latest.
    """
    ensure_dir()
    ver = version or latest_version()
    if not ver:
        raise FileNotFoundError("No persisted models found.")

    paths = build_paths(ver)

    # Load model
    clf = joblib.load(paths["model"])

    # Load params + schema
    with open(paths["feature_params"], "r") as f:
        feature_params = json.load(f)
    with open(paths["schema"], "r") as f:
        schema = json.load(f)

    return {
        "version": ver,
        "clf": clf,
        "feature_params": feature_params,
        "feature_columns": schema["columns"]
    }

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
