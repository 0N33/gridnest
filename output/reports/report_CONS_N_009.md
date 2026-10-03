# Smart Grid Anomaly Investigation Report: CONS_N_009
**Report ID:** `RPT-Zone-009-AE75B7` | **Generated At:** `2026-10-05T07:15:00` | **Priority Rank:** `#1`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `CONS_N_009` / `MTR_N_009` |
| **Consumer Name** | Residential #9 (Z1_North) |
| **Category & Contracted Load** | Residential (3.0 kW) |
| **Zone & Feeder** | Zone_1_North (TX_101 / FDR_NORTH_11KV) |
| **Anomaly Score** | **`98.5 / 100`** (CRITICAL) |
| **Probable Cause** | **`THEFT_TAMPERING`** |
| **Confidence** | **`94.2%`** |

---

### Meter & Feeder Analytics
- **Current Reading:** `0.836 kW` (Voltage: `230.0 V`, Current: `0.00 A`, PF: `0.950`)
- **Diurnal Baseline for Hour:** `2.395 kW`
- **Baseline Deviation:** `-65.1%` (`-3.84 \sigma`)
- **Parent Transformer Unexplained Loss (NTL):** `15.6%`


### Ground Truth Verification (Digital Twin Telemetry Reveal)
- **Active Physical Scenario:** `THEFT_BYPASS`
- **True Physical Consumption:** `2.389 kW`
- **Cyber Reported Reading:** `0.836 kW`
- **Unreported / Stolen Power:** `1.553 kW`
> **Model Accuracy Confirmation:** The detector successfully extracted this anomaly with `94.2%` confidence against physical reality.


### Supporting Evidence Chain
- Magnetic tamper sensor tripped (strong external neodymium magnet field detected)
- Meter terminal enclosure microswitch open event recorded
- Drastic consumption drop (-65.1% below diurnal baseline, z=-3.84)
- Corroborating transformer TX_101 exhibits 15.6% unexplained non-technical losses
- Consumer consumption is 18.6% of peer average on the same distribution line

### Technical Assessment
Statistical and electrical analysis confirms a non-technical loss event at meter MTR_N_009. While the consumer has a contracted load of 3.0 kW and an established historical baseline of 2.39 kW, the meter reported only 0.84 kW (a -65.1% reduction). Concurrently, the distribution transformer TX_101 is registering 15.6% unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized meter shunt, line tapping, or bypass.

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **HIGH PRIORITY: Issue physical inspection warrant. Dispatch anti-theft squad to verify meter shunt/bypass**
