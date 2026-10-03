"""
Smart Grid Digital Twin Master Orchestrator.
Synchronizes the physical AC electrical grid, cyber AMI smart meters,
real-time energy accounting, multi-signal anomaly detection, and aerial inspection routing.
"""
from __future__ import annotations
import copy
from typing import Dict, List, Any, Optional

from config import CONFIG
from models.topology import GridTopology, ConsumerNode, TransformerNode
from models.telemetry import (
    DualStateRecord,
    TelemetryReading,
    MeterStatusFlags,
    ScenarioType,
)
from models.electrical import TechnicalLossCalculator, ElectricalParameters
from simulation.city_generator import CityGISGenerator
from simulation.load_profiles import DiurnalLoadProfileGenerator
from simulation.scenario_injector import ScenarioInjector
from simulation.clock import SimulationClock
from engine.energy_accounting import EnergyAccountingEngine, TransformerLossReport
from engine.anomaly_detector import MultiSignalAnomalyDetector, AnomalyDetectionResult
from engine.explainer import AnomalyExplainer, InvestigationReport
from engine.inspection_planner import InspectionPrioritizer, InspectionTarget, DroneFlightPath


class SmartGridDigitalTwin:
    """Master cyber-physical Digital Twin for electrical distribution networks."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.city_gen = CityGISGenerator(seed=seed)
        self.profile_gen = DiurnalLoadProfileGenerator(seed=seed)
        self.loss_calc = TechnicalLossCalculator()
        self.injector = ScenarioInjector(seed=seed)
        self.clock = SimulationClock()
        self.accounting = EnergyAccountingEngine()
        self.prioritizer = InspectionPrioritizer()

        # State storage
        self.topology: Optional[GridTopology] = None
        self.detector: Optional[MultiSignalAnomalyDetector] = None

        # Cumulative meter registers (kWh): consumer_id -> float
        self.cumulative_true_kwh: Dict[str, float] = {}
        self.cumulative_reported_kwh: Dict[str, float] = {}

        # Latest tick state
        self.latest_dual_records: Dict[str, DualStateRecord] = {}
        self.latest_transformer_reports: Dict[str, TransformerLossReport] = {}
        self.latest_anomaly_results: Dict[str, AnomalyDetectionResult] = {}
        self.latest_inspection_targets: List[InspectionTarget] = []
        self.latest_drone_flight: Optional[DroneFlightPath] = None

        # Toggle for USP "Reveal Ground Truth"
        self.reveal_ground_truth: bool = True

    def initialize(self, setup_scenarios: bool = True):
        """Builds grid topology, pre-calculates diurnal baselines, and sets up initial anomalies."""
        # 1. Procedural 3D GIS Grid
        self.topology = self.city_gen.build_grid()

        # 2. Historical Baselines (14 days synthetic history)
        consumers_list = list(self.topology.consumers.values())
        self.profile_gen.build_historical_baselines(consumers_list, days=CONFIG.BASELINE_HISTORY_DAYS)

        # 3. Anomaly Detector
        self.detector = self.MultiSignalAnomalyDetectorWrapper(self.profile_gen)

        # 4. Initialize cumulative counters
        for c in consumers_list:
            self.cumulative_true_kwh[c.id] = 120.0 + (c.contracted_load_kw * 15.0)
            self.cumulative_reported_kwh[c.id] = self.cumulative_true_kwh[c.id]

        # 5. Inject representative operational scenarios if requested
        if setup_scenarios:
            self.injector.setup_default_demo_scenarios()

        # 6. Execute step to populate initial state
        self.step()

    @property
    def MultiSignalAnomalyDetectorWrapper(self):
        return MultiSignalAnomalyDetector

    def step(self) -> Dict[str, Any]:
        """
        Executes one discrete simulation step (15-min interval):
        1. Advances simulation clock.
        2. Simulates physical electricity flow (true load, voltage drops, line copper losses).
        3. Applies cyber transformations (theft shunt, meter faults, comms loss).
        4. Calculates transformer energy balance (technical vs non-technical losses).
        5. Runs multi-signal anomaly detection & root cause classification.
        6. Prioritizes field inspections and computes 3D drone trajectory.
        """
        self.clock.tick()
        curr_time = self.clock.iso_format
        hour_flt = self.clock.hour_float
        hour_int = self.clock.current_time.hour
        is_wk = self.clock.is_weekend
        interval_h = self.clock.step_minutes / 60.0

        dual_records_this_tick: Dict[str, DualStateRecord] = {}

        # 1. Calculate physical and reported state per consumer
        for c_id, consumer in self.topology.consumers.items():
            # True physical consumption
            true_kw, pf = self.profile_gen.generate_true_consumption(
                consumer=consumer,
                hour_float=hour_flt,
                is_weekend=is_wk,
            )

            # AC Electrical calculations: terminal voltage drop & line copper loss
            elec_params, line_loss_kw = self.loss_calc.compute_service_drop_parameters(
                active_power_kw=true_kw,
                power_factor=pf,
                distance_m=consumer.line_distance_m,
            )

            # Update true cumulative energy counter
            self.cumulative_true_kwh[c_id] += true_kw * interval_h

            # Ground truth reading object
            ground_truth_reading = TelemetryReading(
                timestamp=curr_time,
                consumer_id=c_id,
                meter_id=consumer.meter_id,
                voltage_v=elec_params.voltage_v,
                current_a=elec_params.current_a,
                active_power_kw=elec_params.active_power_kw,
                reactive_power_kvar=elec_params.reactive_power_kvar,
                power_factor=elec_params.power_factor,
                cumulative_energy_kwh=self.cumulative_true_kwh[c_id],
                frequency_hz=elec_params.frequency_hz,
            )

            # Pass through Scenario Injector (transforms into cyber reported reading)
            dual_rec = self.injector.apply_scenario(
                consumer=consumer,
                ground_truth=ground_truth_reading,
                line_loss_kw=line_loss_kw,
            )

            # Update reported cumulative energy counter if meter is reporting
            if dual_rec.reported is not None and not dual_rec.reported.is_missing:
                self.cumulative_reported_kwh[c_id] += dual_rec.reported.active_power_kw * interval_h
                dual_rec.reported.cumulative_energy_kwh = self.cumulative_reported_kwh[c_id]

            dual_records_this_tick[c_id] = dual_rec

        self.latest_dual_records = dual_records_this_tick

        # 2. Transformer Level Energy Accounting (Zone 1 & Zone 2)
        tx_reports: Dict[str, TransformerLossReport] = {}
        for tx_id, tx_node in self.topology.transformers.items():
            tx_consumer_records = [
                dual_records_this_tick[cid]
                for cid in tx_node.connected_consumer_ids
                if cid in dual_records_this_tick
            ]
            report = self.accounting.calculate_transformer_balance(
                transformer=tx_node,
                consumer_records=tx_consumer_records,
                timestamp=curr_time,
                interval_hours=interval_h,
            )
            tx_reports[tx_id] = report

        self.latest_transformer_reports = tx_reports

        # 3. Multi-Signal Anomaly Detection & Cause Classification
        records_list = list(dual_records_this_tick.values())
        anomaly_results = self.detector.analyze_records(
            records=records_list,
            consumers=self.topology.consumers,
            transformer_reports=tx_reports,
            hour_int=hour_int,
        )
        self.latest_anomaly_results = anomaly_results

        # 4. Field Inspection Prioritization
        inspection_targets = self.prioritizer.prioritize_consumers(
            anomaly_results=anomaly_results,
            consumers=self.topology.consumers,
        )
        self.latest_inspection_targets = inspection_targets

        # 5. Autonomous 3D Drone Flight Path (Base Hub: Transformer TX_101)
        base_hub = self.topology.transformers["TX_101"]
        self.latest_drone_flight = self.prioritizer.plan_drone_inspection_route(
            base_hub=base_hub,
            targets=inspection_targets,
            max_targets=5,
        )

        return self.get_snapshot()

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns complete synchronized digital twin state for UI/API/WebSockets."""
        time_state = self.clock.get_time_state()

        consumers_payload = {}
        for c_id, consumer in self.topology.consumers.items():
            dual_rec = self.latest_dual_records.get(c_id)
            anomaly_res = self.latest_anomaly_results.get(c_id)

            consumers_payload[c_id] = {
                "static": consumer.to_dict(),
                "telemetry": dual_rec.to_dict() if dual_rec else None,
                "analysis": anomaly_res.to_dict() if anomaly_res else None,
            }

        transformers_payload = {
            tx_id: report.to_dict()
            for tx_id, report in self.latest_transformer_reports.items()
        }

        # Aggregate network health KPIs
        total_consumers = len(self.topology.consumers)
        anomalies_count = sum(
            1 for res in self.latest_anomaly_results.values()
            if res.risk_level in ["HIGH", "CRITICAL"]
        )
        total_tx_input_kw = sum(r.transformer_input_kw for r in self.latest_transformer_reports.values())
        total_unexplained_loss_kw = sum(r.unexplained_loss_kw for r in self.latest_transformer_reports.values())
        total_tech_loss_kw = sum(r.technical_losses_kw for r in self.latest_transformer_reports.values())
        overall_ntl_pct = (total_unexplained_loss_kw / max(0.1, total_tx_input_kw)) * 100.0

        return {
            "clock": time_state,
            "grid_summary": {
                "total_consumers": total_consumers,
                "anomalous_consumers_count": anomalies_count,
                "total_grid_input_kw": round(total_tx_input_kw, 2),
                "total_technical_loss_kw": round(total_tech_loss_kw, 2),
                "total_unexplained_loss_kw": round(total_unexplained_loss_kw, 2),
                "grid_unexplained_ntl_pct": round(overall_ntl_pct, 2),
                "reveal_ground_truth": self.reveal_ground_truth,
            },
            "transformers": transformers_payload,
            "consumers": consumers_payload,
            "inspection_queue": [t.to_dict() for t in self.latest_inspection_targets],
            "drone_flight": self.latest_drone_flight.to_dict() if self.latest_drone_flight else None,
        }

    def generate_investigation_report(self, consumer_id: str) -> Optional[InvestigationReport]:
        """Generates comprehensive explainable audit report for a consumer."""
        consumer = self.topology.consumers.get(consumer_id)
        anomaly = self.latest_anomaly_results.get(consumer_id)
        dual_rec = self.latest_dual_records.get(consumer_id)

        if not consumer or not anomaly:
            return None

        # Find inspection rank
        rank = 1
        for idx, t in enumerate(self.latest_inspection_targets):
            if t.consumer_id == consumer_id:
                rank = idx + 1
                break

        return AnomalyExplainer.generate_report(
            consumer=consumer,
            anomaly=anomaly,
            dual_record=dual_rec if self.reveal_ground_truth else None,
            priority_rank=rank,
        )

    def inject_scenario(self, consumer_id: str, scenario: ScenarioType, params: Optional[Dict[str, Any]] = None):
        """Dynamically inject an anomaly scenario on a specific consumer."""
        self.injector.inject_scenario(consumer_id, scenario, params)

    def clear_scenario(self, consumer_id: str):
        """Restore consumer to normal operation."""
        self.injector.clear_scenario(consumer_id)
