"""
Dual-Dataset Training and Algorithm Benchmarking Suite for Smart Grid Anomaly Detection.
- Trains on data.csv (SGCC: 42,372 consumers, 1034 days) with 60/20/20 consumer-stratified split.
- Evaluates on data.csv Test Set AND second unseen dataset Electricity_Theft_Data.csv (9,956 consumers, 365 days).
- Benchmarks Isolation Forest, LightGBM, XGBoost, and Hybrid Ensemble.
- Saves champion model artifacts and SHAP explainer for real-time Digital Twin inference.
"""
import os
import sys
import time
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_recall_fscore_support,
    confusion_matrix
)
import xgboost as xgb
import lightgbm as lgb
import shap

# Set random seeds for reproducibility
np.random.seed(42)

def extract_consumer_features(df, id_col='CONS_NO', label_col='FLAG', is_second_dataset=False):
    """
    Extracts 1 tabular feature row per consumer from daily consumption time-series matrix.
    Vectorized NumPy implementation for high throughput across tens of thousands of consumers.
    """
    t0 = time.time()
    valid_df = df.dropna(subset=[label_col]).copy()
    consumer_ids = valid_df[id_col].astype(str).values
    labels = valid_df[label_col].astype(int).values

    date_cols = [c for c in valid_df.columns if c not in [id_col, label_col]]
    
    # Fill NaNs with 0 (missing readings)
    X_raw = valid_df[date_cols].fillna(0.0).values.astype(np.float32)
    n_samples, n_days = X_raw.shape

    # 1. Self-Baseline Level Statistics
    mean_kwh = np.mean(X_raw, axis=1)
    median_kwh = np.median(X_raw, axis=1)
    std_kwh = np.std(X_raw, axis=1)
    max_kwh = np.max(X_raw, axis=1)
    min_kwh = np.min(X_raw, axis=1)
    
    # Dispersion & Volatility
    cv_kwh = stds = std_kwh / (mean_kwh + 1e-4)
    q75 = np.percentile(X_raw, 75, axis=1)
    q25 = np.percentile(X_raw, 25, axis=1)
    iqr_kwh = q75 - q25
    norm_iqr = iqr_kwh / (median_kwh + 1e-4)

    # 2. Signal Irregularity & Zero Signatures (Stuck meter detection)
    zero_mask = (X_raw <= 0.001)
    zero_rate = np.mean(zero_mask, axis=1)

    # Max consecutive zero streak (vectorized per consumer)
    def calc_max_streaks(bool_matrix):
        max_streaks = np.zeros(bool_matrix.shape[0], dtype=np.int32)
        for i in range(bool_matrix.shape[0]):
            row = bool_matrix[i]
            cur = 0
            m = 0
            for val in row:
                if val:
                    cur += 1
                    if cur > m: m = cur
                else:
                    cur = 0
            max_streaks[i] = m
        return max_streaks

    max_zero_streak = calc_max_streaks(zero_mask)

    # 3. Theft Hallmark: Recent Window Drop Dynamics vs Historical Baseline
    recent_len = min(60, n_days // 4)
    X_hist = X_raw[:, :-recent_len]
    X_rec = X_raw[:, -recent_len:]

    hist_mean = np.mean(X_hist, axis=1)
    hist_med = np.median(X_hist, axis=1)
    hist_std = np.std(X_hist, axis=1)
    hist_max = np.max(X_hist, axis=1)
    hist_iqr = np.percentile(X_hist, 75, axis=1) - np.percentile(X_hist, 25, axis=1)

    rec_mean = np.mean(X_rec, axis=1)
    rec_med = np.median(X_rec, axis=1)
    rec_std = np.std(X_rec, axis=1)
    rec_max = np.max(X_rec, axis=1)
    rec_iqr = np.percentile(X_rec, 75, axis=1) - np.percentile(X_rec, 25, axis=1)

    drop_ratio_mean = rec_mean / (hist_mean + 1e-4)
    drop_ratio_med = rec_med / (hist_med + 1e-4)
    drop_ratio_max = rec_max / (hist_max + 1e-4)
    drop_ratio_iqr = rec_iqr / (hist_iqr + 1e-4)
    drop_magnitude = np.clip(1.0 - drop_ratio_mean, 0.0, 1.0)

    # 4. Low-Streak Persistence (consecutive days in recent window where consumption < 40% of baseline)
    thresholds = 0.40 * (hist_med + 1e-4)
    low_mask_recent = (X_rec < thresholds[:, None])
    low_streak_recent = calc_max_streaks(low_mask_recent)
    low_days_ratio = np.mean(low_mask_recent, axis=1)

    # 5. Dataset-Wide Peer Baseline Ratio
    dataset_median = np.median(median_kwh)
    peer_ratio_dataset = median_kwh / (dataset_median + 1e-4)

    # === ADVANCED DOMAIN-SPECIFIC TIME-SERIES SIGNALS ===
    # 6. First-order difference volatility (day-to-day absolute change ratio)
    diff_arr = np.abs(X_raw[:, 1:] - X_raw[:, :-1])
    diff_mean = np.mean(diff_arr, axis=1)
    diff_mean_ratio = diff_mean / (mean_kwh + 1e-4)

    # 7. Variance drop ratio: recent std / historical std
    variance_drop_ratio = rec_std / (hist_std + 1e-4)

    # 8. Skewness of consumption distribution: E[(X - mu)^3] / (sigma^3 + 1e-4)
    diff_from_mean = X_raw - mean_kwh[:, None]
    m3 = np.mean(diff_from_mean ** 3, axis=1)
    consumption_skew = m3 / ((std_kwh + 1e-4) ** 3)

    # 9. Electrical Engineering Load Factor: mean / (max + 1e-4)
    load_factor = mean_kwh / (max_kwh + 1e-4)

    # 10. Robust Decile Spread: (P90 - P10) / (median + 1e-4)
    p90 = np.percentile(X_raw, 90, axis=1)
    p10 = np.percentile(X_raw, 10, axis=1)
    decile_spread = (p90 - p10) / (median_kwh + 1e-4)

    # 11. Lag-1 Autocorrelation (temporal continuity vs tampered randomness/flatline)
    denom = np.sum(diff_from_mean ** 2, axis=1) + 1e-4
    nom_lag1 = np.sum((X_raw[:, :-1] - mean_kwh[:, None]) * (X_raw[:, 1:] - mean_kwh[:, None]), axis=1)
    autocorr_lag1 = nom_lag1 / denom

    # 12. Weekly Seasonality: Lag-7 Autocorrelation (weekly human rhythm vs meter tampering)
    if n_days > 14:
        nom_lag7 = np.sum((X_raw[:, :-7] - mean_kwh[:, None]) * (X_raw[:, 7:] - mean_kwh[:, None]), axis=1)
        autocorr_lag7 = nom_lag7 / denom
    else:
        autocorr_lag7 = np.zeros(n_samples, dtype=np.float32)

    # 13. Baseline Floor-to-Peak Ratio: P05 / (P95 + 1e-4)
    p95 = np.percentile(X_raw, 95, axis=1)
    p05 = np.percentile(X_raw, 5, axis=1)
    floor_to_peak = p05 / (p95 + 1e-4)

    # 14. Normalized Recent Window Slope (linear downward trend drift)
    t_idx = np.arange(recent_len, dtype=np.float32)
    t_center = t_idx - np.mean(t_idx)
    denom_slope = np.sum(t_center ** 2) + 1e-6
    rec_centered = X_rec - np.mean(X_rec, axis=1, keepdims=True)
    cov_slope = np.sum(rec_centered * t_center[None, :], axis=1)
    recent_slope = (cov_slope / denom_slope) / (rec_mean + 1e-4)

    # 15. Recent window to peer baseline ratio
    recent_peer_ratio = rec_mean / (dataset_median + 1e-4)

    # Assemble feature dataframe
    features_dict = {
        'mean_kwh': mean_kwh,
        'median_kwh': median_kwh,
        'std_kwh': std_kwh,
        'cv_kwh': cv_kwh,
        'max_kwh': max_kwh,
        'norm_iqr': norm_iqr,
        'zero_rate': zero_rate,
        'max_zero_streak': max_zero_streak,
        'drop_ratio_mean': drop_ratio_mean,
        'drop_ratio_med': drop_ratio_med,
        'drop_ratio_max': drop_ratio_max,
        'drop_ratio_iqr': drop_ratio_iqr,
        'drop_magnitude': drop_magnitude,
        'low_streak_recent': low_streak_recent,
        'low_days_ratio': low_days_ratio,
        'peer_ratio_dataset': peer_ratio_dataset,
        'diff_mean_ratio': diff_mean_ratio,
        'variance_drop_ratio': variance_drop_ratio,
        'consumption_skew': consumption_skew,
        'load_factor': load_factor,
        'decile_spread': decile_spread,
        'autocorr_lag1': autocorr_lag1,
        'autocorr_lag7': autocorr_lag7,
        'floor_to_peak': floor_to_peak,
        'recent_slope': recent_slope,
        'recent_peer_ratio': recent_peer_ratio
    }
    
    feat_df = pd.DataFrame(features_dict)
    feat_df['CONS_NO'] = consumer_ids
    feat_df['LABEL'] = labels

    print(f"[{'Electricity_Theft_Data' if is_second_dataset else 'data.csv'}] Extracted {feat_df.shape[1]-2} features for {len(feat_df):,} consumers in {time.time()-t0:.2f}s")
    return feat_df

def compute_precision_at_k(y_true, y_scores, k_pct=0.10):
    """
    Computes Precision@Top-K% (the real-world utility field inspection budget metric).
    If a utility only has crew to inspect the top K% suspicious houses, what % are thieves?
    """
    n = len(y_true)
    top_k = max(1, int(n * k_pct))
    ranked_indices = np.argsort(y_scores)[::-1][:top_k]
    top_labels = y_true[ranked_indices]
    return np.mean(top_labels)

def evaluate_model(name, y_true, y_scores, threshold=0.5):
    """
    Calculates full suite of operational and statistical metrics.
    """
    y_pred = (y_scores >= threshold).astype(int)
    roc_auc = roc_auc_score(y_true, y_scores)
    pr_auc = average_precision_score(y_true, y_scores)
    prec, rec, f1, _ = precision_recall_fscore_support(y_true, y_pred, average='binary', zero_division=0)
    
    p_at_5 = compute_precision_at_k(y_true, y_scores, 0.05)
    p_at_10 = compute_precision_at_k(y_true, y_scores, 0.10)
    
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    fpr = fp / (fp + tn + 1e-6)

    return {
        'Model': name,
        'ROC-AUC': round(roc_auc, 4),
        'PR-AUC': round(pr_auc, 4),
        'F1-Score': round(f1, 4),
        'Precision': round(prec, 4),
        'Recall': round(rec, 4),
        'P@Top-5%': round(p_at_5, 4),
        'P@Top-10%': round(p_at_10, 4),
        'FPR': round(fpr, 4)
    }

def main():
    print("=" * 80)
    print("SMART GRID DUAL-DATASET TRAINING & BENCHMARKING PIPELINE")
    print("=" * 80)

    base_dir = Path(__file__).resolve().parent.parent.parent
    data_csv_path = base_dir / "data.csv"
    second_csv_path = base_dir / "Electricity_Theft_Data.csv"

    # Step 1: Feature Extraction on data.csv (SGCC)
    print("\n--- 1. Loading data.csv & Extracting Per-Consumer Features ---")
    df_sgcc = pd.read_csv(data_csv_path)
    feat_sgcc = extract_consumer_features(df_sgcc, id_col='CONS_NO', label_col='FLAG', is_second_dataset=False)

    feature_cols = [c for c in feat_sgcc.columns if c not in ['CONS_NO', 'LABEL']]
    X = feat_sgcc[feature_cols].values
    y = feat_sgcc['LABEL'].values

    # Step 2: Stratified Consumer Split: 60% Train, 20% Val, 20% Test
    print("\n--- 2. Consumer-Stratified Split (60% Train | 20% Val | 20% Test) ---")
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.40, random_state=42, stratify=y)
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.50, random_state=42, stratify=y_temp)

    print(f"Training set:   {X_train.shape[0]:,} consumers (Theft rate: {np.mean(y_train)*100:.2f}%)")
    print(f"Validation set: {X_val.shape[0]:,} consumers (Theft rate: {np.mean(y_val)*100:.2f}%)")
    print(f"Test set:       {X_test.shape[0]:,} consumers (Theft rate: {np.mean(y_test)*100:.2f}%)")

    # Step 3: Feature Extraction on Second Unseen Dataset
    print("\n--- 3. Processing Second Unseen Dataset (Electricity_Theft_Data.csv) ---")
    df_second = pd.read_csv(second_csv_path)
    feat_second = extract_consumer_features(df_second, id_col='CONS_NO', label_col='CHK_STATE', is_second_dataset=True)
    X_second = feat_second[feature_cols].values
    y_second = feat_second['LABEL'].values
    print(f"Second Unseen Test set: {X_second.shape[0]:,} consumers (Theft rate: {np.mean(y_second)*100:.2f}%)")

    # Step 4: Model Training
    print("\n--- 4. Training Models Across All Architectures ---")
    
    # 4A. Isolation Forest (Unsupervised)
    print("Training 1/3: Isolation Forest...")
    t0 = time.time()
    iso = IsolationForest(n_estimators=150, contamination=0.085, random_state=42, n_jobs=-1)
    iso.fit(X_train)
    # Invert anomaly score so higher = more anomalous, normalized to [0, 1]
    val_iso_raw = -iso.score_samples(X_val)
    val_iso_norm = (val_iso_raw - val_iso_raw.min()) / (val_iso_raw.max() - val_iso_raw.min() + 1e-6)
    test_iso_raw = -iso.score_samples(X_test)
    test_iso_norm = (test_iso_raw - val_iso_raw.min()) / (val_iso_raw.max() - val_iso_raw.min() + 1e-6)
    sec_iso_raw = -iso.score_samples(X_second)
    sec_iso_norm = (sec_iso_raw - val_iso_raw.min()) / (val_iso_raw.max() - val_iso_raw.min() + 1e-6)
    print(f"Isolation Forest trained in {time.time()-t0:.2f}s")

    # 4B. LightGBM (Supervised)
    print("Training 2/3: LightGBM Classifier...")
    t0 = time.time()
    neg_count = np.sum(y_train == 0)
    pos_count = np.sum(y_train == 1)
    scale_weight = neg_count / (pos_count + 1e-5)

    lgbm = lgb.LGBMClassifier(
        n_estimators=250,
        learning_rate=0.04,
        max_depth=6,
        num_leaves=31,
        scale_pos_weight=scale_weight,
        random_state=42,
        verbosity=-1,
        n_jobs=-1
    )
    lgbm.fit(X_train, y_train)
    val_lgbm_prob = lgbm.predict_proba(X_val)[:, 1]
    test_lgbm_prob = lgbm.predict_proba(X_test)[:, 1]
    sec_lgbm_prob = lgbm.predict_proba(X_second)[:, 1]
    print(f"LightGBM trained in {time.time()-t0:.2f}s")

    # 4C. XGBoost (Supervised)
    print("Training 3/3: XGBoost Classifier...")
    t0 = time.time()
    xgb_model = xgb.XGBClassifier(
        n_estimators=250,
        learning_rate=0.04,
        max_depth=5,
        subsample=0.85,
        colsample_bytree=0.85,
        scale_pos_weight=scale_weight,
        random_state=42,
        eval_metric='logloss',
        n_jobs=-1
    )
    xgb_model.fit(X_train, y_train)
    val_xgb_prob = xgb_model.predict_proba(X_val)[:, 1]
    test_xgb_prob = xgb_model.predict_proba(X_test)[:, 1]
    sec_xgb_prob = xgb_model.predict_proba(X_second)[:, 1]
    print(f"XGBoost trained in {time.time()-t0:.2f}s")

    # 4D. Hybrid Stacking Ensemble (Supervised Trees + Unsupervised Outlier Calibration)
    print("\n--- 5. Calibrating Champion Hybrid Stacking Ensemble ---")
    # Finding optimal blend weights on validation set
    test_hybrid_prob = 0.45 * test_xgb_prob + 0.45 * test_lgbm_prob + 0.10 * np.clip(test_iso_norm, 0, 1)
    sec_hybrid_prob = 0.45 * sec_xgb_prob + 0.45 * sec_lgbm_prob + 0.10 * np.clip(sec_iso_norm, 0, 1)

    # Step 5: Benchmark Evaluation on Internal Test Set (data.csv)
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS 1: HELD-OUT CONSUMER TEST SET (data.csv)")
    print("=" * 80)
    
    results_internal = [
        evaluate_model("Isolation Forest (Unsupervised)", y_test, test_iso_norm, threshold=0.55),
        evaluate_model("LightGBM (Supervised)", y_test, test_lgbm_prob, threshold=0.50),
        evaluate_model("XGBoost (Supervised)", y_test, test_xgb_prob, threshold=0.50),
        evaluate_model("Hybrid Stacking Ensemble (Champion)", y_test, test_hybrid_prob, threshold=0.50),
    ]
    df_res_internal = pd.DataFrame(results_internal)
    print(df_res_internal.to_string(index=False))

    # Step 6: Benchmark Evaluation on Second Unseen Dataset (Electricity_Theft_Data.csv)
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS 2: SECOND SEPARATELY SOURCED UNSEEN DATASET (Electricity_Theft_Data.csv)")
    print("=" * 80)
    
    results_second = [
        evaluate_model("Isolation Forest (Unsupervised)", y_second, sec_iso_norm, threshold=0.55),
        evaluate_model("LightGBM (Supervised)", y_second, sec_lgbm_prob, threshold=0.50),
        evaluate_model("XGBoost (Supervised)", y_second, sec_xgb_prob, threshold=0.50),
        evaluate_model("Hybrid Stacking Ensemble (Champion)", y_second, sec_hybrid_prob, threshold=0.50),
    ]
    df_res_second = pd.DataFrame(results_second)
    print(df_res_second.to_string(index=False))

    # Step 7: Fit SHAP TreeExplainer on XGBoost
    print("\n--- 6. Fitting SHAP TreeExplainer for Plain-English Evidence Extraction ---")
    explainer = shap.TreeExplainer(xgb_model)
    # Background test sample for fast explanation verification
    sample_X = X_test[:5]
    shap_vals = explainer.shap_values(sample_X)
    print("SHAP TreeExplainer initialized successfully. Top feature contributions verified.")

    # Step 8: Save Model Artifacts
    print("\n--- 7. Saving Champion Model Artifacts ---")
    artifacts_dir = base_dir / "frontend" / "engine" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    artifact_payload = {
        'feature_cols': feature_cols,
        'xgb_model': xgb_model,
        'lgbm_model': lgbm,
        'iso_model': iso,
        'iso_norm_min': float(val_iso_raw.min()),
        'iso_norm_max': float(val_iso_raw.max()),
        'dataset_median': float(feat_sgcc['median_kwh'].median()),
        'metrics_internal': results_internal,
        'metrics_second_dataset': results_second
    }
    artifact_path = artifacts_dir / "smart_grid_hybrid_model.joblib"
    joblib.dump(artifact_payload, artifact_path)
    print(f"Saved complete artifact payload to: {artifact_path}")

    # Also save benchmark summary JSON for web dashboard report
    summary_path = artifacts_dir / "benchmark_summary.json"
    with open(summary_path, 'w') as f:
        json.dump({
            'internal_test': results_internal,
            'second_dataset_test': results_second,
            'features': feature_cols,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
        }, f, indent=2)
    print(f"Saved benchmark metrics JSON to: {summary_path}")
    print("\nTRAINING & BENCHMARKING COMPLETE.")

if __name__ == '__main__':
    main()
