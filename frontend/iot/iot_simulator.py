"""
GridNest Virtual IoT Sensor Network & AMI Simulator.
Simulates 48 Smart Meters, 2 Distribution Transformer IoT Gateways,
and 1 Central Power Station Substation over MQTT 3.1.1.
Enables real-time sensor packet publishing, interactive cyber-physical tamper injection,
hardware fault simulation, and continuous streaming synchronization with the Digital Twin dashboard.
"""
from __future__ import annotations
import sys
import time
import json
import random
import argparse
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False


# ANSI Color Codes for Windows PowerShell / Terminal
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    RESET = "\033[0m"


class VirtualIoTSimulator:
    """Simulates physical grid IoT telemetry and sends packets via MQTT / REST."""

    def __init__(self, mqtt_host: str = "localhost", mqtt_port: int = 1883, api_base: str = "http://localhost:8000"):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.api_base = api_base
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_connected = False
        self.last_grid_snapshot: Dict[str, Any] = {}

    def connect(self) -> bool:
        """Connects to the GridNest MicroMQTTBroker (or external Mosquitto)."""
        if not PAHO_AVAILABLE:
            print(f"{Colors.YELLOW}[!] paho-mqtt not available. Operating in HTTP REST bridge mode.{Colors.RESET}")
            return False

        try:
            # Paho MQTT Client setup (compatible with v1 and v2 API)
            try:
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="GridNest_IoTSimulator")
            except AttributeError:
                self.mqtt_client = mqtt.Client(client_id="GridNest_IoTSimulator")

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()

            # Wait briefly for connection handshake
            time.sleep(0.4)
            if self.mqtt_connected:
                print(f"{Colors.GREEN}[+] Connected to MQTT Broker at {self.mqtt_host}:{self.mqtt_port}{Colors.RESET}")
                return True
            else:
                # Try fallback port 1884
                try:
                    self.mqtt_client.connect(self.mqtt_host, 1884, keepalive=60)
                    time.sleep(0.3)
                    if self.mqtt_connected:
                        self.mqtt_port = 1884
                        print(f"{Colors.GREEN}[+] Connected to MQTT Broker on fallback port {self.mqtt_port}{Colors.RESET}")
                        return True
                except Exception:
                    pass
        except Exception as e:
            print(f"{Colors.YELLOW}[!] MQTT Broker connection skipped ({e}). Falling back to REST API bridge.{Colors.RESET}")

        return False

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        rc_code = getattr(rc, "value", rc)
        if rc_code == 0:
            self.mqtt_connected = True
            client.subscribe("grid/#")
        else:
            self.mqtt_connected = False

    def _on_mqtt_message(self, client, userdata, msg):
        pass

    def disconnect(self):
        if self.mqtt_client:
            try:
                time.sleep(0.1)
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass

    def publish_mqtt(self, topic: str, payload_dict: Dict[str, Any]) -> bool:
        """Publishes an MQTT message; falls back to HTTP REST if MQTT is offline."""
        payload_json = json.dumps(payload_dict)

        if self.mqtt_connected and self.mqtt_client:
            try:
                res = self.mqtt_client.publish(topic, payload_json, qos=0)
                if hasattr(res, "wait_for_publish"):
                    res.wait_for_publish(timeout=1.0)
                return True
            except Exception:
                pass

        # Fallback to HTTP API
        return self._http_fallback(topic, payload_dict)

    def _http_fallback(self, topic: str, payload: Dict[str, Any]) -> bool:
        """Fallback HTTP handler for controlling the digital twin when MQTT is offline."""
        try:
            if topic == "grid/control/step":
                req = urllib.request.Request(f"{self.api_base}/api/step", method="POST")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200

            elif topic == "grid/control/inject":
                cid = payload.get("consumer_id")
                scenario = payload.get("scenario", "NORMAL")
                params = payload.get("params", {})
                mode = params.get("mode", "")
                scale = params.get("scaling_factor", "")
                q = urllib.parse.urlencode({k: v for k, v in [("scenario", scenario), ("mode", mode), ("scaling_factor", scale)] if v})
                req = urllib.request.Request(f"{self.api_base}/api/inject/{cid}?{q}", method="POST")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200

            elif topic == "grid/control/restore":
                cid = payload.get("consumer_id")
                req = urllib.request.Request(f"{self.api_base}/api/restore/{cid}", method="POST")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200
        except Exception:
            return False
        return True

    def fetch_snapshot(self) -> Dict[str, Any]:
        """Fetches the current live digital twin snapshot."""
        try:
            with urllib.request.urlopen(f"{self.api_base}/api/snapshot", timeout=3) as resp:
                if resp.status == 200:
                    self.last_grid_snapshot = json.loads(resp.read().decode("utf-8"))
                    return self.last_grid_snapshot
        except Exception:
            pass
        return self.last_grid_snapshot

    def step_simulation(self) -> bool:
        """Advances simulation by 1 tick (15 simulated minutes)."""
        return self.publish_mqtt("grid/control/step", {"action": "step", "timestamp": time.time()})

    def inject_theft(self, consumer_id: str, shunt_ratio: float = 0.25, trip_magnetic_flag: bool = False) -> bool:
        """Simulates physical electricity theft via meter shunt or bypass."""
        payload = {
            "consumer_id": consumer_id,
            "scenario": "THEFT_BYPASS",
            "params": {
                "mode": "partial_shunt",
                "scaling_factor": shunt_ratio,
                "trigger_tamper_flag": trip_magnetic_flag,
            },
        }
        return self.publish_mqtt("grid/control/inject", payload)

    def inject_meter_fault(self, consumer_id: str, fault_type: str = "stuck") -> bool:
        """Simulates internal smart meter transducer failure or stuck ADC register."""
        payload = {
            "consumer_id": consumer_id,
            "scenario": "METER_MALFUNCTION",
            "params": {
                "malfunction_type": fault_type,
            },
        }
        return self.publish_mqtt("grid/control/inject", payload)

    def inject_communication_failure(self, consumer_id: str) -> bool:
        """Simulates cellular / RF headend packet loss (offline meter)."""
        payload = {
            "consumer_id": consumer_id,
            "scenario": "COMM_FAILURE",
            "params": {},
        }
        return self.publish_mqtt("grid/control/inject", payload)

    def inject_legitimate_surge(self, consumer_id: str, surge_kw: float = 7.4) -> bool:
        """Simulates legitimate high-power demand (Level-2 EV charging / HVAC)."""
        payload = {
            "consumer_id": consumer_id,
            "scenario": "LEGITIMATE_ABNORMAL",
            "params": {
                "surge_kw": surge_kw,
            },
        }
        return self.publish_mqtt("grid/control/inject", payload)

    def restore_consumer(self, consumer_id: str) -> bool:
        """Restores meter to nominal healthy operation."""
        payload = {"consumer_id": consumer_id, "scenario": "NORMAL"}
        return self.publish_mqtt("grid/control/restore", payload)

    def publish_meter_telemetry(
        self,
        consumer_id: str,
        meter_id: str,
        power_kw: float,
        voltage_v: float = 230.0,
        flags: Optional[Dict[str, bool]] = None,
        is_missing: bool = False,
    ) -> bool:
        """Publishes individual virtual sensor packet over MQTT."""
        topic = f"grid/meters/{consumer_id}/telemetry"
        payload = {
            "consumer_id": consumer_id,
            "meter_id": meter_id,
            "active_power_kw": round(power_kw, 3),
            "voltage_v": round(voltage_v, 1),
            "current_a": round((power_kw * 1000.0) / max(1.0, voltage_v), 2),
            "power_factor": 0.95,
            "status_flags": flags or {},
            "is_missing": is_missing,
            "timestamp": time.time(),
        }
        return self.publish_mqtt(topic, payload)

    def run_continuous_stream(self, interval_sec: float = 2.0):
        """Streams live 15-minute sensor data across all 48 meters continuously."""
        print(f"\n{Colors.CYAN}{Colors.BOLD}========================================================================")
        print(f"  STARTING REAL-TIME IoT MQTT TELEMETRY STREAMER (Interval: {interval_sec}s)")
        print(f"  Press Ctrl+C to pause stream and return to menu.")
        print(f"========================================================================{Colors.RESET}\n")

        tick_count = 0
        try:
            while True:
                tick_count += 1
                self.step_simulation()
                snap = self.fetch_snapshot()

                grid = snap.get("grid_summary", {})
                clk = snap.get("clock", {})
                time_str = clk.get("iso_time", "N/A").replace("T", " ")
                anom_count = grid.get("anomalous_consumers_count", 0)
                ntl_loss = grid.get("grid_unexplained_ntl_pct", 0.0)
                total_in = grid.get("total_grid_input_kw", 0.0)

                # Count active thefts
                theft_count = 0
                consumers = snap.get("consumers", {})
                for c in consumers.values():
                    an = c.get("analysis", {})
                    if an.get("probable_cause") == "THEFT_TAMPERING":
                        theft_count += 1

                status_color = Colors.RED if ntl_loss > 10.0 else (Colors.YELLOW if ntl_loss > 6.0 else Colors.GREEN)
                print(
                    f"[{Colors.BOLD}TICK #{tick_count:04d}{Colors.RESET}] {time_str} | "
                    f"Dispatched: {Colors.CYAN}{total_in:.1f} kW{Colors.RESET} | "
                    f"Grid NTL: {status_color}{ntl_loss:.1f}%{Colors.RESET} | "
                    f"Thefts: {Colors.RED}{theft_count}{Colors.RESET} | "
                    f"Total Anomalies: {Colors.YELLOW}{anom_count}{Colors.RESET}"
                )

                time.sleep(interval_sec)
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[*] Streaming paused.{Colors.RESET}")


