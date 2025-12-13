import pandas as pd
from ML_Classifier.ml_trading_features import build_features

def predict_rule_ml_classifier(df: pd.DataFrame, trained: dict, params: dict) -> pd.DataFrame:
    """
    Apply the trained ML pipeline to new/live or historical data.
    Uses StrategySection indicators and global training params.

    Returns a DataFrame with probabilities and signals:
      - prob_up: probability of upward move
      - prob_down: probability of downward move
      - long_signal: 1 if prob_up >= threshold else 0
      - short_signal: 1 if prob_down >= threshold else 0
      - signal: +1 for long, -1 for short, 0 for none
    """
    if df.empty:
        return pd.DataFrame()

    feats = build_features(df, params)
    feature_cols = trained["feature_columns"]
    X_live = feats[feature_cols].copy()

    proba_up = trained["pipeline"].predict_proba(X_live)[:, 1]
    threshold = float(trained.get("decision_threshold", params.get("threshold", 0.6)))

    out = pd.DataFrame(index=X_live.index)
    out["prob_up"] = proba_up
    out["prob_down"] = 1.0 - out["prob_up"]

    # Buy when prob_up >= threshold
    out["long_signal"] = (out["prob_up"] >= threshold).astype(int)
    # Sell when prob_down >= threshold
    out["sell_signal"] = (out["prob_down"] >= threshold).astype(int)

    # Combined signal: +1 = buy, -1 = sell, 0 = hold
    out["signal"] = out["long_signal"] - out["sell_signal"]

    return out
