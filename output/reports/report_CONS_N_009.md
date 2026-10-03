# Smart Grid Anomaly Investigation Report: CONS_N_009
**Report ID:** `RPT-Zone-009-AB4E81` | **Generated At:** `2026-10-05T07:15:00` | **Priority Rank:** `#1`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `CONS_N_009` / `MTR_N_009` |
| **Consumer Name** | Residential Consumer #9 (Zone_1_North) |
| **Category & Contracted Load** | Residential (4.5 kW) |
| **Zone & Feeder** | Zone_1_North (TX_101 / FDR_NORTH_11KV) |
| **Anomaly Score** | **`98.5 / 100`** (CRITICAL) |
| **Probable Cause** | **`THEFT_TAMPERING`** |
| **Confidence** | **`94.2%`** |

---

### Meter & Feeder Analytics
- **Current Reading:** `1.254 kW` (Voltage: `230.0 V`, Current: `0.00 A`, PF: `0.950`)
- **Diurnal Baseline for Hour:** `3.557 kW`
- **Baseline Deviation:** `-64.7%` (`-3.88 \sigma`)
- **Parent Transformer Unexplained Loss (NTL):** `11.6%`


### Ground Truth Verification (Digital Twin Telemetry Reveal)
- **Active Physical Scenario:** `THEFT_BYPASS`
- **True Physical Consumption:** `3.584 kW`
- **Cyber Reported Reading:** `1.254 kW`
- **Unreported / Stolen Power:** `2.330 kW`
> **Model Accuracy Confirmation:** The detector successfully extracted this anomaly with `94.2%` confidence against physical reality.


### Supporting Evidence Chain
- Magnetic tamper sensor tripped (strong external neodymium magnet field detected)
- Meter terminal enclosure microswitch open event recorded
- Drastic consumption drop (-64.7% below diurnal baseline, z=-3.88)
- Corroborating transformer TX_101 exhibits 11.6% unexplained non-technical losses
- Consumer consumption is 27.9% of peer average on the same distribution line

### Technical Assessment
Statistical and electrical analysis confirms a non-technical loss event at meter MTR_N_009. While the consumer has a contracted load of 4.5 kW and an established historical baseline of 3.56 kW, the meter reported only 1.25 kW (a -64.7% reduction). Concurrently, the distribution transformer TX_101 is registering 11.6% unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized meter shunt, line tapping, or bypass.

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **HIGH PRIORITY: Issue physical inspection warrant. Dispatch anti-theft squad to verify meter shunt/bypass**
