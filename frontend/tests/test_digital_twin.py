"""
Comprehensive Test Suite for Smart Grid Digital Twin.
Verifies grid physics, 3-zone architecture, 5 operational scenarios,
dual-state synchronization, transformer energy accounting, and explainable report generation.
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

    def test_01_grid_topology_structure_3zones(self):
        """Verifies 3-Zone architecture: Power Station, Zone 1 North, Zone 2 South."""
        top = self.twin.topology
        self.assertIsNotNone(top)

        # Zone 0: Power Station
        self.assertIsNotNone(top.power_station)
        self.assertEqual(top.power_station.zone_id, "Zone_0_PowerStation")
        self.assertGreater(len(top.power_station.iot_sensors), 3)

        # Transmission Infrastructure
        self.assertGreaterEqual(len(top.pylons), 4)
        self.assertGreaterEqual(len(top.roads), 5)

        # Distribution Transformers (Zones 1 & 2)
        self.assertEqual(len(top.transformers), 2)
        self.assertIn("TX_101", top.transformers)
        self.assertIn("TX_102", top.transformers)

        self.assertEqual(len(top.feeders), 2)
        self.assertEqual(len(top.consumers), 48)

        # Verify each city zone has 24 consumers
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
        self.assertLess(params.voltage_v, 230.0)
        self.assertGreater(params.voltage_v, 215.0)
        self.assertGreater(params.current_a, 15.0)
        self.assertLess(params.current_a, 22.0)
        self.assertGreater(line_loss, 0.0)

    def test_03_transformer_energy_accounting_reconciliation(self):
        """Verifies power inputted vs meters added up reconciliation."""
        for tx_id, report in self.twin.latest_transformer_reports.items():
            rep_dict = report.to_dict()
            self.assertIn("power_inputted_kwh", rep_dict)
            self.assertIn("meters_added_kwh", rep_dict)
            self.assertIn("missing_kwh", rep_dict)
            self.assertIn("is_done_for", rep_dict)

            # Inputted must exceed or equal meters added
            self.assertGreaterEqual(
                report.cumulative_energy_input_kwh,
                report.cumulative_reported_kwh,
            )

    def test_04_scenario_theft_bypass_detection(self):
        """Verifies Scenario 1: Theft/tampering bypass causes high anomaly score and theft cause."""
        dual_rec = self.twin.latest_dual_records.get("CONS_N_004")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.THEFT_BYPASS)

        self.assertGreater(dual_rec.ground_truth.active_power_kw, dual_rec.reported.active_power_kw)
        self.assertGreater(dual_rec.unreported_stolen_kw, 0.0)

        analysis = self.twin.latest_anomaly_results.get("CONS_N_004")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "THEFT_TAMPERING")
        self.assertIn(analysis.risk_level, ["HIGH", "CRITICAL"])
        self.assertGreaterEqual(analysis.anomaly_score, 70.0)

    def test_05_scenario_meter_malfunction_detection(self):
        """Verifies Scenario 2: Meter malfunction flags hardware fault."""
        dual_rec = self.twin.latest_dual_records.get("CONS_N_015")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.METER_MALFUNCTION)

        analysis = self.twin.latest_anomaly_results.get("CONS_N_015")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "METER_MALFUNCTION")
        self.assertTrue(analysis.status_flags.get("hardware_fault", False))

    def test_06_scenario_communication_failure_detection(self):
        """Verifies Scenario 3: Comm failure handles missing packets without false theft alarm."""
        dual_rec = self.twin.latest_dual_records.get("CONS_N_021")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.COMM_FAILURE)
        self.assertIsNone(dual_rec.reported)

        analysis = self.twin.latest_anomaly_results.get("CONS_N_021")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "COMM_FAILURE")

    def test_07_scenario_legitimate_abnormal_surge(self):
        """Verifies Scenario 4: Legitimate heavy load (EV charging) is not flagged as theft."""
        dual_rec = self.twin.latest_dual_records.get("CONS_S_003")
        self.assertIsNotNone(dual_rec)
        self.assertEqual(dual_rec.active_scenario, ScenarioType.LEGITIMATE_ABNORMAL)

        analysis = self.twin.latest_anomaly_results.get("CONS_S_003")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.probable_cause, "LEGITIMATE_ABNORMAL")
        self.assertEqual(analysis.risk_level, "LOW")

    def test_08_scenario_normal_consumption(self):
        """Verifies Scenario 5: Normal houses are scored with low risk."""
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

        md_text = report.to_markdown()
        self.assertIn("# Smart Grid Anomaly Investigation Report", md_text)

    def test_10_drone_flight_path_planning(self):
        """Verifies autonomous 3D inspection trajectory generation."""
        flight = self.twin.latest_drone_flight
        self.assertIsNotNone(flight)
        self.assertGreater(flight.total_distance_m, 0.0)
        self.assertGreater(flight.targets_inspected, 0)
        self.assertGreater(len(flight.waypoints), 3)

    def test_11_geojson_export_integrity(self):
        """Verifies GeoJSON export formats for 3 zones, buildings, roads, and lines."""
        exporter = GeoJSONTwinExporter(self.twin)
        b_geo = exporter.export_buildings_geojson()
        self.assertEqual(b_geo["type"], "FeatureCollection")
        # 48 consumers + 1 power station
        self.assertEqual(len(b_geo["features"]), 49)

        r_geo = exporter.export_roads_geojson()
        self.assertEqual(r_geo["type"], "FeatureCollection")
        self.assertGreater(len(r_geo["features"]), 3)

        l_geo = exporter.export_grid_lines_geojson()
        self.assertEqual(l_geo["type"], "FeatureCollection")
        self.assertGreater(len(l_geo["features"]), 10)


if __name__ == "__main__":
    unittest.main()
