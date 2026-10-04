"""
Adafruit IO MQTT Bridge for Physical ESP32 Hardware Integration.
Connects to io.adafruit.com to ingest real-time voltage, current, active power,
and cumulative energy from an ESP32 smart meter hardware bench prototype.

Routes live physical sensor data to:
- 1 Flagged Transformer (e.g. TX_101)
- 1 Flagged Consumer Smart Meter (e.g. CONS_N_004)
While keeping all other grid nodes on the virtual IoT simulation engine.
"""
from __future__ import annotations
import json
import time
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
import asyncio
import paho.mqtt.client as mqtt

from engine.digital_twin import SmartGridDigitalTwin
from models.telemetry import TelemetryReading, MeterStatusFlags, DualStateRecord, ScenarioType

logger = logging.getLogger("GridNestAdafruitIO")


class AdafruitIOBridge:
    """
    Client bridge connecting GridNest Digital Twin to Adafruit IO MQTT Broker.
    Broker: io.adafruit.com (Port 1883 or 8883)
    Topic pattern: {username}/feeds/{feed_name}
    """

    def __init__(
        self,
        twin: SmartGridDigitalTwin,
        username: str = "",
        key: str = "",
        aio_key: str = "",
        feed: str = "smartgrid",
        physical_transformer_id: str = "TX_101",
        physical_consumer_id: str = "CONS_N_004",
        broadcast_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.twin = twin
        self.username = username.strip()
        self.key = (key or aio_key).strip()
        self.feed = feed.strip() or "smartgrid"
        self.physical_transformer_id = physical_transformer_id
        self.physical_consumer_id = physical_consumer_id
        self.broadcast_callback = broadcast_callback

        self.client: Optional[mqtt.Client] = None
        self.is_connected = False
        self.last_packet_time: Optional[str] = None
        self.packets_received = 0
        self.latest_readings: Dict[str, Any] = {}
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts the background MQTT connection to Adafruit IO if credentials exist."""
        self.event_loop = loop
        if not self.username or not self.key:
            logger.info("[Adafruit IO Bridge] No credentials configured yet. Running in standby mode.")
            return

        self._connect_client()

    def _connect_client(self):
        """Initializes and connects Paho MQTT client to Adafruit IO."""
        try:
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass

            client_id = f"gridnest_twin_{int(time.time())}"
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
            self.client.username_pw_set(self.username, self.key)

            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            logger.info(f"[Adafruit IO Bridge] Connecting to io.adafruit.com:1883 as {self.username}...")
            self.client.connect_async("io.adafruit.com", 1883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"[Adafruit IO Bridge] Connection error: {e}")
            self.is_connected = False

    def stop(self):
        """Stops the Adafruit IO MQTT client."""
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.is_connected = False

    def update_credentials(
        self,
        username: str = "",
        key: str = "",
        feed: Optional[str] = None,
        physical_tx_id: Optional[str] = None,
        physical_cons_id: Optional[str] = None,
        target_transformer_id: Optional[str] = None,
        target_consumer_id: Optional[str] = None,
    ):
        """Allows dynamically updating credentials and target node mapping without restarting."""
        if username:
            self.username = username.strip()
        if key:
            self.key = key.strip()
        if feed:
            self.feed = feed.strip()
        
        tx_id = physical_tx_id or target_transformer_id
        if tx_id:
            self.physical_transformer_id = tx_id.strip()
            self.twin.physical_transformer_id = self.physical_transformer_id

        cons_id = physical_cons_id or target_consumer_id
        if cons_id:
            self.physical_consumer_id = cons_id.strip()
            self.twin.physical_consumer_id = self.physical_consumer_id

        if self.username and self.key:
            self._connect_client()
        else:
            self.stop()

    update_config = update_credentials

    def parse_payload(self, payload_str: str) -> Optional[Dict[str, Any]]:
        """Parses JSON or CSV payload string into normalized dictionary."""
        data: Dict[str, Any] = {}
        payload_str = payload_str.strip()
        if payload_str.startswith("{") and payload_str.endswith("}"):
            try:
                data = json.loads(payload_str)
            except Exception:
                return None
        elif "," in payload_str:
            parts = [p.strip() for p in payload_str.split(",")]
            if len(parts) >= 8:
                try:
                    data = {
                        "transVoltage": float(parts[0]),
                        "transCurrent": float(parts[1]),
                        "transPower": float(parts[2]),
                        "transEnergy": float(parts[3]),
                        "consVoltage": float(parts[4]),
                        "consCurrent": float(parts[5]),
                        "consPower": float(parts[6]),
                        "consEnergy": float(parts[7]),
                        "powerLoss": float(parts[8]) if len(parts) > 8 else 0.0,
                        "energyLoss": float(parts[9]) if len(parts) > 9 else 0.0,
                    }
                except Exception:
                    return None
        if not data:
            return None

        trans_v = float(data.get("transVoltage", data.get("transV", 230.0)))
        trans_c = float(data.get("transCurrent", data.get("transC", 0.0)))
        cons_v = float(data.get("consVoltage", data.get("consV", 230.0)))
        cons_c = float(data.get("consCurrent", data.get("consC", 0.0)))
        power_loss = float(data.get("powerLoss", data.get("powerLoss_W", max(0.0, (trans_v * trans_c / 1000.0) - (cons_v * cons_c / 1000.0)))))
        return {
            "trans_v": trans_v,
            "trans_c_ma": trans_c,
            "cons_v": cons_v,
            "cons_c_ma": cons_c,
            "power_loss_w": power_loss,
            "raw": data,
        }

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            topic = f"{self.username}/feeds/{self.feed}"
            client.subscribe(topic)
            # Also subscribe to wildcard feeds under user account
            client.subscribe(f"{self.username}/feeds/+")
            logger.info(f"[Adafruit IO Bridge] Connected to Adafruit IO! Subscribed to {topic}")
        else:
            self.is_connected = False
            reasons = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password (AIO Key)",
                5: "Not authorized",
            }
            logger.error(f"[Adafruit IO Bridge] Connection failed (rc={rc}): {reasons.get(rc, 'Unknown error')}")

    def _on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        if rc != 0:
            logger.warning(f"[Adafruit IO Bridge] Disconnected unexpectedly (rc={rc}). Will auto-reconnect.")

    def _on_message(self, client, userdata, msg):
        """Processes incoming packet from Adafruit IO."""
        try:
            payload_str = msg.payload.decode("utf-8", errors="replace").strip()
            self.process_raw_payload(payload_str, topic=msg.topic)
        except Exception as e:
            logger.error(f"[Adafruit IO Bridge] Error processing message: {e}")

    def process_raw_payload(self, payload_str: str, topic: str = ""):
        """
        Parses incoming payload from physical ESP32.
        Supports:
        1. JSON payload:
           {
             "transVoltage": 230.1, "transCurrent": 1250.0, "transPower": 287.6, "transEnergy": 4.12,
             "consVoltage": 229.4, "consCurrent": 1240.0, "consPower": 284.4, "consEnergy": 4.08,
             "powerLoss": 3.2, "energyLoss": 0.04
           }
        2. Comma-separated string format:
           "230.1,1250.0,287.6,4.12,229.4,1240.0,284.4,4.08,3.2,0.04"
        """
        data: Dict[str, Any] = {}

        if payload_str.startswith("{") and payload_str.endswith("}"):
            try:
                data = json.loads(payload_str)
            except Exception:
                data = {}
        elif "," in payload_str:
            parts = [p.strip() for p in payload_str.split(",")]
            if len(parts) >= 8:
                try:
                    data = {
                        "transVoltage": float(parts[0]),
                        "transCurrent": float(parts[1]),
                        "transPower": float(parts[2]),
                        "transEnergy": float(parts[3]),
                        "consVoltage": float(parts[4]),
                        "consCurrent": float(parts[5]),
                        "consPower": float(parts[6]),
                        "consEnergy": float(parts[7]),
                        "powerLoss": float(parts[8]) if len(parts) > 8 else 0.0,
                        "energyLoss": float(parts[9]) if len(parts) > 9 else 0.0,
                    }
                except Exception:
                    data = {}

        if not data:
            logger.warning(f"[Adafruit IO Bridge] Unrecognized payload format: {payload_str}")
            return

        self._apply_hardware_data_to_twin(data)

    def _apply_hardware_data_to_twin(self, data: Dict[str, Any]):
        """Injects live physical readings into the flagged Transformer and Consumer."""
        # 1. Parse Transformer sensor measurements
        trans_v = float(data.get("transVoltage", data.get("transV", 230.0)))
        trans_c_ma = float(data.get("transCurrent", data.get("transC", 0.0)))
        trans_p_w = float(data.get("transPower", data.get("transP", trans_v * (trans_c_ma / 1000.0))))
        trans_e_wh = float(data.get("transEnergy", data.get("transE", 0.0)))

        # 2. Parse Consumer sensor measurements
        cons_v = float(data.get("consVoltage", data.get("consV", 230.0)))
        cons_c_ma = float(data.get("consCurrent", data.get("consC", 0.0)))
        cons_p_w = float(data.get("consPower", data.get("consP", cons_v * (cons_c_ma / 1000.0))))
        cons_e_wh = float(data.get("consEnergy", data.get("consE", 0.0)))

        # 3. System loss
        power_loss_w = float(data.get("powerLoss", data.get("loss_w", max(0.0, trans_p_w - cons_p_w))))
        energy_loss_wh = float(data.get("energyLoss", data.get("loss_wh", max(0.0, trans_e_wh - cons_e_wh))))

        self.packets_received += 1
        self.last_packet_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.latest_readings = {
            "trans_v": round(trans_v, 2),
            "trans_c_ma": round(trans_c_ma, 2),
            "trans_p_w": round(trans_p_w, 2),
            "trans_p_kw": round(trans_p_w / 1000.0, 4),
            "trans_e_wh": round(trans_e_wh, 4),
            "cons_v": round(cons_v, 2),
            "cons_c_ma": round(cons_c_ma, 2),
            "cons_p_w": round(cons_p_w, 2),
            "cons_p_kw": round(cons_p_w / 1000.0, 4),
            "cons_e_wh": round(cons_e_wh, 4),
            "power_loss_w": round(power_loss_w, 2),
            "energy_loss_wh": round(energy_loss_wh, 4),
            "loss_pct": round((power_loss_w / max(1.0, trans_p_w)) * 100.0, 1),
        }

        # Update Flagged Consumer in Digital Twin
        cid = self.physical_consumer_id
        consumer = self.twin.topology.consumers.get(cid)
        if consumer:
            cons_kw = max(0.0, cons_p_w / 1000.0)
            cons_curr_a = max(0.0, cons_c_ma / 1000.0)
            cons_kwh = max(0.0, cons_e_wh / 1000.0)

            # Check if there is a severe physical current discrepancy (tamper/shunt)
            is_theft_divergence = (trans_p_w > 10.0 and cons_p_w < trans_p_w * 0.65)

            flags = MeterStatusFlags(
                reverse_current=False,
                magnetic_tamper=is_theft_divergence,
                tamper_cover_opened=False,
                hardware_fault=False,
                communication_error=False,
            )

            reading = TelemetryReading(
                timestamp=self.twin.clock.iso_format,
                consumer_id=cid,
                meter_id=consumer.meter_id,
                voltage_v=cons_v,
                current_a=cons_curr_a,
                active_power_kw=cons_kw,
                reactive_power_kvar=round(cons_kw * 0.25, 3),
                power_factor=0.96,
                cumulative_energy_kwh=cons_kwh,
                frequency_hz=50.0,
                status_flags=flags,
                is_missing=False,
            )

            existing_dual = self.twin.latest_dual_records.get(cid)
            if existing_dual:
                existing_dual.reported = reading
                # The physical transformer sensor provides ground-truth input
                existing_dual.ground_truth.active_power_kw = round(trans_p_w / 1000.0, 4)
                existing_dual.ground_truth.voltage_v = trans_v
                existing_dual.ground_truth.current_a = round(trans_c_ma / 1000.0, 4)
            else:
                self.twin.latest_dual_records[cid] = DualStateRecord(
                    timestamp=reading.timestamp,
                    consumer_id=cid,
                    meter_id=consumer.meter_id,
                    active_scenario=ScenarioType.THEFT_SHUNT if is_theft_divergence else ScenarioType.NORMAL,
                    ground_truth=reading,
                    reported=reading,
                    line_loss_kw=round(power_loss_w / 1000.0, 4),
                )

        # Update Flagged Transformer in Digital Twin
        tx_id = self.physical_transformer_id
        tx_report = self.twin.latest_transformer_reports.get(tx_id)
        if tx_report:
            tx_input_kw = max(0.0, trans_p_w / 1000.0)
            tx_report.transformer_input_kw = tx_input_kw
            tx_report.cumulative_energy_input_kwh += (trans_e_wh / 1000.0)

        # Re-evaluate multi-signal anomaly detection with fresh hardware telemetry
        records_list = list(self.twin.latest_dual_records.values())
        hour_int = getattr(self.twin.clock.current_time, 'hour', 12) if hasattr(self.twin, 'clock') and hasattr(self.twin.clock, 'current_time') else 12
        if self.twin.detector:
            self.twin.latest_anomaly_results = self.twin.detector.analyze_records(
                records=records_list,
                consumers=self.twin.topology.consumers,
                transformer_reports=self.twin.latest_transformer_reports,
                hour_int=hour_int,
            )
            if hasattr(self.twin, 'prioritizer'):
                self.twin.latest_inspection_targets = self.twin.prioritizer.prioritize_consumers(
                    anomaly_results=self.twin.latest_anomaly_results,
                    consumers=self.twin.topology.consumers,
                )

        logger.info(f"[Adafruit IO] Processed packet #{self.packets_received}: "
                    f"Trans={trans_p_w:.1f}W, Cons={cons_p_w:.1f}W, Loss={power_loss_w:.1f}W")

        # Broadcast update to web clients via WebSocket
        if self.broadcast_callback and self.event_loop:
            try:
                snapshot = self.twin.get_snapshot()
                asyncio.run_coroutine_threadsafe(self.broadcast_callback(snapshot), self.event_loop)
            except Exception as e:
                logger.debug(f"[Adafruit IO Bridge] Broadcast error: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Returns live bridge status, connection state, and latest hardware telemetry."""
        return {
            "enabled": bool(self.username and self.key),
            "connected": self.is_connected,
            "broker": "io.adafruit.com",
            "port": 1883,
            "username": self.username if self.username else "NOT_CONFIGURED",
            "feed": self.feed,
            "physical_transformer_id": self.physical_transformer_id,
            "physical_consumer_id": self.physical_consumer_id,
            "packets_received": self.packets_received,
            "last_packet_time": self.last_packet_time or "Never",
            "latest_readings": self.latest_readings,
        }
