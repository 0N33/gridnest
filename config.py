"""
Configuration parameters for the Smart Grid Digital Twin.
Defines electrical specifications, GIS boundaries, simulation clock settings,
and anomaly detection thresholds.
"""
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class GridConfig:
    # City layout & GIS
    BASE_LATITUDE: float = 28.613939       # Example urban center (New Delhi / reference city)
    BASE_LONGITUDE: float = 77.209021
    ZONE_RADIUS_METERS: float = 350.0      # Spatial extent of each transformer zone
    NUM_TRANSFORMERS: int = 2              # Zone 1 (TX-101 North) & Zone 2 (TX-102 South)
    HOUSES_PER_TRANSFORMER: int = 24       # Total 48 houses across 2 zones
    
    # Electrical nominal specifications
    NOMINAL_VOLTAGE_V: float = 230.0       # Single phase 230V AC
    VOLTAGE_TOLERANCE_PCT: float = 5.0     # +/- 5% (218.5V - 241.5V)
    GRID_FREQUENCY_HZ: float = 50.0
    LINE_RESISTANCE_OHM_PER_KM: float = 0.64   # Standard LV copper distribution cable (16mm^2)
    LINE_REACTANCE_OHM_PER_KM: float = 0.08
    TRANSFORMER_CAPACITY_KVA: float = 100.0
    TRANSFORMER_NO_LOAD_LOSS_KW: float = 0.35  # Core loss
    TRANSFORMER_FULL_LOAD_LOSS_KW: float = 1.6 # Copper loss at rated load
    
    # Simulation Clock & Telemetry
    SIM_TICK_SECONDS: float = 1.0          # Wall-clock interval per tick
    TIME_ACCELERATION_FACTOR: int = 900    # 1 real sec = 15 simulated minutes (900s)
    REPORTING_INTERVAL_MINS: int = 15      # Smart meter telemetry interval
    
    # Baseline historical profiling
    BASELINE_HISTORY_DAYS: int = 14        # Historical window for baseline building
    
    # Anomaly Detection thresholds
    THEFT_DEVIATION_THRESHOLD_Z: float = -2.2
    TRANSFORMER_UNEXPLAINED_LOSS_ALERT_PCT: float = 8.0 # Alert when NTL > 8% of feeder intake
    HIGH_RISK_ANOMALY_SCORE: float = 70.0
    CRITICAL_RISK_ANOMALY_SCORE: float = 85.0


CONFIG = GridConfig()
