"""
GridNest MQTT Bridge for Smart Grid Digital Twin.
Translates incoming IoT MQTT sensor packets and control messages into
real-time Digital Twin state updates, triggers hybrid AI/ML anomaly scoring,
and pushes live synchronized snapshots to WebSockets and browser dashboards.
"""
from __future__ import annotations
import json
import logging
from typing import Dict, Any, Callable, Awaitable, Optional

from engine.digital_twin import SmartGridDigitalTwin
from models.telemetry import ScenarioType, TelemetryReading, MeterStatusFlags, DualStateRecord
from iot.mqtt_broker import MicroMQTTBroker

logger = logging.getLogger("GridNestMQTTBridge")


class SmartGridMQTTBridge:
    """
    Subscribes to grid MQTT topics and syncs with the Digital Twin.
    Topics:
      - grid/meters/{consumer_id}/telemetry
      - grid/transformers/{tx_id}/telemetry
      - grid/power_station/telemetry
      - grid/control/inject
      - grid/control/restore
      - grid/control/step
    """

    def __init__(
        self,
        twin: SmartGridDigitalTwin,
        broker: MicroMQTTBroker,
        broadcast_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.twin = twin
        self.broker = broker
        self.broadcast_callback = broadcast_callback
        self.broker.on_message(self.handle_incoming_message)

    def handle_incoming_message(self, topic: str, payload_bytes: bytes):
        """Dispatches incoming MQTT packet to appropriate twin handler."""
        try:
            payload_str = payload_bytes.decode("utf-8", errors="replace")
            data = json.loads(payload_str)
        except Exception:
            data = {}

        # 1. Meter telemetry
        if topic.startswith("grid/meters/") and topic.endswith("/telemetry"):
            parts = topic.split("/")
            if len(parts) >= 4:
                cid = parts[2]
                self._process_meter_telemetry(cid, data)

        # 2. Control injection
        elif topic == "grid/control/inject":
            self._process_control_inject(data)

        # 3. Control restore
        elif topic == "grid/control/restore":
            self._process_control_restore(data)

        # 4. Control step
        elif topic == "grid/control/step":
            self._process_control_step()

    def _process_meter_telemetry(self, cid: str, data: Dict[str, Any]):
        """Injects custom sensor reading from virtual IoT meter."""
        consumer = self.twin.topology.consumers.get(cid)
        if not consumer:
            return

        kw = float(data.get("active_power_kw", 0.0))
        volt = float(data.get("voltage_v", 230.0))
        curr = float(data.get("current_a", kw * 1000.0 / max(1.0, volt)))
        pf = float(data.get("power_factor", 0.95))
        is_missing = bool(data.get("is_missing", False))
        raw_flags = data.get("status_flags", {})

        flags = MeterStatusFlags(
            tamper_cover_opened=bool(raw_flags.get("tamper_cover_opened", False)),
            magnetic_tamper=bool(raw_flags.get("magnetic_tamper", False)),
            reverse_current=bool(raw_flags.get("reverse_current", False)),
            neutral_missing=bool(raw_flags.get("neutral_missing", False)),
            low_battery=bool(raw_flags.get("low_battery", False)),
            hardware_fault=bool(raw_flags.get("hardware_fault", False)),
            communication_error=bool(raw_flags.get("communication_error", False)),
            voltage_out_of_range=bool(raw_flags.get("voltage_out_of_range", False)),
        )

        reading = TelemetryReading(
            timestamp=self.twin.clock.iso_format,
            consumer_id=cid,
            meter_id=consumer.meter_id,
            voltage_v=volt,
            current_a=curr,
            active_power_kw=kw,
            reactive_power_kvar=round(kw * 0.3, 3),
            power_factor=pf,
            cumulative_energy_kwh=self.twin.cumulative_reported_kwh.get(cid, 100.0),
            frequency_hz=50.0,
            status_flags=flags,
            is_missing=is_missing,
        )

        # Update latest dual record reported side
        existing_dual = self.twin.latest_dual_records.get(cid)
        if existing_dual:
            existing_dual.reported = reading if not is_missing else None
        else:
            self.twin.latest_dual_records[cid] = DualStateRecord(
                timestamp=reading.timestamp,
                consumer_id=cid,
                meter_id=consumer.meter_id,
                active_scenario=ScenarioType.NORMAL,
                ground_truth=reading,
                reported=reading if not is_missing else None,
                line_loss_kw=0.05,
            )

        # Trigger re-evaluation and broadcast
        self._trigger_eval_and_broadcast()

    def _process_control_inject(self, data: Dict[str, Any]):
        cid = data.get("consumer_id")
        scen_str = data.get("scenario", "NORMAL").upper()
        params = data.get("params", {})
        if not cid or cid not in self.twin.topology.consumers:
            return

        try:
            scen_type = ScenarioType(scen_str)
            self.twin.inject_scenario(cid, scen_type, params)
            self.twin.step()
            self._trigger_eval_and_broadcast()
            logger.info(f"[MQTT Bridge] Injected {scen_type.value} on {cid}")
        except Exception as e:
            logger.error(f"[MQTT Bridge] Failed to inject scenario: {e}")

    def _process_control_restore(self, data: Dict[str, Any]):
        cid = data.get("consumer_id")
        if not cid:
            return
        self.twin.clear_scenario(cid)
        self.twin.step()
        self._trigger_eval_and_broadcast()
        logger.info(f"[MQTT Bridge] Restored {cid} to NORMAL")

    def _process_control_step(self):
        self.twin.step()
        self._trigger_eval_and_broadcast()

    def _trigger_eval_and_broadcast(self):
        """Broadcasts current snapshot to web viewers."""
        if self.broadcast_callback:
            snapshot = self.twin.get_snapshot()
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast_callback(snapshot))
            except RuntimeError:
                pass
