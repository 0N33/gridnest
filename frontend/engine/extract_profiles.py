"""
Extracts 48 real consumer time-series from data.csv and binds them to the 48 Digital Twin buildings.
Preserves real Kaggle CONS_NO IDs, labels (FLAG=1 / FLAG=0), and authentic recorded kWh time-series.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

def main():
    print("Loading data.csv to select 48 authentic Kaggle consumer profiles...")
    base_dir = Path(__file__).resolve().parent.parent.parent
    data_csv = base_dir / "data.csv"

    # Load first 12,000 rows
    df_all = pd.read_csv(data_csv, nrows=12000)
    date_cols = [c for c in df_all.columns if c not in ["CONS_NO", "FLAG"]]

    thieves_df = df_all[df_all["FLAG"] == 1].copy()
    normals_df = df_all[df_all["FLAG"] == 0].copy()

    # Select the last 60 dates for high-recency comparison
    window_cols = date_cols[-60:]
    dates_list = window_cols

    # Filter candidates with good completeness
    thieves_clean = thieves_df.dropna(subset=window_cols[:30])
    normals_clean = normals_df.dropna(subset=window_cols[:45])

    print(f"Eligible records: {len(thieves_clean)} thieves, {len(normals_clean)} normals")

    # Evaluate drop dynamics on thieves
    t_vals = thieves_clean[window_cols].fillna(0.0).values
    t_hist = t_vals[:, :40].mean(axis=1)
    t_rec = t_vals[:, 40:].mean(axis=1)
    t_ratio = t_rec / (t_hist + 1e-4)

    drop_indices = np.where((t_ratio > 0.15) & (t_ratio < 0.45) & (t_hist > 8.0))[0]
    print(f"Identified {len(drop_indices)} real Kaggle thieves with pronounced drops.")

    thief_rows = [thieves_clean.iloc[idx] for idx in drop_indices]

    profiles = {}

    def make_profile(twin_id, row, scenario_name, custom_cat=None):
        vals = [float(x) if pd.notnull(x) else 0.0 for x in row[window_cols]]
        hist_30 = vals[:30]
        rec_30 = vals[30:]
        h_mean = float(np.mean(hist_30))
        h_std = float(max(0.1, np.std(hist_30)))
        h_med = float(np.median(hist_30))
        r_mean = float(np.mean(rec_30))
        r_med = float(np.median(rec_30))
        dr = float(r_mean / (h_mean + 1e-4))

        return {
            "twin_id": twin_id,
            "kaggle_id": str(row["CONS_NO"]),
            "kaggle_flag": int(row["FLAG"]),
            "scenario": scenario_name,
            "category": custom_cat or ("Commercial" if h_mean > 20.0 else "Residential"),
            "dates": dates_list,
            "daily_kwh_history": [round(v, 2) for v in vals],
            "historical_mean_kwh": round(h_mean, 2),
            "historical_std_kwh": round(h_std, 2),
            "historical_median_kwh": round(h_med, 2),
            "recent_mean_kwh": round(r_mean, 2),
            "recent_median_kwh": round(r_med, 2),
            "drop_ratio": round(dr, 3),
            "drop_pct": round((1.0 - dr) * 100.0, 1) if dr < 1.0 else 0.0,
            "is_anomaly": scenario_name != "NORMAL"
        }

    # Assign key scenarios to specific real Kaggle consumers
    profiles["CONS_N_004"] = make_profile("CONS_N_004", thief_rows[0], "THEFT_BYPASS", "Commercial")
    profiles["CONS_N_009"] = make_profile("CONS_N_009", thief_rows[1], "THEFT_TAMPER_MAGNETIC", "Residential")
    profiles["CONS_N_015"] = make_profile("CONS_N_015", normals_clean.iloc[10], "METER_MALFUNCTION_STUCK", "Commercial")
    profiles["CONS_N_021"] = make_profile("CONS_N_021", normals_clean.iloc[15], "COMM_FAILURE_DROPPED", "Residential")

    profiles["CONS_S_003"] = make_profile("CONS_S_003", normals_clean.iloc[20], "LEGITIMATE_EV_SURGE", "Commercial")
    profiles["CONS_S_011"] = make_profile("CONS_S_011", normals_clean.iloc[25], "METER_MALFUNCTION_ZERO", "Residential")
    profiles["CONS_S_018"] = make_profile("CONS_S_018", thief_rows[2], "THEFT_FLAT_FRAUD", "Commercial")

    # Map remaining houses to real normal consumers from data.csv
    norm_idx = 35
    for i in range(1, 25):
        cid = f"CONS_N_{i:03d}"
        if cid not in profiles:
            profiles[cid] = make_profile(cid, normals_clean.iloc[norm_idx], "NORMAL")
            norm_idx += 1

    for i in range(1, 25):
        cid = f"CONS_S_{i:03d}"
        if cid not in profiles:
            profiles[cid] = make_profile(cid, normals_clean.iloc[norm_idx], "NORMAL")
            norm_idx += 1

    out_file = base_dir / "frontend" / "engine" / "artifacts" / "kaggle_consumer_profiles.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(profiles, f, indent=2)

    print(f"Saved complete 48-building Kaggle dataset binding to: {out_file}")
    for cid in ["CONS_N_004", "CONS_N_009", "CONS_S_018", "CONS_N_001"]:
        p = profiles[cid]
        print(f"  {cid}: Kaggle ID={p['kaggle_id'][:16]}... | FLAG={p['kaggle_flag']} | Hist={p['historical_mean_kwh']} -> Rec={p['recent_mean_kwh']} kWh/d (Drop: {p['drop_pct']}%)")

if __name__ == "__main__":
    main()
