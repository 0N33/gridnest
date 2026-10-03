"""
AC Electrical Network Engine and Technical Loss Calculator.
Calculates realistic single-phase AC voltages, currents, power factors, line impedances,
and copper/core losses based on Ohm's and Kirchhoff's laws.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Any, Tuple
from config import CONFIG


@dataclass
class ElectricalParameters:
    voltage_v: float
    current_a: float
    active_power_kw: float
    reactive_power_kvar: float
    apparent_power_kva: float
    power_factor: float
    frequency_hz: float = 50.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "voltage_v": round(self.voltage_v, 2),
            "current_a": round(self.current_a, 2),
            "active_power_kw": round(self.active_power_kw, 3),
            "reactive_power_kvar": round(self.reactive_power_kvar, 3),
            "apparent_power_kva": round(self.apparent_power_kva, 3),
            "power_factor": round(self.power_factor, 3),
            "frequency_hz": round(self.frequency_hz, 2),
        }


class TechnicalLossCalculator:
    """Calculates physical I^2*R line losses and transformer core/copper losses."""

    def __init__(
        self,
        r_ohm_per_km: float = CONFIG.LINE_RESISTANCE_OHM_PER_KM,
        x_ohm_per_km: float = CONFIG.LINE_REACTANCE_OHM_PER_KM,
        v_nom: float = CONFIG.NOMINAL_VOLTAGE_V,
    ):
        self.r_ohm_per_m = r_ohm_per_km / 1000.0
        self.x_ohm_per_m = x_ohm_per_km / 1000.0
        self.v_nom = v_nom

    def compute_service_drop_parameters(
        self,
        active_power_kw: float,
        power_factor: float,
        distance_m: float,
        transformer_voltage_v: float = 232.0,
    ) -> Tuple[ElectricalParameters, float]:
        """
        Computes consumer terminal voltage, current, and line technical loss (kW).
        Accounts for voltage drop along the service line from transformer/pole.
        """
        pf = max(0.60, min(0.999, power_factor))
        sin_phi = math.sqrt(max(0.0, 1.0 - pf**2))

        # Iterative voltage drop solution for AC single phase
        v_terminal = transformer_voltage_v
        p_w = active_power_kw * 1000.0

        if p_w <= 1e-3:
            current_a = 0.0
            line_loss_kw = 0.0
            q_kvar = 0.0
            s_kva = 0.0
            return (
                ElectricalParameters(
                    voltage_v=v_terminal,
                    current_a=current_a,
                    active_power_kw=active_power_kw,
                    reactive_power_kvar=q_kvar,
                    apparent_power_kva=s_kva,
                    power_factor=pf,
                ),
                line_loss_kw,
            )

        # 2-step relaxation for terminal voltage
        r_line = self.r_ohm_per_m * distance_m
        x_line = self.x_ohm_per_m * distance_m

        current_a = p_w / (v_terminal * pf)
        # Approximate voltage drop formula: Delta V = I * (R * cos(phi) + X * sin(phi))
        v_drop = current_a * (r_line * pf + x_line * sin_phi)
        v_terminal = max(180.0, transformer_voltage_v - v_drop)
        # Recompute accurate current at terminal voltage
        current_a = p_w / (v_terminal * pf)

        # Line copper loss: I^2 * R (in Watts -> kW)
        line_loss_kw = (current_a**2 * r_line) / 1000.0

        # Reactive and apparent power
        q_kvar = active_power_kw * (sin_phi / pf)
        s_kva = math.sqrt(active_power_kw**2 + q_kvar**2)

        return (
            ElectricalParameters(
                voltage_v=v_terminal,
                current_a=current_a,
                active_power_kw=active_power_kw,
                reactive_power_kvar=q_kvar,
                apparent_power_kva=s_kva,
                power_factor=pf,
            ),
            line_loss_kw,
        )

    def compute_transformer_technical_loss(
        self,
        total_active_load_kw: float,
        total_reactive_load_kvar: float,
        transformer_capacity_kva: float = CONFIG.TRANSFORMER_CAPACITY_KVA,
        no_load_loss_kw: float = CONFIG.TRANSFORMER_NO_LOAD_LOSS_KW,
        full_load_loss_kw: float = CONFIG.TRANSFORMER_FULL_LOAD_LOSS_KW,
    ) -> float:
        """
        Total transformer loss = Core (no load) loss + Load dependent copper loss.
        P_cu = P_rated_loss * (S_load / S_rated)^2
        """
        s_load_kva = math.sqrt(total_active_load_kw**2 + total_reactive_load_kvar**2)
        loading_ratio = min(1.5, s_load_kva / max(1.0, transformer_capacity_kva))
        copper_loss_kw = full_load_loss_kw * (loading_ratio**2)
        return no_load_loss_kw + copper_loss_kw
