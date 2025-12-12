import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.model_selection import TimeSeriesSplit

from ML_Classifier.ml_trading_features import build_features
from ML_Classifier.ml_trading_labels import build_labels

def train_rule_ml_classifier(df: pd.DataFrame, params:dict) ->dict:
    """
    Train logistic regression classifier using time-series split.
    Returns a dict with pipeline, feature columns, metrics and thresholds.
    """
    # 1) Build features and labels
    feats = build_features(df, params)
    y = build_labels(df.loc[feats.index], params)
    
    common_idx = feats.index.intersection(y.index)
    X = feats.loc[common_idx]
    y = y.loc[common_idx]
    
    # 2) Define pipeline: scaler + logistic regression
    pipeline = Pipeline(steps=[
        ("scaler", StandardScaler() if params.get("standardize", True) else "passthrough"),
        ("clf", LogisticRegression(
            C = float(params.get("regularization_C", 1.0)),
            class_weight = params.get("class_weight", None),
            max_iter = 1000,
            solver="lbfgs"
        ))
    ])
    
    # 3) Time-series split for validation
    n_splits = int(params.get("n_splits", 5 ))
    tscv = TimeSeriesSplit(n_splits=n_splits)
    
    reports = []
    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    
        pipeline.fit(X_train, y_train)
    
        # --- Apply custom threshold ---
        probs = pipeline.predict_proba(X_test)[:, 1]  # probability of positive class
        thresh = float(params.get("threshold", 0.5))
        y_pred = (probs >= thresh).astype(int)
    
        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, average="weighted", zero_division=0)
        rec = recall_score(y_test, y_pred, average="weighted", zero_division=0)
        f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)
    
        reports.append({
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1": f1
        })
        # Optional: print(f"Fold {fold_idx+1}/{n_splits}\n{report}")
    
    # 4) Fit on all data
    pipeline.fit(X,y)
    
    # 5) Package results
    result = {
        "pipeline": pipeline,
        "feature_columns": list(X.columns),
        "validation_reports": reports,
        "decision_threshold": float(params.get("threshold", 0.6)),
        "horizon": int(params.get("horizon", 3)),
        "min_move": float(params.get("min_move", 0.0005))
    }
    return result