"""
Configuration parameters for the Smart Grid Digital Twin.
Defines electrical specifications, GIS boundaries, simulation clock settings,
and 3-zone architecture (Zone 0: Power Station, Zone 1: City North, Zone 2: City South).
"""
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class GridConfig:
    # 3-Zone Architecture
    ZONE_POWER_STATION: str = "Zone_0_PowerStation"
    ZONE_CITY_NORTH: str = "Zone_1_North"
    ZONE_CITY_SOUTH: str = "Zone_2_South"

    # City layout & GIS
    BASE_LATITUDE: float = 28.613939       # Urban center reference coordinates
    BASE_LONGITUDE: float = 77.209021
    ZONE_RADIUS_METERS: float = 400.0
    NUM_TRANSFORMERS: int = 2              # TX-101 in Zone 1 (North), TX-102 in Zone 2 (South)
    HOUSES_PER_TRANSFORMER: int = 24       # Total 48 houses across the 2 city zones
    
    # Power Station & Substation specs
    POWER_STATION_NAME: str = "Central Generation & 33kV Primary Switching Station"
    POWER_STATION_CAPACITY_MVA: float = 5.0
    TRANSMISSION_VOLTAGE_KV: float = 33.0
    PRIMARY_FEEDER_VOLTAGE_KV: float = 11.0

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
    
    # Energy Reconciliation & Anomaly Detection thresholds
    ALLOWED_TECHNICAL_LOSS_PCT: float = 4.5 # Max expected physical line & transformer I^2*R losses
    THEFT_DEVIATION_THRESHOLD_Z: float = -2.2
    TRANSFORMER_UNEXPLAINED_LOSS_ALERT_PCT: float = 6.0 # Alert when NTL > 6% of zone intake ("Done for!")
    HIGH_RISK_ANOMALY_SCORE: float = 70.0
    CRITICAL_RISK_ANOMALY_SCORE: float = 85.0

    # Telegram Bot Alert Configuration
    TELEGRAM_BOT_TOKEN: str = "8322452678:AAGbkk48lL0RSdjmj1xNUW65kXfo8JcN9_Y"
    TELEGRAM_CHAT_ID: str = "1085775169"
    TELEGRAM_ALERT_THRESHOLD: float = 75.0


CONFIG = GridConfig()
