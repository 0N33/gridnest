"""
Unit tests for GridNest MicroMQTTBroker, SmartGridMQTTBridge, and VirtualIoTSimulator.
Verifies MQTT 3.1.1 protocol handling, sensor packet translation, and twin synchronization.
"""
import asyncio
import json
import unittest

from engine.digital_twin import SmartGridDigitalTwin
from models.telemetry import ScenarioType
from iot.mqtt_broker import MicroMQTTBroker
from iot.mqtt_bridge import SmartGridMQTTBridge
from iot.iot_simulator import VirtualIoTSimulator


class TestIoTMQTT(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.twin = SmartGridDigitalTwin(seed=42)
        self.twin.initialize(setup_scenarios=True)
        # Use port 19883 for isolated test broker
        self.broker = MicroMQTTBroker(host="127.0.0.1", port=19883)
        self.bridge = SmartGridMQTTBridge(twin=self.twin, broker=self.broker)
        await self.broker.start()

    async def asyncTearDown(self):
        await self.broker.stop()

    async def test_broker_publish_local_and_callback(self):
        received_msgs = []

        def on_msg(topic, payload):
            received_msgs.append((topic, payload))

        self.broker.on_message(on_msg)
        await self.broker.publish_local("grid/test/topic", b'{"status": "ok"}')

        self.assertEqual(len(received_msgs), 1)
        self.assertEqual(received_msgs[0][0], "grid/test/topic")
        self.assertEqual(received_msgs[0][1], b'{"status": "ok"}')

    async def test_bridge_injects_theft_scenario(self):
        inject_payload = {
            "consumer_id": "CONS_N_004",
            "scenario": "THEFT_BYPASS",
            "params": {"scaling_factor": 0.20, "trigger_tamper_flag": True},
        }
        await self.broker.publish_local("grid/control/inject", json.dumps(inject_payload))

        snap = self.twin.get_snapshot()
        c4 = snap["consumers"]["CONS_N_004"]
        an = c4.get("analysis", {})
        self.assertEqual(an.get("probable_cause"), "THEFT_TAMPERING")
        self.assertGreaterEqual(an.get("anomaly_score", 0), 80.0)

    async def test_bridge_restores_consumer(self):
        # Inject theft on normal consumer CONS_N_003
        await self.broker.publish_local("grid/control/inject", json.dumps({
            "consumer_id": "CONS_N_003",
            "scenario": "THEFT_BYPASS",
            "params": {"scaling_factor": 0.20, "trigger_tamper_flag": True},
        }))
        snap1 = self.twin.get_snapshot()
        self.assertEqual(snap1["consumers"]["CONS_N_003"]["analysis"]["probable_cause"], "THEFT_TAMPERING")

        # Then restore
        await self.broker.publish_local("grid/control/restore", json.dumps({
            "consumer_id": "CONS_N_003",
        }))

        snap2 = self.twin.get_snapshot()
        c3 = snap2["consumers"]["CONS_N_003"]
        an = c3.get("analysis", {})
        self.assertEqual(an.get("probable_cause"), "NORMAL")
        self.assertLess(an.get("anomaly_score", 100), 40.0)

    async def test_bridge_ingests_custom_meter_telemetry(self):
        sensor_data = {
            "consumer_id": "CONS_N_001",
            "meter_id": "MTR_N_001",
            "active_power_kw": 0.15,
            "voltage_v": 230.5,
            "current_a": 0.65,
            "status_flags": {"magnetic_tamper": True},
            "is_missing": False,
        }
        await self.broker.publish_local("grid/meters/CONS_N_001/telemetry", json.dumps(sensor_data))

        dual = self.twin.latest_dual_records.get("CONS_N_001")
        self.assertIsNotNone(dual)
        self.assertIsNotNone(dual.reported)
        self.assertAlmostEqual(dual.reported.active_power_kw, 0.15, places=2)
        self.assertTrue(dual.reported.status_flags.magnetic_tamper)


class TestIoTSimulatorMethods(unittest.TestCase):
    def test_simulator_payload_generation(self):
        sim = VirtualIoTSimulator(mqtt_host="127.0.0.1", mqtt_port=19883)
        # Verify method calls return True/False without crashing
        res = sim._http_fallback("grid/control/unknown", {})
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()
