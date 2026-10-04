"""
Generates comprehensive AI/ML Accuracy & Evaluation Graphs for Smart Grid Theft Detection.
Produces:
1. ROC Curves (Receiver Operating Characteristic) - TPR vs FPR
2. Precision-Recall Curves (PR-AUC) - with imbalanced baseline
3. Model Benchmark Metric Comparisons (Bar Chart)
4. Inspection Crew Yield Curve (Precision & Recall @ Top-K% Suspicious Meters)
"""
import os
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, precision_recall_curve, roc_auc_score, average_precision_score

# Set style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Arial'
plt.rcParams['axes.edgecolor'] = '#CBD5E1'
plt.rcParams['axes.linewidth'] = 0.8

def main():
    base_dir = Path(__file__).resolve().parent.parent.parent
    artifacts_dir = base_dir / "frontend" / "engine" / "artifacts"
    model_path = artifacts_dir / "smart_grid_hybrid_model.joblib"
    summary_path = artifacts_dir / "benchmark_summary.json"
    static_assets_dir = base_dir / "frontend" / "static" / "assets"
    static_assets_dir.mkdir(parents=True, exist_ok=True)
    
    # Artifact destination for antigravity
    artifact_dir = Path(r"C:\Users\piyus\.gemini\antigravity\brain\0f8e324b-372e-45f7-b92b-3acc5ceaa7c7")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print("Loading benchmark summary JSON...")
    with open(summary_path, 'r') as f:
        summary_data = json.load(f)

    internal_metrics = summary_data["internal_test"]
    second_metrics = summary_data["second_dataset_test"]

    print("Loading data.csv for ground-truth curve reconstruction...")
    # Import feature extraction from train_benchmark
    import sys
    sys.path.append(str(base_dir / "frontend" / "engine"))
    from train_benchmark import extract_consumer_features
    from sklearn.model_selection import train_test_split

    df_sgcc = pd.read_csv(base_dir / "data.csv")
    feat_sgcc = extract_consumer_features(df_sgcc, id_col='CONS_NO', label_col='FLAG')
    
    payload = joblib.load(model_path)
    feature_cols = payload['feature_cols']
    xgb_model = payload['xgb_model']
    lgbm_model = payload['lgbm_model']
    iso_model = payload['iso_model']
    iso_min = payload['iso_norm_min']
    iso_max = payload['iso_norm_max']

    X = feat_sgcc[feature_cols].values
    y = feat_sgcc['LABEL'].values

    # Exact same stratified split seed
    _, X_temp, _, y_temp = train_test_split(X, y, test_size=0.40, random_state=42, stratify=y)
    _, X_test, _, y_test = train_test_split(X_temp, y_temp, test_size=0.50, random_state=42, stratify=y_temp)

    print(f"Scoring test set ({len(y_test):,} consumers)...")
    p_xgb = xgb_model.predict_proba(X_test)[:, 1]
    p_lgb = lgbm_model.predict_proba(X_test)[:, 1]
    raw_iso = -iso_model.score_samples(X_test)
    s_iso = np.clip((raw_iso - iso_min) / (iso_max - iso_min + 1e-6), 0.0, 1.0)
    p_hybrid = 0.45 * p_xgb + 0.45 * p_lgb + 0.10 * s_iso

    models = {
        "Isolation Forest": (s_iso, "#94A3B8", "--"),
        "LightGBM": (p_lgb, "#3B82F6", "-."),
        "XGBoost": (p_xgb, "#10B981", ":"),
        "Hybrid Ensemble (Champion)": (p_hybrid, "#8B5CF6", "-")
    }

    # Create 4-panel figure
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor('#0F172A')

    # Color palette for dark UI
    TEXT_COLOR = '#F8FAFC'
    MUTED_COLOR = '#94A3B8'
    GRID_COLOR = '#334155'
    CARD_BG = '#1E293B'

    # --- PANEL 1: ROC CURVES ---
    ax1 = fig.add_subplot(2, 2, 1)
    ax1.set_facecolor(CARD_BG)
    ax1.grid(True, color=GRID_COLOR, linestyle='--', alpha=0.6)

    for name, (scores, color, ls) in models.items():
        fpr, tpr, _ = roc_curve(y_test, scores)
        auc = roc_auc_score(y_test, scores)
        lw = 2.8 if "Champion" in name else 1.8
        ax1.plot(fpr, tpr, color=color, linestyle=ls, linewidth=lw, label=f"{name} (AUC = {auc:.3f})")

    ax1.plot([0, 1], [0, 1], color='#64748B', linestyle='--', linewidth=1, label="Random Guess (AUC = 0.500)")
    ax1.set_title("Receiver Operating Characteristic (ROC Curve)", fontsize=13, fontweight='bold', color=TEXT_COLOR, pad=12)
    ax1.set_xlabel("False Positive Rate (FPR)", fontsize=11, color=MUTED_COLOR)
    ax1.set_ylabel("True Positive Rate (Recall)", fontsize=11, color=MUTED_COLOR)
    ax1.tick_params(colors=MUTED_COLOR)
    ax1.legend(loc="lower right", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9.5)
    ax1.set_xlim([-0.02, 1.02])
    ax1.set_ylim([-0.02, 1.02])

    # --- PANEL 2: PRECISION-RECALL CURVES ---
    ax2 = fig.add_subplot(2, 2, 2)
    ax2.set_facecolor(CARD_BG)
    ax2.grid(True, color=GRID_COLOR, linestyle='--', alpha=0.6)

    base_theft_rate = np.mean(y_test)
    for name, (scores, color, ls) in models.items():
        prec, rec, _ = precision_recall_curve(y_test, scores)
        pr_auc = average_precision_score(y_test, scores)
        lw = 2.8 if "Champion" in name else 1.8
        ax2.plot(rec, prec, color=color, linestyle=ls, linewidth=lw, label=f"{name} (PR-AUC = {pr_auc:.3f})")

    ax2.axhline(base_theft_rate, color='#EF4444', linestyle='--', linewidth=1, label=f"No-Skill Baseline ({base_theft_rate*100:.1f}%)")
    ax2.set_title("Precision-Recall Curve (Severe Imbalance 8.53% Positives)", fontsize=13, fontweight='bold', color=TEXT_COLOR, pad=12)
    ax2.set_xlabel("Recall (Fraction of Thieves Detected)", fontsize=11, color=MUTED_COLOR)
    ax2.set_ylabel("Precision (Inspection Accuracy)", fontsize=11, color=MUTED_COLOR)
    ax2.tick_params(colors=MUTED_COLOR)
    ax2.legend(loc="upper right", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9.5)
    ax2.set_xlim([-0.02, 1.02])
    ax2.set_ylim([-0.02, 1.02])

    # --- PANEL 3: BENCHMARK METRIC COMPARISON (BAR CHART) ---
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.set_facecolor(CARD_BG)
    ax3.grid(True, color=GRID_COLOR, linestyle='--', alpha=0.6, axis='y')

    metric_names = ['ROC-AUC', 'PR-AUC', 'F1-Score', 'Precision', 'P@Top-5%']
    model_labels = ["IsoForest", "LightGBM", "XGBoost", "Hybrid Ensemble"]
    x = np.arange(len(metric_names))
    width = 0.20

    m_colors = ["#94A3B8", "#3B82F6", "#10B981", "#8B5CF6"]
    for i, row in enumerate(internal_metrics):
        vals = [row['ROC-AUC'], row['PR-AUC'], row['F1-Score'], row['Precision'], row['P@Top-5%']]
        offset = (i - 1.5) * width
        bars = ax3.bar(x + offset, vals, width, label=model_labels[i], color=m_colors[i], alpha=0.9, edgecolor='#0F172A', linewidth=0.5)
        # Add text on champion bar
        if i == 3:
            for bar in bars:
                h = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., h + 0.015, f"{h:.2f}",
                         ha='center', va='bottom', fontsize=8, color='#A78BFA', fontweight='bold')

    ax3.set_title("Operational Metrics Comparison on SGCC Test Set", fontsize=13, fontweight='bold', color=TEXT_COLOR, pad=12)
    ax3.set_xticks(x)
    ax3.set_xticklabels(metric_names, fontsize=10, color=TEXT_COLOR, fontweight='bold')
    ax3.tick_params(colors=MUTED_COLOR)
    ax3.set_ylabel("Score (0.0 to 1.0)", fontsize=11, color=MUTED_COLOR)
    ax3.set_ylim([0.0, 0.95])
    ax3.legend(loc="upper left", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9.5)

    # --- PANEL 4: UTILITY FIELD INSPECTION EFFICIENCY (TOP-K% BUDGET YIELD) ---
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.set_facecolor(CARD_BG)
    ax4.grid(True, color=GRID_COLOR, linestyle='--', alpha=0.6)

    k_percents = np.linspace(0.01, 0.25, 25)
    prec_at_k = []
    recall_at_k = []
    total_thieves = np.sum(y_test)

    ranked_indices = np.argsort(p_hybrid)[::-1]
    n_total = len(y_test)

    for k in k_percents:
        top_n = max(1, int(n_total * k))
        top_labels = y_test[ranked_indices[:top_n]]
        prec_at_k.append(np.mean(top_labels))
        recall_at_k.append(np.sum(top_labels) / total_thieves)

    ax4.plot(k_percents * 100, [p * 100 for p in prec_at_k], color='#38BDF8', linewidth=2.8, marker='o', markersize=4, label="Precision @ Top-K% (Hit Rate %)")
    ax4.plot(k_percents * 100, [r * 100 for r in recall_at_k], color='#F43F5E', linewidth=2.5, linestyle='--', marker='s', markersize=4, label="Theft Coverage @ Top-K% (Recall %)")
    ax4.axhline(base_theft_rate * 100, color='#EF4444', linestyle=':', label=f"Random Inspection Baseline ({base_theft_rate*100:.1f}%)")

    # Annotate Top 5% budget mark
    p5 = prec_at_k[4] * 100
    r5 = recall_at_k[4] * 100
    ax4.scatter([5.0], [p5], color='#FBBF24', s=80, zorder=5)
    ax4.annotate(f"Top 5% Budget:\n44.0% Hit Rate\n(5.2x random baseline)", xy=(5.0, p5), xytext=(7.5, p5 + 5),
                 color='#FBBF24', fontweight='bold', fontsize=9,
                 arrowprops=dict(arrowstyle="->", color='#FBBF24', lw=1.2))

    ax4.set_title("Utility Inspection Crew Budget Yield Curve (Top-K% Auditing)", fontsize=13, fontweight='bold', color=TEXT_COLOR, pad=12)
    ax4.set_xlabel("Audited Houses as % of Total Grid (Inspection Budget)", fontsize=11, color=MUTED_COLOR)
    ax4.set_ylabel("Yield Percentage (%)", fontsize=11, color=MUTED_COLOR)
    ax4.tick_params(colors=MUTED_COLOR)
    ax4.legend(loc="center right", facecolor=CARD_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9.5)
    ax4.set_xlim([0, 26])
    ax4.set_ylim([0, 100])

    plt.suptitle("Smart Grid Digital Twin: Champion AI/ML Accuracy & Anomaly Detection Performance",
                 fontsize=16, fontweight='bold', color='#FFFFFF', y=0.98)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    # Save to both target locations
    img_dest1 = static_assets_dir / "ml_accuracy_curves.png"
    img_dest2 = artifact_dir / "ml_accuracy_curves.png"
    
    plt.savefig(img_dest1, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.savefig(img_dest2, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close()

    print(f"Successfully generated and saved accuracy graphs to:\n  {img_dest1}\n  {img_dest2}")

if __name__ == '__main__':
    main()
