"""
GridNest IoT Serial Bridge — ESP32 to 3D Digital Twin.
Reads live physical sensor telemetry directly from ESP32 on USB Serial (e.g. COM7),
parses Transformer and Consumer measurements, and streams them into GridNest Digital Twin (Zone B).
"""
import sys
import time
import re
import argparse
import requests

DEFAULT_SERVER_URL = "http://localhost:8000/api/iot/telemetry"

# Regex patterns matching the exact Serial.println format from the Arduino code
RE_TRANS = re.compile(
    r"Transformer\s*->\s*([\d\.]+)V\s*\|\s*([\d\.]+)mA\s*\|\s*([\d\.]+)W\s*\|\s*([\d\.]+)Wh",
    re.IGNORECASE
)
RE_CONS = re.compile(
    r"Consumer\s*->\s*([\d\.]+)V\s*\|\s*([\d\.]+)mA\s*\|\s*([\d\.]+)W\s*\|\s*([\d\.]+)Wh",
    re.IGNORECASE
)
RE_LOSS = re.compile(
    r"SYSTEM LOSS\s*->\s*Power Loss:\s*([\d\.]+)W\s*\|\s*Cumulative Energy Loss:\s*([\d\.]+)Wh",
    re.IGNORECASE
)


def find_esp32_port() -> str | None:
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        # 1. Prefer typical USB-to-UART bridges (CP210x, CH340, FTDI, ESP32)
        for p in ports:
            p_desc = (p.description or "").lower()
            p_dev = p.device.lower()
            if any(k in p_desc or k in p_dev for k in ["usb", "uart", "cp210", "ch340", "ftdi", "wch"]):
                return p.device
        # 2. Fallback to any non-bluetooth port
        for p in ports:
            if "bluetooth" not in p.device.lower():
                return p.device
    except Exception:
        pass
    return None


def run_serial_bridge(port: str = "auto", baudrate: int = 115200, server_url: str = DEFAULT_SERVER_URL):
    try:
        import serial
    except ImportError:
        print("[!] 'pyserial' not installed. Install with: pip install pyserial")
        sys.exit(1)

    if port == "auto" or not port:
        detected = find_esp32_port()
        if detected:
            print(f"[*] Auto-detected ESP32 serial port: {detected}")
            port = detected
        else:
            default_fallback = "COM7" if sys.platform.startswith("win") else "/dev/cu.usbserial-0001"
            print(f"[!] No active USB serial port found. Falling back to default: {default_fallback}")
            port = default_fallback

    print("\n=======================================================")
    print(f" 🔌 GRIDNEST LIVE IOT HARDWARE SERIAL BRIDGE")
    print(f" Port:       {port}")
    print(f" Baudrate:   {baudrate}")
    print(f" Target URL: {server_url}")
    print(f" Target:     Zone B -> Transformer TX_102 | Consumer CONS_S_001")
    print("=======================================================\n")

    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=2.0)
        time.sleep(2.0)  # Wait for serial reset
        print(f"[+] Serial port {port} opened successfully! Listening for ESP32 packets...\n")
    except Exception as e:
        print(f"[!] Failed to open serial port {port}: {e}")
        print("[*] Tip: Check Device Manager (Windows) or 'ls /dev/cu.*' (Mac) to confirm port name.")
        sys.exit(1)

    current_data = {}

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            # Print raw line for debugging
            print(f"[ESP32] {line}")

            # Check for Transformer line
            m_trans = RE_TRANS.search(line)
            if m_trans:
                current_data["transVoltage"] = float(m_trans.group(1))
                current_data["transCurrent"] = float(m_trans.group(2))
                current_data["transPower_W"] = float(m_trans.group(3))
                current_data["transEnergy_Wh"] = float(m_trans.group(4))

            # Check for Consumer line
            m_cons = RE_CONS.search(line)
            if m_cons:
                current_data["consVoltage"] = float(m_cons.group(1))
                current_data["consCurrent"] = float(m_cons.group(2))
                current_data["consPower_W"] = float(m_cons.group(3))
                current_data["consEnergy_Wh"] = float(m_cons.group(4))

            # Check for Loss line
            m_loss = RE_LOSS.search(line)
            if m_loss:
                current_data["powerLoss_W"] = float(m_loss.group(1))
                current_data["energyLoss_Wh"] = float(m_loss.group(2))

                # When full packet received, post to GridNest Digital Twin
                if "transVoltage" in current_data and "consVoltage" in current_data:
                    current_data["target_consumer_id"] = "CONS_S_001"
                    current_data["target_transformer_id"] = "TX_102"

                    try:
                        resp = requests.post(server_url, json=current_data, timeout=2.0)
                        if resp.status_code == 200:
                            is_theft = current_data["powerLoss_W"] > 0.25
                            theft_tag = "🔴 [PHYSICAL THEFT / LINE TAP!]" if is_theft else "🟢 [HEALTHY]"
                            print(f"[-->] Synced with 3D Twin: TX={current_data['transPower_W']}W, CONS={current_data['consPower_W']}W, LOSS={current_data['powerLoss_W']}W {theft_tag}")
                    except Exception as err:
                        print(f"[!] Warning: Could not reach GridNest server at {server_url}: {err}")

        except KeyboardInterrupt:
            print("\n[*] Stopping serial bridge...")
            ser.close()
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GridNest ESP32 Serial to Digital Twin Bridge")
    parser.add_argument("--port", type=str, default="auto", help="Serial port ('auto' to auto-detect, 'COM7' on Windows, or '/dev/cu.usbserial*' on Mac)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default 115200)")
    parser.add_argument("--url", type=str, default=DEFAULT_SERVER_URL, help="GridNest API URL")
    args = parser.parse_args()

    run_serial_bridge(port=args.port, baudrate=args.baud, server_url=args.url)
