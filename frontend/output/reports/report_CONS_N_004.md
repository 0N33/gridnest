# Smart Grid Anomaly Investigation Report: CONS_N_004
**Report ID:** `RPT-Zone-004-FF31CF` | **Generated At:** `2026-10-05T07:15:00` | **Priority Rank:** `#1`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `CONS_N_004` / `MTR_N_004` |
| **Consumer Name** | LightIndustrial #4 (Z1_North) |
| **Category & Contracted Load** | LightIndustrial (25.0 kW) |
| **Zone & Feeder** | Zone_1_North (TX_101 / FDR_NORTH_11KV) |
| **Final Anomaly Score** | **`98.5 / 100`** (CRITICAL) |
| **Probable Cause** | **`THEFT_TAMPERING`** |
| **Diagnostic Confidence** | **`98.0%`** |

---

### AI/ML Hybrid Ensemble Attribution
| Component Model | Architecture | Raw Prediction | Ensemble Weight |
|---|---|---|---|
| **XGBoost Classifier** | Supervised Gradient Boosted Trees | `P(Theft) = 0.842` | 45% |
| **LightGBM Classifier** | Supervised Leaf-Wise Trees | `P(Theft) = 0.871` | 45% |
| **Isolation Forest** | Unsupervised Isolation Trees | `Anomaly = 0.731` | 10% |
| **Hybrid Stacking Blend** | Multi-Model Meta-Learner | **Score: `98.5 / 100`** | **100%** |

#### Top SHAP Feature Impacts (XGBoost TreeExplainer)
| Feature Name | Observed Value | SHAP Impact (\Delta log-odds) |
|---|---|---|
| `Max Kwh` | `239.408` | `+1.135` |
| `Mean Kwh` | `155.988` | `+0.654` |
| `Std Kwh` | `72.099` | `+0.580` |
| `Zero Rate` | `0.0` | `+0.374` |

---

### Meter & Feeder Analytics
- **Current Reading:** `0.888 kW` (Voltage: `230.0 V`, Current: `0.00 A`, PF: `0.950`)
- **Diurnal Baseline for Hour:** `3.533 kW`
- **Baseline Deviation:** `-74.9%` (`-3.83 \sigma`)
- **Parent Transformer Unexplained Loss (NTL):** `15.6%`


### Ground Truth Verification (Digital Twin Telemetry Reveal)
- **Active Physical Scenario:** `THEFT_BYPASS`
- **True Physical Consumption:** `3.172 kW`
- **Cyber Reported Reading:** `0.888 kW`
- **Unreported / Stolen Power:** `2.284 kW`
> **Model Accuracy Confirmation:** The detector successfully extracted this anomaly with `98.0%` confidence against physical reality.


### Supporting Evidence Chain
- Drastic consumption drop (74.9% below diurnal baseline, z=-3.83)
- Persistent low-consumption streak lasting 14 consecutive days
- Corroborating transformer TX_101 exhibits 15.6% unexplained non-technical loss (NTL)
- Consumer load is 19.8% of neighborhood feeder peer average
- SHAP ML Evidence: 'Max Kwh' contributed +1.14 toward theft probability
- SHAP ML Evidence: 'Mean Kwh' contributed +0.65 toward theft probability
- SHAP ML Evidence: 'Std Kwh' contributed +0.58 toward theft probability
- SHAP ML Evidence: 'Zero Rate' contributed +0.37 toward theft probability

### Technical Assessment
Statistical and electrical analysis confirms a non-technical loss event at meter MTR_N_004. While the consumer has a contracted load of 25.0 kW and an established historical baseline of 3.53 kW, the meter reported only 0.89 kW (a -74.9% reduction). Concurrently, the distribution transformer TX_101 is registering 15.6% unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized meter shunt, line tapping, or bypass.

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **HIGH PRIORITY: Issue physical inspection warrant. Dispatch anti-theft squad to verify meter shunt/bypass**
