# Smart Grid Anomaly Investigation Report: CONS_S_018
**Report ID:** `RPT-Zone-018-B1B02A` | **Generated At:** `2026-10-05T07:15:00` | **Priority Rank:** `#1`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `CONS_S_018` / `MTR_S_018` |
| **Consumer Name** | Residential #18 (Z2_South) |
| **Category & Contracted Load** | Residential (4.5 kW) |
| **Zone & Feeder** | Zone_2_South (TX_102 / FDR_SOUTH_11KV) |
| **Final Anomaly Score** | **`97.0 / 100`** (CRITICAL) |
| **Probable Cause** | **`THEFT_TAMPERING`** |
| **Diagnostic Confidence** | **`88.8%`** |

---


### Historical Benchmark vs. Real-Time Telemetry Audit
| Audit Metric | Ground-Truth Historical Record | Real-Time Telemetry (15-min streaming) |
|---|---|---|
| **Dataset Source / Benchmark** | State Grid Corp China (`data.csv`) | Digital Twin IoT Streaming Telemetry |
| **Kaggle Consumer Hash** | `8D32642A92C55B4F7C7DE4DD5CD13BAD` | `MTR_S_018` |
| **Benchmark Ground Truth** | `THEFT / NON-TECHNICAL LOSS (FLAG=1)` | Diagnostic Classification: `THEFT_TAMPERING` |
| **Daily Energy Baseline** | `20.75 kWh/day` | Real-time Extrapolated: `2.32 kWh/day` |
| **Energy Divergence (\Delta)** | Historical Reference | **`-88.8%`** (`+18.43 kWh/day`) |
| **Cumulative Theft / Divergence (30-day)** | Historical Baseline Trajectory | **`397.9 kWh`** |
| **Estimated Utility Revenue Loss** | - | **`₹2,984.47`** (@ ₹7.50/kWh) |
| **Temporal Onset Point** | Historical Shift Changepoint | `Day 4` |

---

### AI/ML Hybrid Ensemble Attribution
| Component Model | Architecture | Raw Prediction | Ensemble Weight |
|---|---|---|---|
| **XGBoost Classifier** | Supervised Gradient Boosted Trees | `P(Theft) = 0.515` | 45% |
| **LightGBM Classifier** | Supervised Leaf-Wise Trees | `P(Theft) = 0.465` | 45% |
| **Isolation Forest** | Unsupervised Isolation Trees | `Anomaly = 0.261` | 10% |
| **Hybrid Stacking Blend** | Multi-Model Meta-Learner | **Score: `97.0 / 100`** | **100%** |

#### Top SHAP Feature Impacts (XGBoost TreeExplainer)
| Feature Name | Observed Value | SHAP Impact (\Delta log-odds) |
|---|---|---|
| `Std Kwh` | `12.729` | `+0.361` |
| `Max Kwh` | `50.0` | `+0.357` |
| `Mean Kwh` | `14.008` | `+0.116` |
| `Cv Kwh` | `0.909` | `+0.115` |

---

### Meter & Feeder Analytics
- **Current Reading:** `0.200 kW` (Voltage: `230.0 V`, Current: `0.00 A`, PF: `0.950`)
- **Diurnal Baseline for Hour:** `3.561 kW`
- **Baseline Deviation:** `-94.4%` (`-5.03 \sigma`)
- **Parent Transformer Unexplained Loss (NTL):** `5.6%`


### Ground Truth Verification (Digital Twin Telemetry Reveal)
- **Active Physical Scenario:** `THEFT_BYPASS`
- **True Physical Consumption:** `3.768 kW`
- **Cyber Reported Reading:** `0.200 kW`
- **Unreported / Stolen Power:** `3.568 kW`
> **Model Accuracy Confirmation:** The detector successfully extracted this anomaly with `88.8%` confidence against physical reality.


### Supporting Evidence Chain
- Drastic consumption drop (94.4% below diurnal baseline, z=-5.03)
- Persistent low-consumption streak lasting 5 consecutive days
- Distribution transformer TX_102 operating within nominal loss limits (5.6%)
- Consumer load is 5.0% of neighborhood feeder peer average
- SHAP ML Evidence: 'Std Kwh' contributed +0.36 toward theft probability
- SHAP ML Evidence: 'Max Kwh' contributed +0.36 toward theft probability
- SHAP ML Evidence: 'Mean Kwh' contributed +0.12 toward theft probability
- SHAP ML Evidence: 'Cv Kwh' contributed +0.12 toward theft probability

### Technical Assessment
Statistical and electrical analysis confirms a non-technical loss event at meter MTR_S_018. While the consumer has a contracted load of 4.5 kW and an established historical baseline of 3.56 kW, the meter reported only 0.20 kW (a -94.4% reduction). Concurrently, the distribution transformer TX_102 is registering 5.6% unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized meter shunt, line tapping, or bypass.

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **HIGH PRIORITY: Issue physical inspection warrant. Dispatch anti-theft squad to verify meter shunt/bypass**
