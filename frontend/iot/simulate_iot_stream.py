"""
GridNest IoT Packet Simulator & Stress Tester.
Pushes realistic ESP32 telemetry packets either directly to GridNest Digital Twin (:8000)
or to the Mock Adafruit IO Broker (:8002).
"""
import sys
import time
import json
import random
import argparse
import requests

TWIN_URL = "http://localhost:8000/api/iot/telemetry"
MOCK_AIO_URL = "http://localhost:8002/api/v2/demo/feeds/energy-telemetry/data"


def generate_packet(scenario: str, step: int = 0) -> dict:
    noise_v = random.uniform(-0.03, 0.03)
    noise_c = random.uniform(-6.0, 6.0)

    if scenario == "theft":
        # Wire tap diverting ~60% of power
        trans_v = round(4.65 + noise_v, 2)
        trans_c = round(640.0 + noise_c, 1)
        trans_w = round(trans_v * (trans_c / 1000.0), 2)

        cons_v = round(4.08 + noise_v, 2)
        cons_c = round(280.0 + noise_c, 1)
        cons_w = round(cons_v * (cons_c / 1000.0), 2)

        loss_w = round(max(0.0, trans_w - cons_w), 2)
        loss_wh = round(loss_w * (step * 2.0 / 3600.0) + 0.0050, 4)
    elif scenario == "sag":
        # Voltage drop under heavy resistive load
        trans_v = round(4.15 + noise_v, 2)
        trans_c = round(770.0 + noise_c, 1)
        trans_w = round(trans_v * (trans_c / 1000.0), 2)

        cons_v = round(3.68 + noise_v, 2)
        cons_c = round(750.0 + noise_c, 1)
        cons_w = round(cons_v * (cons_c / 1000.0), 2)

        loss_w = round(max(0.0, trans_w - cons_w), 2)
        loss_wh = round(loss_w * (step * 2.0 / 3600.0) + 0.0020, 4)
    else:
        # Balanced normal flow
        trans_v = round(4.50 + noise_v, 2)
        trans_c = round(462.0 + noise_c, 1)
        trans_w = round(trans_v * (trans_c / 1000.0), 2)

        cons_v = round(4.36 + noise_v, 2)
        cons_c = round(470.0 + noise_c, 1)
        cons_w = round(cons_v * (cons_c / 1000.0), 2)

        loss_w = round(max(0.01, trans_w - cons_w), 2)
        loss_wh = round(loss_w * (step * 2.0 / 3600.0), 4)

    return {
        "transVoltage": trans_v,
        "transCurrent": trans_c,
        "transPower_W": trans_w,
        "transEnergy_Wh": round(0.0150 + (step * 0.0002), 4),
        "consVoltage": cons_v,
        "consCurrent": cons_c,
        "consPower_W": cons_w,
        "consEnergy_Wh": round(0.0145 + (step * 0.0002), 4),
        "powerLoss_W": loss_w,
        "energyLoss_Wh": loss_wh,
        "target_consumer_id": "CONS_S_001",
        "target_transformer_id": "TX_102",
    }


def send_telemetry(payload: dict, target: str):
    if target == "mock":
        # Send in Adafruit IO format: {"value": json_string}
        url = MOCK_AIO_URL
        body = {"value": json.dumps(payload)}
    else:
        url = TWIN_URL
        body = payload

    try:
        resp = requests.post(url, json=body, timeout=2.0)
        return resp.status_code == 200, resp.text
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="GridNest IoT Packet Simulator")
    parser.add_argument("--scenario", choices=["normal", "theft", "sag"], default="normal", help="Test scenario")
    parser.add_argument("--target", choices=["twin", "mock"], default="twin", help="Target API: 'twin' (:8000) or 'mock' (:8002)")
    parser.add_argument("--stream", action="store_true", help="Stream packets continuously every 1.5s")
    parser.add_argument("--interval", type=float, default=1.5, help="Streaming interval in seconds")
    args = parser.parse_args()

    print("\n=======================================================")
    print(f" ⚡ GRIDNEST IOT PACKET SIMULATOR")
    print(f" Scenario:  {args.scenario.upper()}")
    print(f" Target:    {'GridNest Digital Twin (:8000)' if args.target == 'twin' else 'Mock Adafruit IO Broker (:8002)'}")
    print(f" Mode:      {'Continuous Stream' if args.stream else 'Single Shot'}")
    print("=======================================================\n")

    step = 0
    try:
        while True:
            payload = generate_packet(args.scenario, step)
            success, msg = send_telemetry(payload, args.target)

            loss_pct = (payload['powerLoss_W'] / max(0.01, payload['transPower_W'])) * 100.0
            status_icon = "🔴 [THEFT DETECTED]" if payload['powerLoss_W'] > 0.25 else "🟢 [BALANCED]"

            print(f"[{time.strftime('%H:%M:%S')}] {status_icon} Tx: {payload['transPower_W']}W | Cons: {payload['consPower_W']}W | Loss: {payload['powerLoss_W']}W ({loss_pct:.1f}%) -> HTTP {'OK' if success else 'FAIL'}")

            if not args.stream:
                break

            step += 1
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nSimulator stopped.")


if __name__ == "__main__":
    main()
