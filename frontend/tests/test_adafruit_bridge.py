"""
Unit tests for Adafruit IO MQTT Bridge and ESP32 hardware telemetry ingestion.
Verifies payload decoding, physical-to-virtual node attribution, and digital twin state updates.
"""
import json
from pathlib import Path
import sys
import unittest

# Ensure frontend root is on sys.path
frontend_dir = Path(__file__).resolve().parent.parent
if str(frontend_dir) not in sys.path:
    sys.path.insert(0, str(frontend_dir))

from engine.digital_twin import SmartGridDigitalTwin
from iot.adafruit_bridge import AdafruitIOBridge


class TestAdafruitBridge(unittest.TestCase):
    def setUp(self):
        self.twin = SmartGridDigitalTwin(seed=42)
        self.twin.initialize(setup_scenarios=True)
        self.bridge = AdafruitIOBridge(
            twin=self.twin,
            username="test_user",
            aio_key="aio_testkey123",
            feed="smartgrid",
            physical_transformer_id="TX_101",
            physical_consumer_id="CONS_N_004",
        )

    def test_bridge_initialization(self):
        st = self.bridge.get_status()
        self.assertEqual(st["username"], "test_user")
        self.assertEqual(st["feed"], "smartgrid")
        self.assertEqual(st["physical_transformer_id"], "TX_101")
        self.assertEqual(st["physical_consumer_id"], "CONS_N_004")
        self.assertEqual(st["packets_received"], 0)

    def test_parse_json_esp32_payload(self):
        raw_payload = json.dumps({
            "transVoltage": 231.5,
            "transCurrent": 4120.0,
            "transPower_W": 953.78,
            "transEnergy_Wh": 14.25,
            "consVoltage": 228.6,
            "consCurrent": 1180.0,
            "consPower_W": 269.75,
            "consEnergy_Wh": 4.12,
            "powerLoss_W": 684.03,
            "energyLoss_Wh": 10.13,
        })
        parsed = self.bridge.parse_payload(raw_payload)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["trans_v"], 231.5, places=1)
        self.assertAlmostEqual(parsed["trans_c_ma"], 4120.0, places=1)
        self.assertAlmostEqual(parsed["cons_v"], 228.6, places=1)
        self.assertAlmostEqual(parsed["cons_c_ma"], 1180.0, places=1)
        self.assertAlmostEqual(parsed["power_loss_w"], 684.03, places=1)

    def test_parse_csv_payload_fallback(self):
        csv_payload = "230.0,4000.0,920.0,10.0,229.0,1000.0,229.0,2.5,691.0,7.5"
        parsed = self.bridge.parse_payload(csv_payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["trans_v"], 230.0)
        self.assertEqual(parsed["trans_c_ma"], 4000.0)
        self.assertEqual(parsed["cons_v"], 229.0)
        self.assertEqual(parsed["cons_c_ma"], 1000.0)

    def test_apply_hardware_data_updates_twin_nodes(self):
        sample_payload = json.dumps({
            "transVoltage": 230.5,
            "transCurrent": 4500.0,
            "consVoltage": 228.0,
            "consCurrent": 1200.0,
            "powerLoss_W": 765.0,
            "energyLoss_Wh": 0.5,
        })
        self.bridge.process_raw_payload(sample_payload)

        # Check bridge packet counter
        st = self.bridge.get_status()
        self.assertEqual(st["packets_received"], 1)

        # Check digital twin snapshot flags
        snap = self.twin.get_snapshot()
        self.assertEqual(snap["physical_iot"]["transformer_id"], "TX_101")
        self.assertEqual(snap["physical_iot"]["consumer_id"], "CONS_N_004")

        # Verify TX_101 is flagged physical
        tx101 = snap["transformers"]["TX_101"]
        self.assertTrue(tx101["is_physical_iot"])
        self.assertIn("Adafruit IO ESP32", tx101["hardware_source"])
        self.assertIn("GPIO 35", tx101["hardware_pins"])

        # Verify other transformer TX_102 is virtual
        tx102 = snap["transformers"]["TX_102"]
        self.assertFalse(tx102["is_physical_iot"])

        # Verify CONS_N_004 is flagged physical
        cons4 = snap["consumers"]["CONS_N_004"]
        self.assertTrue(cons4["is_physical_iot"])
        self.assertIn("Adafruit IO ESP32", cons4["hardware_source"])
        self.assertIn("GPIO 33", cons4["hardware_pins"])

        # Verify other consumers (e.g., CONS_N_001) are virtual
        cons1 = snap["consumers"]["CONS_N_001"]
        self.assertFalse(cons1["is_physical_iot"])

    def test_dynamic_remapping_of_physical_nodes(self):
        # Remap to TX_102 and CONS_S_003
        self.bridge.update_config(
            target_transformer_id="TX_102",
            target_consumer_id="CONS_S_003",
        )
        snap = self.twin.get_snapshot()
        self.assertFalse(snap["transformers"]["TX_101"]["is_physical_iot"])
        self.assertTrue(snap["transformers"]["TX_102"]["is_physical_iot"])
        self.assertFalse(snap["consumers"]["CONS_N_004"]["is_physical_iot"])
        self.assertTrue(snap["consumers"]["CONS_S_003"]["is_physical_iot"])


if __name__ == "__main__":
    unittest.main()
