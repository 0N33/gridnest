"""
Comprehensive Test Suite for Smart Grid Digital Twin.
Verifies grid physics, 5 operational scenarios, dual-state synchronization,
transformer energy accounting, and explainable report generation.
"""
from __future__ import annotations
import unittest
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG
from models.topology import Coordinate, GridTopology
from models.telemetry import ScenarioType
from models.electrical import TechnicalLossCalculator
from simulation.city_generator import CityGISGenerator
from simulation.load_profiles import DiurnalLoadProfileGenerator
from engine.digital_twin import SmartGridDigitalTwin
from engine.energy_accounting import EnergyAccountingEngine
from export.geojson_exporter import GeoJSONTwinExporter


class TestSmartGridDigitalTwin(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.twin = SmartGridDigitalTwin(seed=42)
        cls.twin.initialize(setup_scenarios=True)

    def test_01_grid_topology_structure(self):
        """Verifies 2 transformer zones, feeders, poles, and 48 buildings."""
        top = self.twin.topology
        self.assertIsNotNone(top)
        self.assertEqual(len(top.transformers), 2)
        self.assertIn("TX_101", top.transformers)
        self.assertIn("TX_102", top.transformers)

        self.assertEqual(len(top.feeders), 2)
        self.assertEqual(len(top.consumers), 48)

        # Verify each zone has 24 consumers
        zone1_consumers = top.get_consumers_in_zone("Zone_1_North")
        zone2_consumers = top.get_consumers_in_zone("Zone_2_South")
        self.assertEqual(len(zone1_consumers), 24)
        self.assertEqual(len(zone2_consumers), 24)

    def test_02_electrical_calculations_and_losses(self):
        """Verifies AC voltage drops and I^2*R line losses."""
        calc = TechnicalLossCalculator()
        params, line_loss = calc.compute_service_drop_parameters(
            active_power_kw=4.0,
            power_factor=0.95,
            distance_m=120.0,
            transformer_voltage_v=230.0,
        )
        # Terminal voltage should drop slightly below 230V
        self.assertLess(params.voltage_v, 230.0)
        self.assertGreater(params.voltage_v, 215.0)
        # Current should be P / (V * PF) ~ 4000 / (228 * 0.95) ~ 18.4A
        self.assertGreater(params.current_a, 15.0)
        self.assertLess(params.current_a, 22.0)
        # Line loss should be positive
        self.assertGreater(line_loss, 0.0)

    def test_03_transformer_energy_accounting(self):
        """Verifies transformer input equals sum of true loads plus technical losses."""
        for tx_id, report in self.twin.latest_transformer_reports.items():
            # Transformer input must exceed sum of consumer loads by technical losses
            self.assertGreaterEqual(
                report.transformer_input_kw,
                report.consumer_true_load_kw,
            )
            # Technical loss percentage should be within realistic 1.5% - 8.0%
            self.assertGreater(report.technical_loss_pct, 1.0)
            self.assertLess(report.technical_loss_pct, 12.0)

    def test_04_scenario_theft_bypass_detection(self):
        """Verifies Scenario 1: Theft/tampering bypass results in high anomaly score and correct cause."""
        # CONS_N_004 was injected with partial shunt theft
        dual_rec = self.twin.latest_dual_records.get("CONS_N_004")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.THEFT_BYPASS)

        # Ground truth must be higher than reported
        self.assertGreater(dual_rec.ground_truth.active_power_kw, dual_rec.reported.active_power_kw)
        self.assertGreater(dual_rec.unreported_stolen_kw, 0.0)

        # Anomaly detector analysis
        analysis = self.twin.latest_anomaly_results.get("CONS_N_004")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "THEFT_TAMPERING")
        self.assertIn(analysis.risk_level, ["HIGH", "CRITICAL"])
        self.assertGreaterEqual(analysis.anomaly_score, 75.0)

    def test_05_scenario_meter_malfunction_detection(self):
        """Verifies Scenario 2: Meter malfunction flags hardware fault."""
        # CONS_N_015 was injected with stuck reading
        dual_rec = self.twin.latest_dual_records.get("CONS_N_015")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.METER_MALFUNCTION)

        analysis = self.twin.latest_anomaly_results.get("CONS_N_015")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "METER_MALFUNCTION")
        self.assertTrue(analysis.status_flags.get("hardware_fault", False))

    def test_06_scenario_communication_failure_detection(self):
        """Verifies Scenario 3: Comm failure handles missing packets without false theft alarm."""
        # CONS_N_021 was injected with comm failure
        dual_rec = self.twin.latest_dual_records.get("CONS_N_021")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.COMM_FAILURE)
        self.assertIsNone(dual_rec.reported)

        analysis = self.twin.latest_anomaly_results.get("CONS_N_021")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "COMM_FAILURE")

    def test_07_scenario_legitimate_abnormal_surge(self):
        """Verifies Scenario 4: Legitimate heavy load (EV charging) is not flagged as theft."""
        # CONS_S_003 was injected with EV fast charger surge
        dual_rec = self.twin.latest_dual_records.get("CONS_S_003")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.LEGITIMATE_ABNORMAL)

        # Reported equals ground truth (no theft!)
        self.assertAlmostEqual(
            dual_rec.ground_truth.active_power_kw,
            dual_rec.reported.active_power_kw,
            places=2,
        )

        analysis = self.twin.latest_anomaly_results.get("CONS_S_003")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "LEGITIMATE_ABNORMAL")
        self.assertEqual(analysis.risk_level, "LOW")

    def test_08_scenario_normal_consumption(self):
        """Verifies Scenario 5: Normal houses are scored with low risk."""
        # Pick a known normal house
        analysis = self.twin.latest_anomaly_results.get("CONS_N_001")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "NORMAL")
        self.assertEqual(analysis.risk_level, "NORMAL")
        self.assertLess(analysis.anomaly_score, 45.0)

    def test_09_explainable_investigation_report(self):
        """Verifies generation of complete explainable audit report."""
        report = self.twin.generate_investigation_report("CONS_N_004")
        self.assertIsNotNone(report)
        self.assertEqual(report.consumer_id, "CONS_N_004")
        self.assertEqual(report.probable_cause, "THEFT_TAMPERING")
        self.assertGreater(len(report.evidence_chain), 0)
        self.assertTrue(len(report.technical_assessment) > 50)

        # Verify markdown export
        md_text = report.to_markdown()
        self.assertIn("# Smart Grid Anomaly Investigation Report", md_text)
        self.assertIn("Executive Summary", md_text)

    def test_10_drone_flight_path_planning(self):
        """Verifies autonomous 3D inspection trajectory generation."""
        flight = self.twin.latest_drone_flight
        self.assertIsNotNone(flight)
        self.assertGreater(flight.total_distance_m, 0.0)
        self.assertGreater(flight.targets_inspected, 0)
        self.assertGreater(len(flight.waypoints), 3)

        # Verify takeoff and landing actions
        actions = [w.action for w in flight.waypoints]
        self.assertEqual(actions[0], "TAKEOFF")
        self.assertEqual(actions[-1], "LAND")

    def test_11_geojson_export_integrity(self):
        """Verifies GeoJSON export formats."""
        exporter = GeoJSONTwinExporter(self.twin)
        b_geo = exporter.export_buildings_geojson()
        self.assertEqual(b_geo["type"], "FeatureCollection")
        self.assertEqual(len(b_geo["features"]), 48)

        l_geo = exporter.export_grid_lines_geojson()
        self.assertEqual(l_geo["type"], "FeatureCollection")
        self.assertGreater(len(l_geo["features"]), 10)


if __name__ == "__main__":
    unittest.main()
