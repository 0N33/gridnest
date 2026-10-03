"""
Diurnal Load Profiles and Stochastic Appliance Consumption Engine.
Generates realistic human behavioral energy usage curves for residential, commercial,
and light industrial consumers across 24 hours, weekdays, weekends, and seasonal temperatures.
"""
from __future__ import annotations
import math
import random
from typing import Dict, Tuple, List, Optional
import numpy as np
from models.topology import ConsumerNode


class DiurnalLoadProfileGenerator:
    """Generates synthetic high-fidelity load profiles and maintains historical baselines."""

    def __init__(self, seed: int = 101):
        self.random = random.Random(seed)
        self.np_random = np.random.default_rng(seed)
        self.baselines: Dict[str, Dict[int, Tuple[float, float]]] = {} # consumer_id -> {hour: (mean, std)}

    def _get_residential_normalized_curve(self, hour_float: float, is_weekend: bool = False) -> float:
        """
        Returns normalized 0.0 - 1.0 load factor for residential consumers.
        Peaks: Morning (7-9 AM), Evening (6-10 PM).
        """
        # Base standby overnight
        base = 0.12

        # Morning peak centered around 7:30 AM (or 9:00 AM on weekends)
        m_center = 9.0 if is_weekend else 7.5
        m_width = 1.6
        m_peak = 0.65 * math.exp(-0.5 * ((hour_float - m_center) / m_width) ** 2)

        # Daytime valley
        day_factor = 0.22 if not is_weekend else 0.40
        daytime = day_factor * math.exp(-0.5 * ((hour_float - 13.5) / 3.0) ** 2)

        # Evening peak centered around 20:00 (8:00 PM)
        e_center = 20.2
        e_width = 2.2
        e_peak = 0.88 * math.exp(-0.5 * ((hour_float - e_center) / e_width) ** 2)

        total = base + m_peak + daytime + e_peak
        return min(1.0, max(0.08, total))

    def _get_commercial_normalized_curve(self, hour_float: float, is_weekend: bool = False) -> float:
        """Commercial profile: business hours 09:00 to 20:00."""
        if is_weekend:
            # Weekend retail/cafes have sustained daytime
            if 10.0 <= hour_float <= 21.0:
                return 0.75 + 0.15 * math.sin((hour_float - 10.0) / 11.0 * math.pi)
            return 0.18

        # Weekday office/shop
        if 8.5 <= hour_float <= 19.5:
            return 0.80 + 0.12 * math.sin((hour_float - 8.5) / 11.0 * math.pi)
        elif 7.0 <= hour_float < 8.5 or 19.5 < hour_float <= 21.0:
            return 0.40
        return 0.15

    def _get_industrial_normalized_curve(self, hour_float: float, is_weekend: bool = False) -> float:
        """Small workshop: single shift 08:00 - 17:00."""
        if is_weekend:
            return 0.10 # minimal machinery standby
        if 8.0 <= hour_float <= 17.5:
            return 0.85
        return 0.15

    def compute_ambient_temperature(self, hour_float: float, day_of_year: int = 150) -> float:
        """Realistic daily temperature cycle: min at 05:00, max at 15:00."""
        # Mean summer temp 32C, amplitude 7C
        t_mean = 32.0
        t_amp = 6.5
        # Peak at 15:00 (3 PM)
        temp = t_mean + t_amp * math.cos(math.radians((hour_float - 15.0) * 15.0))
        return round(temp, 1)

    def generate_true_consumption(
        self,
        consumer: ConsumerNode,
        hour_float: float,
        is_weekend: bool = False,
        ambient_temp_c: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Generates ground truth physical power draw (kW) and power factor.
        Includes stochastic appliance pulses (compressors, motors) and thermal load.
        """
        if ambient_temp_c is None:
            ambient_temp_c = self.compute_ambient_temperature(hour_float)

        cat = consumer.category
        if cat == "Residential":
            norm = self._get_residential_normalized_curve(hour_float, is_weekend)
            # AC / cooling sensitivity: above 28C, load increases
            cooling_delta = max(0.0, (ambient_temp_c - 28.0) * 0.04)
            power_factor = self.random.uniform(0.92, 0.97)
        elif cat == "Commercial":
            norm = self._get_commercial_normalized_curve(hour_float, is_weekend)
            cooling_delta = max(0.0, (ambient_temp_c - 26.0) * 0.05)
            power_factor = self.random.uniform(0.88, 0.94)
        else: # LightIndustrial
            norm = self._get_industrial_normalized_curve(hour_float, is_weekend)
            cooling_delta = 0.0
            power_factor = self.random.uniform(0.82, 0.88) # Inductive motors

        scaled_factor = min(1.0, norm + cooling_delta)
        base_kw = consumer.contracted_load_kw * scaled_factor

        # Stochastic noise (+/- 8%)
        noise = self.random.gauss(0.0, 0.08 * base_kw)

        # Stochastic appliance pulse (e.g. 15% probability of a 0.8kW compressor/heater kick)
        appliance_pulse = 0.8 if self.random.random() < 0.15 else 0.0

        true_kw = max(0.08, base_kw + noise + appliance_pulse)
        return round(true_kw, 3), round(power_factor, 3)

    def build_historical_baselines(
        self,
        consumers: List[ConsumerNode],
        days: int = 14,
    ) -> Dict[str, Dict[int, Tuple[float, float]]]:
        """
        Precomputes historical diurnal hourly baselines (mean kW, std kW) for each consumer.
        Used by the anomaly detection engine to identify deviations.
        """
        self.baselines.clear()
        for c in consumers:
            hourly_samples: Dict[int, List[float]] = {h: [] for h in range(24)}
            for day in range(days):
                is_wk = (day % 7) in [5, 6]
                for hour in range(24):
                    # Sample multiple 15-min intervals within the hour
                    for m in [0, 15, 30, 45]:
                        h_flt = hour + m / 60.0
                        kw, _ = self.generate_true_consumption(c, h_flt, is_weekend=is_wk)
                        hourly_samples[hour].append(kw)

            self.baselines[c.id] = {}
            for h in range(24):
                arr = np.array(hourly_samples[h])
                self.baselines[c.id][h] = (float(arr.mean()), float(max(0.1, arr.std())))

        return self.baselines

    def get_baseline_for_hour(self, consumer_id: str, hour: int) -> Tuple[float, float]:
        """Returns (mean_kw, std_kw) for given consumer and hour."""
        if consumer_id in self.baselines and hour in self.baselines[consumer_id]:
            return self.baselines[consumer_id][hour]
        return (1.5, 0.4) # default fallback
