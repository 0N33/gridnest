"""
Scenario & Anomaly Injection Engine for Problem Statement 2.
Implements the 5 operational scenarios:
1. Electricity theft/tampering (shunt/bypass, flat fraud, reverse power)
2. Meter malfunction (stuck, zero, erratic sensor spike, hardware error flag)
3. Communication failure (dropped packets, offline status, timeout)
4. Legitimate abnormal consumption (EV charging, heat wave, event surge)
5. Normal consumption (healthy baseline with stochastic noise)
"""
from __future__ import annotations
import copy
import random
from typing import Dict, Any, Optional, Tuple
from models.telemetry import (
    ScenarioType,
    TelemetryReading,
    MeterStatusFlags,
    DualStateRecord,
)
from models.topology import ConsumerNode


class ScenarioInjector:
    """Manages active injection profiles and transforms ground truth into cyber reported states."""

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)
        # consumer_id -> { "scenario": ScenarioType, "params": dict }
        self.active_injections: Dict[str, Dict[str, Any]] = {}
        # Track persistent state for stuck meters or cumulative counters
        self.stuck_meter_states: Dict[str, float] = {}

    def inject_scenario(
        self,
        consumer_id: str,
        scenario: ScenarioType,
        params: Optional[Dict[str, Any]] = None,
    ):
        """Activates a specific scenario on a consumer."""
        if params is None:
            params = {}
        self.active_injections[consumer_id] = {
            "scenario": scenario,
            "params": params,
        }

    def clear_scenario(self, consumer_id: str):
        """Restores consumer to NORMAL operation."""
        if consumer_id in self.active_injections:
            del self.active_injections[consumer_id]
        if consumer_id in self.stuck_meter_states:
            del self.stuck_meter_states[consumer_id]

    def get_consumer_scenario(self, consumer_id: str) -> ScenarioType:
        if consumer_id in self.active_injections:
            return self.active_injections[consumer_id]["scenario"]
        return ScenarioType.NORMAL

    def apply_scenario(
        self,
        consumer: ConsumerNode,
        ground_truth: TelemetryReading,
        line_loss_kw: float,
    ) -> DualStateRecord:
        """
        Transforms physical Ground Truth reading into the cyber Reported reading
        based on the active scenario for this consumer.
        """
        scenario = self.get_consumer_scenario(consumer.id)
        params = self.active_injections.get(consumer.id, {}).get("params", {})

        # Deep copy ground truth as baseline for reported
        reported_reading = copy.deepcopy(ground_truth)
        theft_scaling = 1.0
        unreported_kw = 0.0

        if scenario == ScenarioType.NORMAL:
            # Everything matches reality; clean flags
            reported_reading.status_flags = MeterStatusFlags()
            return DualStateRecord(
                timestamp=ground_truth.timestamp,
                consumer_id=consumer.id,
                meter_id=consumer.meter_id,
                active_scenario=scenario,
                ground_truth=ground_truth,
                reported=reported_reading,
                line_loss_kw=line_loss_kw,
                theft_scaling_factor=1.0,
                unreported_stolen_kw=0.0,
            )

        elif scenario == ScenarioType.THEFT_BYPASS:
            # Electricity theft: partial shunt or full bypass
            theft_mode = params.get("mode", "partial_shunt")
            flag_tamper = params.get("trigger_tamper_flag", False)

            if theft_mode == "partial_shunt":
                # Shunt bypass: reports only 20% to 45% of true load
                theft_scaling = params.get("scaling_factor", 0.30)
                reported_kw = max(0.05, ground_truth.active_power_kw * theft_scaling)
                unreported_kw = ground_truth.active_power_kw - reported_kw
                reported_reading.active_power_kw = round(reported_kw, 3)
                # Recalculate reported current
                reported_reading.current_a = round(
                    (reported_kw * 1000.0) / (reported_reading.voltage_v * reported_reading.power_factor), 2
                )
            elif theft_mode == "flat_baseline":
                # Consumer draws high power, but meter is pegged to flat 0.20 kW
                theft_scaling = min(1.0, 0.20 / max(0.1, ground_truth.active_power_kw))
                unreported_kw = max(0.0, ground_truth.active_power_kw - 0.20)
                reported_reading.active_power_kw = 0.20
                reported_reading.current_a = round((200.0) / (reported_reading.voltage_v * 0.95), 2)

            # In some thefts, physical tamper switch or magnet triggered
            if flag_tamper:
                reported_reading.status_flags.magnetic_tamper = True
                reported_reading.status_flags.tamper_cover_opened = True

            return DualStateRecord(
                timestamp=ground_truth.timestamp,
                consumer_id=consumer.id,
                meter_id=consumer.meter_id,
                active_scenario=scenario,
                ground_truth=ground_truth,
                reported=reported_reading,
                line_loss_kw=line_loss_kw,
                theft_scaling_factor=theft_scaling,
                unreported_stolen_kw=unreported_kw,
            )

        elif scenario == ScenarioType.METER_MALFUNCTION:
            malfunction_type = params.get("malfunction_type", "stuck")
            reported_reading.status_flags.hardware_fault = True

            if malfunction_type == "stuck":
                # Energy/power register is frozen at a static reading
                if consumer.id not in self.stuck_meter_states:
                    self.stuck_meter_states[consumer.id] = 0.420
                reported_reading.active_power_kw = self.stuck_meter_states[consumer.id]
                reported_reading.current_a = 1.95
            elif malfunction_type == "zero_reading":
                # Zero power despite nominal line voltage
                reported_reading.active_power_kw = 0.0
                reported_reading.current_a = 0.0
            elif malfunction_type == "erratic_spike":
                # Wild sensor spike e.g. 50kW on a 5kW meter
                reported_reading.active_power_kw = 48.5
                reported_reading.current_a = 210.0
                reported_reading.status_flags.voltage_out_of_range = True

            return DualStateRecord(
                timestamp=ground_truth.timestamp,
                consumer_id=consumer.id,
                meter_id=consumer.meter_id,
                active_scenario=scenario,
                ground_truth=ground_truth,
                reported=reported_reading,
                line_loss_kw=line_loss_kw,
                theft_scaling_factor=1.0,
                unreported_stolen_kw=0.0,
            )

        elif scenario == ScenarioType.COMM_FAILURE:
            # Packets are lost; headend receives missing reading
            reported_reading.is_missing = True
            reported_reading.status_flags.communication_error = True

            return DualStateRecord(
                timestamp=ground_truth.timestamp,
                consumer_id=consumer.id,
                meter_id=consumer.meter_id,
                active_scenario=scenario,
                ground_truth=ground_truth,
                reported=None, # Cyber headend receives null reading
                line_loss_kw=line_loss_kw,
                theft_scaling_factor=1.0,
                unreported_stolen_kw=0.0,
            )

        elif scenario == ScenarioType.LEGITIMATE_ABNORMAL:
            # Real physical surge (e.g. EV fast charging 7.4 kW or heavy air conditioning)
            surge_kw = params.get("surge_kw", 7.2)
            # Physical consumption actually increased!
            ground_truth.active_power_kw += surge_kw
            ground_truth.current_a = round(
                (ground_truth.active_power_kw * 1000.0) / (ground_truth.voltage_v * ground_truth.power_factor), 2
            )
            # Meter accurately reports this high load!
            reported_reading = copy.deepcopy(ground_truth)
            reported_reading.status_flags = MeterStatusFlags()

            return DualStateRecord(
                timestamp=ground_truth.timestamp,
                consumer_id=consumer.id,
                meter_id=consumer.meter_id,
                active_scenario=scenario,
                ground_truth=ground_truth,
                reported=reported_reading,
                line_loss_kw=line_loss_kw,
                theft_scaling_factor=1.0,
                unreported_stolen_kw=0.0,
            )

        # Fallback
        return DualStateRecord(
            timestamp=ground_truth.timestamp,
            consumer_id=consumer.id,
            meter_id=consumer.meter_id,
            active_scenario=ScenarioType.NORMAL,
            ground_truth=ground_truth,
            reported=reported_reading,
            line_loss_kw=line_loss_kw,
        )

    def setup_default_demo_scenarios(self):
        """
        Pre-configures representative anomalies across both zones for instant live demonstration:
        - Zone 1 (North):
          * CONS_N_004: Theft (Bypass shunt, 30% reported, covert without flag)
          * CONS_N_009: Theft (Aggressive shunt + magnetic tamper flag tripped)
          * CONS_N_015: Meter Malfunction (Stuck register at 0.35 kW)
          * CONS_N_021: Communication Failure (Intermittent offline packet loss)
        - Zone 2 (South):
          * CONS_S_003: Legitimate Abnormal (EV Fast Charger 7.4 kW active)
          * CONS_S_011: Meter Malfunction (Zero reading fault with hardware flag)
          * CONS_S_018: Theft (Commercial bakery bypass during peak evening hours)
          * CONS_S_022: Legitimate Heatwave Surge (Commercial AC cluster)
        """
        self.inject_scenario(
            "CONS_N_004",
            ScenarioType.THEFT_BYPASS,
            {"mode": "partial_shunt", "scaling_factor": 0.28, "trigger_tamper_flag": False},
        )
        self.inject_scenario(
            "CONS_N_009",
            ScenarioType.THEFT_BYPASS,
            {"mode": "partial_shunt", "scaling_factor": 0.35, "trigger_tamper_flag": True},
        )
        self.inject_scenario(
            "CONS_N_015",
            ScenarioType.METER_MALFUNCTION,
            {"malfunction_type": "stuck"},
        )
        self.inject_scenario(
            "CONS_N_021",
            ScenarioType.COMM_FAILURE,
            {},
        )
        self.inject_scenario(
            "CONS_S_003",
            ScenarioType.LEGITIMATE_ABNORMAL,
            {"surge_kw": 7.4},
        )
        self.inject_scenario(
            "CONS_S_011",
            ScenarioType.METER_MALFUNCTION,
            {"malfunction_type": "zero_reading"},
        )
        self.inject_scenario(
            "CONS_S_018",
            ScenarioType.THEFT_BYPASS,
            {"mode": "flat_baseline", "trigger_tamper_flag": False},
        )
