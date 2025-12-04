import pandas as pd
import numpy as np
from ml_trading_features import build_features

def predict_rule_ml_classifier(df: pd.DataFrame, trained: dict, params: dict) -> pd.DataFrame:
    """
    Apply the trained pipeline to new/live data.
    Returns a DataFrame with probabilities and signals.
    """
    # 1) Build features using the same function as training
    feats = build_features(df, params)
    
    # 2) Restrict to the trained feature columns
    feature_cols = trained["feature_columns"]
    X_live = feats[feature_cols].copy()
    
    # 3) Get probabilities for the positive class (y=1)
    proba = trained["pipeline"].predict_proba(X_live)[:, 1]
    threshold = float(trained.get("decision_threshold", params.get("threshold", 0.6)))
    
    # 4) Build output DataFrame
    out = pd.DataFrame(index=X_live.index)
    out["prib_up"] = proba
    out["raw_long"] = (out["prob_up"] >= threshold).astype(int)
    
    # 5) Optional RSI filter: suppress longs if overbought
    if params.get("avoid_overbought", True) and "rsi" in df.columns:
        out["rsi_overbought"] = (df.loc[out.index, "rsi"] > 70).astype(int)
        out["long_signal"] = np.where(out["rsi_overbought"] == 1, 0, out["raw_long"])
    else:
        out["long_signal"] = out["raw_long"]
    
    # 6) Short signals 
    out["prob_down"] = 1.0 - out["prob_up"]
    out["raw_short"] = (out["prob_down"] >= threshold).astype(int)

    if params.get("avoid_oversold", True) and "rsi" in df.columns:
        out["rsi_oversold"] = (df.loc[out.index, "rsi"] < 30).astype(int)
        out["short_signal"] = np.where(out["rsi_oversold"] == 1, 0, out["raw_short"])
    else:
        out["short_signal"] = out["raw_short"]
        
    # 7) Final signal preference
    allow_shorts = bool(params.get("allow_shorts", False))
    if not allow_shorts:
        out["signal"] = out["long_signal"]
    else:
        out["signal"] = out["long_signal"] - out["short_signal"]

    return out