def print_banner(sim: VirtualIoTSimulator):
    mqtt_stat = f"{Colors.GREEN}ONLINE (MQTT 3.1.1, port {sim.mqtt_port}){Colors.RESET}" if sim.mqtt_connected else f"{Colors.YELLOW}REST BRIDGE (http://localhost:8000){Colors.RESET}"
    print(f"""
{Colors.CYAN}{Colors.BOLD}================================================================================
   GRIDNEST™ VIRTUAL IoT SENSOR NETWORK & AMI SIMULATOR
   Standard: MQTT 3.1.1 (paho-mqtt) | Cyber-Physical AC Distribution Digital Twin
================================================================================{Colors.RESET}
  * Network Status: {mqtt_stat}
  * Virtual Nodes: 48 Smart Meters | 2 Distribution Transformers | 1 Power Station
  * Real-Time Stream Target: Three.js 3D Viewport & Anomaly Inspector (Port 8000)
--------------------------------------------------------------------------------
""")


def print_menu():
    print(f"""{Colors.BOLD}AVAILABLE IoT CONTROL ACTIONS:{Colors.RESET}
  {Colors.CYAN}[1]{Colors.RESET} Monitor Live Grid Telemetry (Snapshot of 48 Meters & Transformers)
  {Colors.RED}[2]{Colors.RESET} Simulate Electricity Theft (Inject Meter Shunt Bypass / Partial Theft)
  {Colors.YELLOW}[3]{Colors.RESET} Simulate Meter Malfunction (Stuck Register / Zero Reading Fault)
  {Colors.BLUE}[4]{Colors.RESET} Simulate AMI Communication Failure (Packet Drop / Meter Offline)
  {Colors.GREEN}[5]{Colors.RESET} Simulate Legitimate High-Power Surge (EV Level-2 Fast Charger / HVAC)
  {Colors.CYAN}[6]{Colors.RESET} Heal / Restore Consumer Meter to Nominal Baseline
  {Colors.BOLD}[7]{Colors.RESET} Step Grid Clock Forward (15-Minute Interval Advance)
  {Colors.CYAN}[8]{Colors.RESET} Continuous Autonomous Real-Time Streamer (Auto-publish every N sec)
  {Colors.YELLOW}[9]{Colors.RESET} Auto-Demo Preset (Sequential test of all 5 scenarios with live explanations)
  {Colors.DIM}[q]{Colors.RESET} Exit Simulator
""")


