"""
Telemetry, Meter Status Registers, and Dual-State Digital Twin Data Models.
Represents physical ground truth vs cyber reported data.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional


class ScenarioType(str, Enum):
    NORMAL = "NORMAL"
    THEFT_BYPASS = "THEFT_BYPASS"
    METER_MALFUNCTION = "METER_MALFUNCTION"
    COMM_FAILURE = "COMM_FAILURE"
    LEGITIMATE_ABNORMAL = "LEGITIMATE_ABNORMAL"


@dataclass
class MeterStatusFlags:
    """Smart meter internal status registers / diagnostic flags."""
    tamper_cover_opened: bool = False
    magnetic_tamper: bool = False
    reverse_current: bool = False
    neutral_missing: bool = False
    low_battery: bool = False
    hardware_fault: bool = False
    communication_error: bool = False
    voltage_out_of_range: bool = False

    @property
    def has_tamper(self) -> bool:
        return self.tamper_cover_opened or self.magnetic_tamper or self.reverse_current or self.neutral_missing

    @property
    def has_fault(self) -> bool:
        return self.hardware_fault or self.low_battery

    def to_bitmask(self) -> int:
        mask = 0
        if self.tamper_cover_opened: mask |= 1 << 0
        if self.magnetic_tamper: mask |= 1 << 1
        if self.reverse_current: mask |= 1 << 2
        if self.neutral_missing: mask |= 1 << 3
        if self.low_battery: mask |= 1 << 4
        if self.hardware_fault: mask |= 1 << 5
        if self.communication_error: mask |= 1 << 6
        if self.voltage_out_of_range: mask |= 1 << 7
        return mask

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tamper_cover_opened": self.tamper_cover_opened,
            "magnetic_tamper": self.magnetic_tamper,
            "reverse_current": self.reverse_current,
            "neutral_missing": self.neutral_missing,
            "low_battery": self.low_battery,
            "hardware_fault": self.hardware_fault,
            "communication_error": self.communication_error,
            "voltage_out_of_range": self.voltage_out_of_range,
            "bitmask": self.to_bitmask(),
            "has_tamper": self.tamper_cover_opened or self.magnetic_tamper or self.reverse_current,
            "has_fault": self.hardware_fault or self.low_battery,
        }


@dataclass
class TelemetryReading:
    """Snapshot of a single meter reading at a specific timestamp."""
    timestamp: str
    consumer_id: str
    meter_id: str
    voltage_v: float
    current_a: float
    active_power_kw: float
    reactive_power_kvar: float
    power_factor: float
    cumulative_energy_kwh: float
    status_flags: MeterStatusFlags = field(default_factory=MeterStatusFlags)
    frequency_hz: float = 50.0
    ambient_temp_c: float = 28.0
    is_missing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "consumer_id": self.consumer_id,
            "meter_id": self.meter_id,
            "voltage_v": round(self.voltage_v, 2),
            "current_a": round(self.current_a, 2),
            "active_power_kw": round(self.active_power_kw, 3),
            "reactive_power_kvar": round(self.reactive_power_kvar, 3),
            "power_factor": round(self.power_factor, 3),
            "cumulative_energy_kwh": round(self.cumulative_energy_kwh, 4),
            "status_flags": self.status_flags.to_dict(),
            "frequency_hz": round(self.frequency_hz, 2),
            "ambient_temp_c": round(self.ambient_temp_c, 1),
            "is_missing": self.is_missing,
        }


@dataclass
class DualStateRecord:
    """
    Core USP of the Digital Twin:
    Maintains synchronized Ground Truth (Physical Reality) vs Reported (Cyber Reality).
    Allows 'God's Eye' reveal of true non-technical losses.
    """
    timestamp: str
    consumer_id: str
    meter_id: str
    active_scenario: ScenarioType
    ground_truth: TelemetryReading
    reported: Optional[TelemetryReading]
    line_loss_kw: float = 0.0
    theft_scaling_factor: float = 1.0 # e.g. 0.3 means meter reports 30% of actual power
    unreported_stolen_kw: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        gt_dict = self.ground_truth.to_dict()
        rep_dict = self.reported.to_dict() if self.reported and not self.reported.is_missing else None
        return {
            "timestamp": self.timestamp,
            "consumer_id": self.consumer_id,
            "meter_id": self.meter_id,
            "active_scenario": self.active_scenario.value,
            "ground_truth": gt_dict,
            "reported": rep_dict,
            "line_loss_kw": round(self.line_loss_kw, 4),
            "theft_scaling_factor": self.theft_scaling_factor,
            "unreported_stolen_kw": round(self.unreported_stolen_kw, 3),
            "is_tampered": self.active_scenario == ScenarioType.THEFT_BYPASS,
            "is_offline": self.reported is None or self.reported.is_missing,
        }
