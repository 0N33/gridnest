# Smart Grid Anomaly Investigation Report: CONS_N_004
**Report ID:** `RPT-Zone-004-7C0F60` | **Generated At:** `2026-10-05T07:15:00` | **Priority Rank:** `#1`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `CONS_N_004` / `MTR_N_004` |
| **Consumer Name** | LightIndustrial #4 (Z1_North) |
| **Category & Contracted Load** | LightIndustrial (25.0 kW) |
| **Zone & Feeder** | Zone_1_North (TX_101 / FDR_NORTH_11KV) |
| **Final Anomaly Score** | **`97.8 / 100`** (CRITICAL) |
| **Probable Cause** | **`THEFT_TAMPERING`** |
| **Diagnostic Confidence** | **`98.0%`** |

---


### Historical Benchmark vs. Real-Time Telemetry Audit
| Audit Metric | Ground-Truth Historical Record | Real-Time Telemetry (15-min streaming) |
|---|---|---|
| **Dataset Source / Benchmark** | State Grid Corp China (`data.csv`) | Digital Twin IoT Streaming Telemetry |
| **Kaggle Consumer Hash** | `E89F2AD4B103F2E2045EE0F4E60429BC` | `MTR_N_004` |
| **Benchmark Ground Truth** | `THEFT / NON-TECHNICAL LOSS (FLAG=1)` | Diagnostic Classification: `THEFT_TAMPERING` |
| **Daily Energy Baseline** | `16.84 kWh/day` | Real-time Extrapolated: `4.23 kWh/day` |
| **Energy Divergence (\Delta)** | Historical Reference | **`-74.9%`** (`+12.61 kWh/day`) |
| **Cumulative Theft / Divergence (30-day)** | Historical Baseline Trajectory | **`394.5 kWh`** |
| **Estimated Utility Revenue Loss** | - | **`₹2,958.82`** (@ ₹7.50/kWh) |
| **Temporal Onset Point** | Historical Shift Changepoint | `Day 3` |

---

### AI/ML Hybrid Ensemble Attribution
| Component Model | Architecture | Raw Prediction | Ensemble Weight |
|---|---|---|---|
| **XGBoost Classifier** | Supervised Gradient Boosted Trees | `P(Theft) = 0.367` | 45% |
| **LightGBM Classifier** | Supervised Leaf-Wise Trees | `P(Theft) = 0.265` | 45% |
| **Isolation Forest** | Unsupervised Isolation Trees | `Anomaly = 0.219` | 10% |
| **Hybrid Stacking Blend** | Multi-Model Meta-Learner | **Score: `97.8 / 100`** | **100%** |

#### Top SHAP Feature Impacts (XGBoost TreeExplainer)
| Feature Name | Observed Value | SHAP Impact (\Delta log-odds) |
|---|---|---|
| `Max Kwh` | `45.26` | `+0.294` |
| `Autocorr Lag7` | `0.231` | `+0.246` |
| `Std Kwh` | `9.507` | `+0.233` |
| `Low Streak Recent` | `5.0` | `+0.099` |

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
- Persistent low-consumption streak lasting 5 consecutive days
- Corroborating transformer TX_101 exhibits 15.6% unexplained non-technical loss (NTL)
- Consumer load is 19.8% of neighborhood feeder peer average
- SHAP ML Evidence: 'Max Kwh' contributed +0.29 toward theft probability
- SHAP ML Evidence: 'Autocorr Lag7' contributed +0.25 toward theft probability
- SHAP ML Evidence: 'Std Kwh' contributed +0.23 toward theft probability
- SHAP ML Evidence: 'Low Streak Recent' contributed +0.10 toward theft probability

### Technical Assessment
Statistical and electrical analysis confirms a non-technical loss event at meter MTR_N_004. While the consumer has a contracted load of 25.0 kW and an established historical baseline of 3.53 kW, the meter reported only 0.89 kW (a -74.9% reduction). Concurrently, the distribution transformer TX_101 is registering 15.6% unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized meter shunt, line tapping, or bypass.

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **HIGH PRIORITY: Issue physical inspection warrant. Dispatch anti-theft squad to verify meter shunt/bypass**