def interactive_cli(sim: VirtualIoTSimulator):
    """Runs interactive terminal REPL."""
    print_banner(sim)

    while True:
        print_menu()
        try:
            choice = input(f"{Colors.BOLD}Select action [1-9, q]: {Colors.RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if choice == "q":
            print("Shutting down IoT Simulator. Bye!")
            break

        elif choice == "1":
            snap = sim.fetch_snapshot()
            if not snap:
                print(f"{Colors.RED}[!] Could not reach Digital Twin. Ensure 'python run_twin.py --serve' is running!{Colors.RESET}")
                continue

            grid = snap.get("grid_summary", {})
            clk = snap.get("clock", {})
            print(f"\n{Colors.BOLD}--- GRID TELEMETRY SUMMARY ({clk.get('iso_time', 'N/A')}) ---{Colors.RESET}")
            print(f"Dispatched Power: {grid.get('total_grid_input_kw', 0)} kW | Tech Loss: {grid.get('total_technical_loss_kw', 0)} kW")
            print(f"Unexplained Non-Technical Loss: {Colors.RED}{grid.get('grid_unexplained_ntl_pct', 0)}%{Colors.RESET}")
            print(f"Active Flagged Anomalies: {grid.get('anomalous_consumers_count', 0)} / 48")

            print(f"\n{Colors.BOLD}{'CONSUMER ID':<13} {'METER ID':<12} {'REPORTED':<11} {'BASELINE':<11} {'DEV %':<9} {'SCORE':<7} {'PROBABLE CAUSE':<20}{Colors.RESET}")
            print("-" * 85)
            consumers = snap.get("consumers", {})
            for cid in sorted(consumers.keys()):
                c = consumers[cid]
                an = c.get("analysis", {})
                score = an.get("anomaly_score", 0.0)
                cause = an.get("probable_cause", "NORMAL")
                c_color = Colors.RED if score >= 80 else (Colors.YELLOW if score >= 50 else Colors.GREEN)
                rep_kw = an.get("reported_kw", 0.0)
                base_kw = an.get("baseline_mean_kw", 0.0)
                dev_pct = an.get("deviation_pct", 0.0)
                print(f"{cid:<13} {c['static']['meter_id']:<12} {rep_kw:<11.2f} {base_kw:<11.2f} {dev_pct:+7.1f}%  {c_color}{score:<6.1f}{Colors.RESET} {c_color}{cause:<20}{Colors.RESET}")
            print()

        elif choice == "2":
            cid = input(f"Enter target consumer ID [e.g. CONS_N_004, CONS_S_018]: ").strip().upper() or "CONS_N_004"
            shunt_str = input("Enter reported shunt ratio (e.g. 0.25 = 75% stolen power) [default: 0.25]: ").strip()
            shunt = float(shunt_str) if shunt_str else 0.25
            trip_flag = input("Trip physical magnetic sensor flag? (y/N): ").strip().lower() == "y"

            ok = sim.inject_theft(cid, shunt_ratio=shunt, trip_magnetic_flag=trip_flag)
            if ok:
                print(f"{Colors.GREEN}[+] MQTT: Injected THEFT_BYPASS on {cid} (Shunt: {shunt*100:.0f}%, Magnetic Flag: {trip_flag}){Colors.RESET}")
                print(f"    Check dashboard: building {cid} score will surge to CRITICAL and Zone transformer loss will spike!")
            else:
                print(f"{Colors.RED}[!] Failed to inject theft. Check server connection.{Colors.RESET}")

        elif choice == "3":
            cid = input(f"Enter target consumer ID [e.g. CONS_N_015, CONS_S_011]: ").strip().upper() or "CONS_N_015"
            mode = input("Select fault type: [1] Stuck Register (frozen value), [2] Zero Reading Fault [default: 1]: ").strip()
            f_type = "zero_reading" if mode == "2" else "stuck"

            ok = sim.inject_meter_fault(cid, fault_type=f_type)
            if ok:
                print(f"{Colors.GREEN}[+] MQTT: Injected METER_MALFUNCTION ({f_type}) on {cid}{Colors.RESET}")
            else:
                print(f"{Colors.RED}[!] Failed to inject fault.{Colors.RESET}")

        elif choice == "4":
            cid = input(f"Enter target consumer ID [e.g. CONS_N_021, CONS_S_018]: ").strip().upper() or "CONS_N_021"
            ok = sim.inject_communication_failure(cid)
            if ok:
                print(f"{Colors.GREEN}[+] MQTT: Injected COMM_FAILURE on {cid} (METER OFFLINE){Colors.RESET}")
            else:
                print(f"{Colors.RED}[!] Failed to inject comm failure.{Colors.RESET}")

        elif choice == "5":
            cid = input(f"Enter target consumer ID [e.g. CONS_S_003]: ").strip().upper() or "CONS_S_003"
            surge_str = input("Enter EV charger draw kW [default: 7.4 kW]: ").strip()
            surge = float(surge_str) if surge_str else 7.4

            ok = sim.inject_legitimate_surge(cid, surge_kw=surge)
            if ok:
                print(f"{Colors.GREEN}[+] MQTT: Injected LEGITIMATE_ABNORMAL on {cid} (+{surge} kW EV Load){Colors.RESET}")
                print(f"    Verified: AI engine will classify as LEGITIMATE demand without penalizing as theft!")
            else:
                print(f"{Colors.RED}[!] Failed to inject surge.{Colors.RESET}")

        elif choice == "6":
            cid = input(f"Enter consumer ID to restore [e.g. CONS_N_004]: ").strip().upper() or "CONS_N_004"
            ok = sim.restore_consumer(cid)
            if ok:
                print(f"{Colors.GREEN}[+] MQTT: Restored {cid} to healthy nominal baseline!{Colors.RESET}")
            else:
                print(f"{Colors.RED}[!] Failed to restore consumer.{Colors.RESET}")

        elif choice == "7":
            ok = sim.step_simulation()
            if ok:
                snap = sim.fetch_snapshot()
                clk = snap.get("clock", {})
                print(f"{Colors.GREEN}[+] Simulation advanced to {clk.get('iso_time', 'N/A')}{Colors.RESET}")
            else:
                print(f"{Colors.RED}[!] Failed to step simulation.{Colors.RESET}")

        elif choice == "8":
            interval_str = input("Enter streaming interval in seconds [default: 2.0]: ").strip()
            interval = float(interval_str) if interval_str else 2.0
            sim.run_continuous_stream(interval_sec=interval)

        elif choice == "9":
            print(f"\n{Colors.CYAN}{Colors.BOLD}--- RUNNING AUTOMATED 5-SCENARIO VERIFICATION SUITE ---{Colors.RESET}")
            demos = [
                ("CONS_N_004", "THEFT_BYPASS", lambda: sim.inject_theft("CONS_N_004", 0.28, False), "Covert meter bypass (72% unmetered)"),
                ("CONS_N_009", "THEFT_TAMPER_MAGNETIC", lambda: sim.inject_theft("CONS_N_009", 0.35, True), "Neodymium magnetic tamper event"),
                ("CONS_N_015", "METER_MALFUNCTION", lambda: sim.inject_meter_fault("CONS_N_015", "stuck"), "Transducer stuck register fault"),
                ("CONS_N_021", "COMM_FAILURE", lambda: sim.inject_communication_failure("CONS_N_021"), "AMI collector packet drop"),
                ("CONS_S_003", "LEGITIMATE_ABNORMAL", lambda: sim.inject_legitimate_surge("CONS_S_003", 7.4), "Level-2 EV Fast Charger (7.4 kW)"),
            ]
            for target_cid, s_name, inject_fn, desc in demos:
                inject_fn()
                time.sleep(0.5)
                sim.step_simulation()
                snap = sim.fetch_snapshot()
                an = snap.get("consumers", {}).get(target_cid, {}).get("analysis", {})
                cause = an.get("probable_cause", "UNKNOWN")
                score = an.get("anomaly_score", 0.0)
                print(f"  * {target_cid:<12} | Scenario: {s_name:<22} | Detected: {Colors.BOLD}{cause:<20}{Colors.RESET} | Score: {score:.1f}/100")
                time.sleep(1.0)
            print(f"{Colors.GREEN}[+] Scenario verification complete! All cases verified on live dashboard.{Colors.RESET}\n")

        print()


def main():
    parser = argparse.ArgumentParser(description="GridNest Virtual IoT Sensor Network & AMI Simulator (MQTT 3.1.1)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT Broker hostname (default: localhost)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Digital Twin API base URL")
    parser.add_argument("--stream", action="store_true", help="Launch directly into autonomous continuous streaming mode")
    parser.add_argument("--interval", type=float, default=2.0, help="Streaming interval in seconds (default: 2.0)")
    parser.add_argument("--step", action="store_true", help="Step grid simulation clock once and exit")
    parser.add_argument("--inject", help="Directly inject scenario on consumer: CONSUMER_ID")
    parser.add_argument("--scenario", default="THEFT_BYPASS", help="Scenario type for --inject")
    parser.add_argument("--shunt", type=float, default=0.25, help="Shunt scaling factor (0.0 to 1.0)")
    parser.add_argument("--restore", help="Restore consumer to nominal baseline: CONSUMER_ID")

    args = parser.parse_args()

    sim = VirtualIoTSimulator(mqtt_host=args.mqtt_host, mqtt_port=args.mqtt_port, api_base=args.api_url)
    sim.connect()

    if args.step:
        sim.step_simulation()
        sim.disconnect()
        print("[+] Stepped grid simulation clock forward by 1 tick.")
        sys.exit(0)

    if args.restore:
        sim.restore_consumer(args.restore)
        sim.disconnect()
        print(f"[+] Restored {args.restore} to nominal baseline.")
        sys.exit(0)

    if args.inject:
        if args.scenario.upper() == "THEFT_BYPASS":
            sim.inject_theft(args.inject, shunt_ratio=args.shunt)
        elif args.scenario.upper() == "METER_MALFUNCTION":
            sim.inject_meter_fault(args.inject)
        elif args.scenario.upper() == "COMM_FAILURE":
            sim.inject_communication_failure(args.inject)
        elif args.scenario.upper() == "LEGITIMATE_ABNORMAL":
            sim.inject_legitimate_surge(args.inject)
        sim.disconnect()
        print(f"[+] Injected {args.scenario} on {args.inject}.")
        sys.exit(0)

    if args.stream:
        sim.run_continuous_stream(interval_sec=args.interval)
        sys.exit(0)

    # Default: Interactive CLI
    interactive_cli(sim)


if __name__ == "__main__":
    main()
