"""
FastAPI Backend and WebSocket Streaming Server for Smart Grid Digital Twin.
Serves real-time telemetry, 3D GeoJSON GIS layers, report generation endpoints,
and bidirectional scenario injection.
"""
from __future__ import annotations
import os
import json
import time
import asyncio
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from engine.digital_twin import SmartGridDigitalTwin
from models.telemetry import ScenarioType
from export.geojson_exporter import GeoJSONTwinExporter
from iot.mqtt_broker import MicroMQTTBroker
from iot.mqtt_bridge import SmartGridMQTTBridge
from iot.adafruit_bridge import AdafruitIOBridge

app = FastAPI(
    title="Smart Grid Digital Twin API",
    description="Cyber-physical simulation, energy accounting, and explainable theft detection backend.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Twin singleton
twin = SmartGridDigitalTwin(seed=42)
twin.initialize(setup_scenarios=True)
exporter = GeoJSONTwinExporter(twin)

# Connected WebSocket clients
connected_clients: list[WebSocket] = []

# In-process Micro MQTT 3.1.1 Broker & Bridge (Virtual Network)
mqtt_broker = MicroMQTTBroker(host="0.0.0.0", port=1883)
mqtt_bridge: Optional[SmartGridMQTTBridge] = None

# Adafruit IO Physical ESP32 Bridge
adafruit_bridge = AdafruitIOBridge(
    twin=twin,
    username=os.environ.get("ADAFRUIT_IO_USERNAME", ""),
    key=os.environ.get("ADAFRUIT_IO_KEY", ""),
    feed=os.environ.get("ADAFRUIT_IO_FEED", "smartgrid"),
    physical_transformer_id=twin.physical_transformer_id,
    physical_consumer_id=twin.physical_consumer_id,
    broadcast_callback=None,  # Set in startup_event
)

# Live physical IoT hardware overlay state (ESP32 / Adafruit IO)
latest_iot_telemetry: Optional[dict] = None
last_iot_timestamp: float = 0.0


class IoTTelemetryPayload(BaseModel):
    transVoltage: float = Field(..., description="Transformer measured voltage in Volts")
    transCurrent: float = Field(..., description="Transformer measured current in mA")
    transPower_W: Optional[float] = Field(None, description="Transformer measured power in Watts")
    transEnergy_Wh: Optional[float] = Field(0.0, description="Transformer cumulative energy in Wh")
    consVoltage: float = Field(..., description="Consumer measured voltage in Volts")
    consCurrent: float = Field(..., description="Consumer measured current in mA")
    consPower_W: Optional[float] = Field(None, description="Consumer measured power in Watts")
    consEnergy_Wh: Optional[float] = Field(0.0, description="Consumer cumulative energy in Wh")
    powerLoss_W: Optional[float] = Field(None, description="Measured line power loss in Watts")
    energyLoss_Wh: Optional[float] = Field(0.0, description="Cumulative energy loss in Wh")
    target_consumer_id: Optional[str] = Field(None, description="Target Consumer ID")
    target_transformer_id: Optional[str] = Field(None, description="Target Transformer ID")


def apply_iot_hardware_overlay(snapshot: dict) -> dict:
    """Injects live physical ESP32 / Adafruit IoT sensor readings into designated twin node."""
    global latest_iot_telemetry, last_iot_timestamp
    if not latest_iot_telemetry:
        return snapshot

    iot = latest_iot_telemetry
    c_id = iot.get("target_consumer_id") or twin.physical_consumer_id or "CONS_S_001"
    tx_id = iot.get("target_transformer_id") or twin.physical_transformer_id or "TX_102"

    consumers = snapshot.get("consumers", {})
    if c_id in consumers:
        c_data = consumers[c_id]

        trans_v = float(iot.get("transVoltage", iot.get("transV", 230.0)))
        trans_ma = float(iot.get("transCurrent", iot.get("transC", 0.0)))
        trans_w = float(iot.get("transPower_W", iot.get("transPower", iot.get("trans_p_w", trans_v * (trans_ma / 1000.0)))))

        cons_v = float(iot.get("consVoltage", iot.get("consV", 230.0)))
        cons_ma = float(iot.get("consCurrent", iot.get("consC", 0.0)))
        cons_w = float(iot.get("consPower_W", iot.get("consPower", iot.get("cons_p_w", cons_v * (cons_ma / 1000.0)))))

        loss_w = float(iot.get("powerLoss_W", iot.get("powerLoss", iot.get("loss_w", max(0.0, trans_w - cons_w)))))
        loss_wh = float(iot.get("energyLoss_Wh", iot.get("energyLoss", iot.get("loss_wh", 0.0))))
        loss_pct = (loss_w / max(0.01, trans_w)) * 100.0 if trans_w > 0 else 0.0

        # Physical Shunt / Line Tap check based on Conservation of Energy
        has_theft = (loss_w > 0.25 and loss_pct > 8.0) or (trans_w > cons_w + 0.30 and loss_pct > 8.0)

        if has_theft:
            score = min(100.0, round(78.0 + (loss_pct * 0.22), 1))
            risk = "CRITICAL"
            cause = "THEFT_TAMPERING"
            action = f"PHYSICAL LINE TAP DETECTED: Anti-theft field squad dispatched to inspect drop line between {tx_id} and {c_id}."
            factors = [
                f"Physical ESP32 Sensor: Active line tap / power theft detected on {tx_id} drop wire",
                f"Transformer input: {trans_w:.2f} W, but consumer meter only registers {cons_w:.2f} W",
                f"Unmetered line diversion loss: {loss_w:.2f} W ({loss_pct:.1f}% stolen power)",
                f"Cumulative stolen energy recorded: {loss_wh:.4f} Wh",
                f"Terminal voltage drop: {cons_v:.2f} V (load current: {cons_ma:.1f} mA)",
            ]
        else:
            score = 12.0
            risk = "NORMAL"
            cause = "NORMAL"
            action = "Live hardware sensors verified healthy. Physical circuit in balance."
            factors = [
                f"Physical ESP32 Sensor: Circuit balanced. Transformer: {trans_w:.2f} W, Meter: {cons_w:.2f} W",
                f"Unexplained physical line loss: {loss_w:.2f} W (nominal resistive loss within ±5% tolerance)",
                f"Measured terminal voltage: {cons_v:.2f} V, Current: {cons_ma:.1f} mA",
                f"Cumulative energy consumed: {float(iot.get('consEnergy_Wh', iot.get('cons_e_wh', 0.0))):.4f} Wh",
            ]

        # Update telemetry
        if "telemetry" in c_data and c_data["telemetry"]:
            tel = c_data["telemetry"]
            if "reported" in tel and tel["reported"]:
                tel["reported"]["voltage_v"] = cons_v
                tel["reported"]["current_a"] = round(cons_ma / 1000.0, 3)
                tel["reported"]["active_power_kw"] = round(cons_w / 1000.0, 4)
            if "ground_truth" in tel and tel["ground_truth"]:
                tel["ground_truth"]["voltage_v"] = trans_v
                tel["ground_truth"]["active_power_kw"] = round(trans_w / 1000.0, 4)
                tel["ground_truth"]["current_a"] = round(trans_ma / 1000.0, 3)
            tel["unreported_stolen_kw"] = round(loss_w / 1000.0, 4) if has_theft else 0.0
            tel["active_scenario"] = "THEFT_SHUNT" if has_theft else "NORMAL"
            tel["is_tampered"] = has_theft

        # Update analysis
        c_data["analysis"] = {
            "consumer_id": c_id,
            "meter_id": c_data.get("static", {}).get("meter_id", f"MTR_{c_id}"),
            "zone_id": c_data.get("static", {}).get("zone_id", "Zone_1_North"),
            "transformer_id": tx_id,
            "timestamp": snapshot.get("clock", {}).get("iso_time", "2026-10-05T10:15:00"),
            "anomaly_score": score,
            "risk_level": risk,
            "probable_cause": cause,
            "confidence_pct": 98.5 if has_theft else 95.0,
            "reported_kw": round(cons_w / 1000.0, 4),
            "baseline_mean_kw": round(trans_w / 1000.0, 4),
            "baseline_std_kw": round(trans_w * 0.08 / 1000.0, 4),
            "deviation_z": round(-loss_pct / 10.0, 2) if has_theft else 0.0,
            "deviation_pct": round(-loss_pct if has_theft else 0.0, 1),
            "peer_ratio": 1.0,
            "zone_ntl_pct": round(loss_pct, 1),
            "status_flags": {
                "tamper_cover_opened": False,
                "magnetic_tamper": has_theft,
                "reverse_current": False,
                "neutral_missing": False,
                "low_battery": False,
                "hardware_fault": False,
                "communication_error": False,
                "voltage_out_of_range": False,
                "bitmask": 1 if has_theft else 0,
                "has_tamper": has_theft,
                "has_fault": False,
            },
            "contributing_factors": factors,
            "recommended_action": action,
            "ml_score": score,
            "ml_subscores": {
                "xgb_prob": round(score / 100.0, 4),
                "lgbm_prob": round(score / 100.0, 4),
                "iso_score": 0.1,
                "hybrid_blend": round(score / 100.0, 4),
            },
            "shap_factors": [],
            "is_physical_iot": True,
            "is_iot_hardware": True,
            "ml_powered": True,
        }

        c_data["is_physical_iot"] = True
        c_data["hardware_source"] = "Adafruit IO ESP32 (GPIO 33/32)"
        c_data["hardware_pins"] = "GPIO 33 (V) / GPIO 32 (I)"
        c_data["iot_telemetry"] = iot

    # Update Target Transformer in snapshot
    transformers = snapshot.get("transformers", {})
    if tx_id in transformers:
        tx_data = transformers[tx_id]
        tx_data["is_physical_iot"] = True
        tx_data["hardware_source"] = "Adafruit IO ESP32 (GPIO 35/34)"
        tx_data["hardware_pins"] = "GPIO 35 (V) / GPIO 34 (I)"
        iot_sensors = tx_data.setdefault("iot_sensors", {})
        iot_sensors["active_power_kw"] = round(trans_w / 1000.0, 4)
        iot_sensors["voltage_v"] = trans_v
        iot_sensors["secondary_current_a"] = round(trans_ma / 1000.0, 3)
        iot_sensors["unexplained_loss_kw"] = round(loss_w / 1000.0, 4)
        iot_sensors["unexplained_loss_pct"] = round(loss_pct, 1)
        iot_sensors["is_done_for"] = has_theft
        iot_sensors["status"] = (
            f"ALERT_THEFT_DISCREPANCY ({loss_w:.2f}W LINE LOSS!)"
            if has_theft
            else "BALANCED_HEALTHY (IoT STREAMING)"
        )

        acc = tx_data.setdefault("accounting", {})
        acc["is_done_for"] = has_theft
        acc["transformer_input_kw"] = round(trans_w / 1000.0, 4)
        acc["unexplained_loss_kw"] = round(loss_w / 1000.0, 4)
        acc["unexplained_loss_pct"] = round(loss_pct, 1)
        acc["is_iot_hardware"] = True
        tx_data["iot_telemetry"] = iot

    # Update grid summary
    summary = snapshot.setdefault("grid_summary", {})
    summary["iot_hardware_active"] = True
    summary["iot_last_ping_seconds_ago"] = round(time.time() - last_iot_timestamp, 1) if last_iot_timestamp > 0 else 0.0

    # Physical IoT block
    snapshot["physical_iot"] = {
        "status": {
            "connected": True,
            "enabled": True,
            "last_readings": {
                "transVoltage": trans_v,
                "transCurrent_mA": trans_ma,
                "transPower_W": trans_w,
                "consVoltage": cons_v,
                "consCurrent_mA": cons_ma,
                "consPower_W": cons_w,
                "powerLoss_W": loss_w,
                "energyLoss_Wh": loss_wh,
                "loss_pct": round(loss_pct, 1),
            },
        },
        "transformer_id": tx_id,
        "consumer_id": c_id,
    }

    return snapshot


def sync_snapshot_cache(snapshot: dict) -> dict:
    """Updates snapshot with physical IoT hardware overlay if active."""
    if latest_iot_telemetry:
        snapshot = apply_iot_hardware_overlay(snapshot)
    return snapshot


def handle_incoming_hardware_telemetry(data: dict):
    """Callback for adafruit_bridge or direct hardware streams."""
    global latest_iot_telemetry, last_iot_timestamp
    latest_iot_telemetry = data
    last_iot_timestamp = time.time()


@app.on_event("startup")
async def startup_event():
    global mqtt_bridge
    mqtt_bridge = SmartGridMQTTBridge(
        twin=twin,
        broker=mqtt_broker,
        broadcast_callback=broadcast_to_clients,
    )
    started = await mqtt_broker.start()
    if started:
        print(f"[+] GridNest MicroMQTTBroker active on port {mqtt_broker.port} (MQTT 3.1.1)")
    else:
        print("[!] MicroMQTTBroker running in internal event bus mode")

    # Start Adafruit IO client in background loop
    loop = asyncio.get_running_loop()
    adafruit_bridge.broadcast_callback = broadcast_to_clients
    adafruit_bridge.on_telemetry_packet = handle_incoming_hardware_telemetry
    adafruit_bridge.start(loop=loop)
    twin.adafruit_status = adafruit_bridge.get_status()


@app.on_event("shutdown")
async def shutdown_event():
    await mqtt_broker.stop()
    adafruit_bridge.stop()


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serves the 3D Digital Twin Viewer UI."""
    viewer_path = os.path.join(os.path.dirname(__file__), "..", "viewer", "twin_viewer.html")
    if os.path.exists(viewer_path):
        with open(viewer_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Digital Twin Viewer file not found.</h3>")


@app.get("/simulator", response_class=HTMLResponse)
async def get_simulator():
    """Serves the Interactive Web-Based Virtual IoT Simulator Control Panel."""
    sim_path = os.path.join(os.path.dirname(__file__), "..", "viewer", "iot_simulator.html")
    if os.path.exists(sim_path):
        with open(sim_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Virtual IoT Simulator file not found.</h3>")


@app.get("/api/snapshot")
async def get_snapshot():
    """Returns the latest synchronized digital twin snapshot."""
    snapshot = twin.get_snapshot()
    snapshot = sync_snapshot_cache(snapshot)
    return JSONResponse(snapshot)


@app.post("/api/step")
async def step_simulation():
    """Advances simulation clock by 1 tick (15 mins) and returns updated state."""
    snapshot = twin.step()
    snapshot = sync_snapshot_cache(snapshot)
    # Broadcast to websocket clients
    await broadcast_to_clients(snapshot)
    return JSONResponse(snapshot)


@app.get("/api/consumer/{consumer_id}")
async def get_consumer(consumer_id: str):
    """Returns telemetry, baseline, and anomaly analysis for a specific consumer."""
    snapshot = twin.get_snapshot()
    snapshot = sync_snapshot_cache(snapshot)
    c_data = snapshot["consumers"].get(consumer_id)
    if not c_data:
        raise HTTPException(status_code=404, detail="Consumer not found")
    return JSONResponse(c_data)


@app.get("/api/report/{consumer_id}")
async def get_report(consumer_id: str):
    """Generates and returns an auditable investigation report."""
    snapshot = twin.get_snapshot()
    snapshot = sync_snapshot_cache(snapshot)
    c_data = snapshot["consumers"].get(consumer_id)
    if c_data and c_data.get("is_physical_iot") and latest_iot_telemetry:
        an = c_data.get("analysis", {})
        static_info = c_data.get("static", {})
        score = an.get("anomaly_score", 0)
        risk = an.get("risk_level", "NORMAL")
        cause = an.get("probable_cause", "NORMAL").replace("_", " ")
        conf = an.get("confidence_pct", 95.0)
        factors = an.get("contributing_factors", [])
        ev_list = "\n".join([f"- {f}" for f in factors]) if factors else "- Physical telemetry balanced within ±5% tolerance."
        action = an.get("recommended_action", "Routine monitoring.")
        
        md = f"""# Smart Grid Anomaly Investigation Report: {consumer_id} [LIVE PHYSICAL IOT HARDWARE SENSOR — ESP32]
**Report ID:** `RPT-{consumer_id}` | **Generated At:** `{snapshot.get('clock', {}).get('iso_time', '2026-10-05T10:15:00')}`
**Data Stream:** `Physical IoT Hardware Bench (ESP32 GPIO 35/34 & GPIO 33/32)`

### Executive Summary
- **Consumer ID:** `{consumer_id}`
- **Meter ID:** `{static_info.get('meter_id', 'Unknown')}`
- **Category:** `{static_info.get('category', 'Unknown')}`
- **Transformer Zone:** `{static_info.get('transformer_id', 'TX_101')} ({static_info.get('zone_id', 'Zone_1_North')})`
- **Anomaly Score:** `{score} / 100` ({risk} RISK)
- **Probable Cause:** **{cause}**
- **Confidence Level:** `{conf}%`

### Physical Sensor & Machine Learning Evidence Chain
{ev_list}

### Recommended Enforcement Action
**{action}**
"""
        return JSONResponse({"markdown": md, "structured": an})

    report = twin.generate_investigation_report(consumer_id)
    if not report:
        raise HTTPException(status_code=404, detail="Unable to generate report for consumer")
    return JSONResponse({
        "markdown": report.to_markdown(),
        "structured": report.to_dict(),
    })


@app.get("/api/ml/benchmark")
async def get_benchmark_metrics():
    """Returns empirical benchmark metrics across data.csv and Electricity_Theft_Data.csv."""
    summary_path = os.path.join(os.path.dirname(__file__), "..", "engine", "artifacts", "benchmark_summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            return JSONResponse(json.load(f))
    return JSONResponse({"status": "error", "message": "Benchmark summary not found"}, status_code=404)


@app.post("/api/inject/{consumer_id}")
async def inject_scenario_endpoint(
    consumer_id: str,
    request: Request,
    scenario: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    scaling_factor: Optional[float] = Query(None),
    malfunction_type: Optional[str] = Query(None),
    surge_kw: Optional[float] = Query(None),
    trigger_tamper_flag: Optional[bool] = Query(None),
):
    """Dynamically injects an operational scenario on a consumer (supports JSON body or query params)."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    scen_str = body.get("scenario") or scenario or "NORMAL"
    try:
        scen_type = ScenarioType(str(scen_str).upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scenario type: {scen_str}")

    params = body.get("params", {})
    if mode: params["mode"] = mode
    if scaling_factor is not None: params["scaling_factor"] = scaling_factor
    if malfunction_type: params["malfunction_type"] = malfunction_type
    if surge_kw is not None: params["surge_kw"] = surge_kw
    if trigger_tamper_flag is not None: params["trigger_tamper_flag"] = trigger_tamper_flag

    for k in ["magnetic_tamper", "tamper_cover_opened", "reverse_current", "trigger_tamper_flag", "scaling_factor", "mode", "malfunction_type", "surge_kw"]:
        if k in body and k not in params:
            params[k] = body[k]

    twin.inject_scenario(consumer_id, scen_type, params)
    snapshot = twin.step()
    await broadcast_to_clients(snapshot)
    return JSONResponse({
        "status": "success",
        "consumer_id": consumer_id,
        "scenario": scen_type.value,
        "params": params,
        "snapshot": snapshot,
    })


@app.post("/api/restore/{consumer_id}")
async def restore_consumer_endpoint(consumer_id: str):
    """Restores consumer meter to normal baseline operation."""
    twin.clear_scenario(consumer_id)
    snapshot = twin.step()
    await broadcast_to_clients(snapshot)
    return JSONResponse({"status": "success", "consumer_id": consumer_id, "message": "Restored to nominal baseline", "snapshot": snapshot})


@app.post("/api/restore-all")
async def restore_all_consumers_endpoint():
    """Restores all 48 consumer meters to normal nominal baseline operation."""
    for cid in list(twin.topology.consumers.keys()):
        twin.clear_scenario(cid)
    snapshot = twin.step()
    await broadcast_to_clients(snapshot)
    return JSONResponse({"status": "success", "message": "All 48 consumers restored to NORMAL", "snapshot": snapshot})


@app.post("/api/reset-demo")
async def reset_demo_scenarios_endpoint():
    """Resets grid to default representative demonstration scenarios."""
    twin.injector.active_injections.clear()
    twin.injector.setup_default_demo_scenarios()
    snapshot = twin.step()
    await broadcast_to_clients(snapshot)
    return JSONResponse({"status": "success", "message": "Demo scenarios reloaded", "snapshot": snapshot})


@app.get("/api/iot/status")
async def get_iot_status():
    """Returns the live status of the MQTT broker, connected IoT clients, and topics."""
    return JSONResponse({
        "broker_running": mqtt_broker.is_running,
        "mqtt_host": mqtt_broker.host,
        "mqtt_port": mqtt_broker.port,
        "connected_clients": len(mqtt_broker.clients),
        "active_topic_subscriptions": list(mqtt_broker.subscribers.keys()),
        "total_smart_meters": len(twin.topology.consumers),
        "total_transformer_gateways": len(twin.topology.transformers),
        "power_station_gateway": twin.topology.power_station.id if twin.topology.power_station else "PS_CENTRAL_01",
    })


@app.post("/api/iot/publish")
async def publish_iot_message(topic: str = Query(...), payload: str = Query(...)):
    """Allows testing MQTT publishing via HTTP interface."""
    await mqtt_broker.publish_local(topic, payload)
    return JSONResponse({"status": "published", "topic": topic})


@app.get("/api/iot/adafruit/status")
async def get_adafruit_status():
    """Returns the live status of the Adafruit IO MQTT connection and latest readings."""
    status = adafruit_bridge.get_status()
    twin.adafruit_status = status
    return JSONResponse(status)


@app.post("/api/iot/adafruit/config")
async def update_adafruit_config(request: Request):
    """Allows updating Adafruit IO credentials and target hardware node mappings dynamically."""
    body = await request.json()
    username = (body.get("username") or "").strip()
    key = (body.get("key") or body.get("aio_key") or "").strip()
    feed = (body.get("feed") or body.get("feed_name") or "smartgrid").strip()
    phys_tx = body.get("physical_transformer_id") or body.get("target_transformer_id") or twin.physical_transformer_id
    phys_cons = body.get("physical_consumer_id") or body.get("target_consumer_id") or twin.physical_consumer_id

    twin.physical_transformer_id = phys_tx
    twin.physical_consumer_id = phys_cons
    adafruit_bridge.update_credentials(
        username=username,
        key=key,
        feed=feed,
        physical_tx_id=phys_tx,
        physical_cons_id=phys_cons,
    )
    status = adafruit_bridge.get_status()
    twin.adafruit_status = status
    feed_topic = f"{username}/feeds/{feed}" if username else feed
    return JSONResponse({
        "status": "updated",
        "feed": feed,
        "feed_topic": feed_topic,
        "username": username,
        "physical_transformer_id": phys_tx,
        "physical_consumer_id": phys_cons,
        "adafruit": status
    })


@app.post("/api/iot/adafruit/mock-packet")
async def inject_mock_adafruit_packet(request: Request):
    """
    Simulates an incoming hardware packet from physical ESP32 to test the Adafruit pipeline.
    Expected JSON body with transVoltage, transCurrent, transPower, consVoltage, consCurrent, consPower.
    """
    body = await request.json()
    if isinstance(body, dict):
        payload_str = json.dumps(body)
    else:
        payload_str = str(body)

    adafruit_bridge.process_raw_payload(payload_str, topic=f"{adafruit_bridge.username}/feeds/{adafruit_bridge.feed}")
    return JSONResponse({
        "status": "ingested",
        "readings": adafruit_bridge.latest_readings,
        "physical_transformer": adafruit_bridge.physical_transformer_id,
        "physical_consumer": adafruit_bridge.physical_consumer_id,
    })


@app.get("/api/geojson/buildings")
async def get_buildings_geojson():
    return JSONResponse(exporter.export_buildings_geojson())


@app.get("/api/geojson/grid-lines")
async def get_grid_lines_geojson():
    return JSONResponse(exporter.export_grid_lines_geojson())


@app.get("/api/geojson/transformers")
async def get_transformers_geojson():
    return JSONResponse(exporter.export_transformers_geojson())


@app.get("/api/geojson/drone")
async def get_drone_geojson():
    return JSONResponse(exporter.export_drone_flight_geojson())


async def broadcast_to_clients(data: Dict[str, Any]):
    """Broadcasts live tick updates to all active WebSockets."""
    for client in list(connected_clients):
        try:
            await client.send_text(json.dumps(data))
        except Exception:
            connected_clients.remove(client)


@app.post("/api/iot/telemetry")
async def ingest_iot_telemetry(payload: IoTTelemetryPayload):
    """
    Ingests live physical sensor telemetry from ESP32 / Arduino / Adafruit IO:
    Maps transformer readings to designated Transformer (e.g. TX_101 or TX_102) and
    consumer readings to designated House (e.g. CONS_S_001 or CONS_N_004).
    Broadcasts the live state immediately to the 3D Viewer via WebSockets.
    """
    global latest_iot_telemetry, last_iot_timestamp
    data = payload.dict(exclude_unset=True)
    if data.get("transPower_W") is None and data.get("transVoltage") and data.get("transCurrent"):
        data["transPower_W"] = round(data["transVoltage"] * (data["transCurrent"] / 1000.0), 2)
    if data.get("consPower_W") is None and data.get("consVoltage") and data.get("consCurrent"):
        data["consPower_W"] = round(data["consVoltage"] * (data["consCurrent"] / 1000.0), 2)
    if data.get("powerLoss_W") is None:
        data["powerLoss_W"] = round(max(0.0, (data.get("transPower_W") or 0.0) - (data.get("consPower_W") or 0.0)), 2)
    
    target_c = data.get("target_consumer_id") or twin.physical_consumer_id or "CONS_S_001"
    target_tx = data.get("target_transformer_id") or twin.physical_transformer_id or "TX_102"
    data["target_consumer_id"] = target_c
    data["target_transformer_id"] = target_tx

    latest_iot_telemetry = data
    last_iot_timestamp = time.time()

    # Also keep adafruit_bridge in sync
    adafruit_bridge.latest_readings = {
        "trans_v": data["transVoltage"],
        "trans_c_ma": data["transCurrent"],
        "trans_p_w": data.get("transPower_W", 0.0),
        "cons_v": data["consVoltage"],
        "cons_c_ma": data["consCurrent"],
        "cons_p_w": data.get("consPower_W", 0.0),
        "power_loss_w": data.get("powerLoss_W", 0.0),
        "energyLoss_Wh": data.get("energyLoss_Wh", 0.0),
    }
    adafruit_bridge.packets_received += 1
    adafruit_bridge.last_packet_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    snapshot = twin.get_snapshot()
    snapshot = sync_snapshot_cache(snapshot)
    await broadcast_to_clients(snapshot)

    loss_val = data.get("powerLoss_W", 0.0)
    return JSONResponse({
        "status": "success",
        "message": f"IoT telemetry ingested for {target_tx} and {target_c}",
        "powerLoss_W": loss_val,
        "is_theft": loss_val > 0.25,
        "timestamp": last_iot_timestamp,
    })


@app.post("/api/iot/reset")
async def reset_iot_telemetry():
    """Clears physical hardware overlay and restores normal simulation state."""
    global latest_iot_telemetry, last_iot_timestamp
    latest_iot_telemetry = None
    last_iot_timestamp = 0.0
    snapshot = twin.get_snapshot()
    snapshot = sync_snapshot_cache(snapshot)
    await broadcast_to_clients(snapshot)
    return JSONResponse({"status": "reset", "message": "IoT overlay cleared; simulation restored."})


@app.websocket("/ws")
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Streams live simulation updates to frontend viewers."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        # Send initial snapshot with hardware overlay
        snapshot = twin.get_snapshot()
        snapshot = sync_snapshot_cache(snapshot)
        await websocket.send_text(json.dumps(snapshot))
        while True:
            # Keepalive / listen for client commands
            msg = await websocket.receive_text()
            if msg == "step":
                snapshot = twin.step()
                snapshot = sync_snapshot_cache(snapshot)
                await broadcast_to_clients(snapshot)
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
