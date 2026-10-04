"""
FastAPI Backend and WebSocket Streaming Server for Smart Grid Digital Twin.
Serves real-time telemetry, 3D GeoJSON GIS layers, report generation endpoints,
and bidirectional scenario injection.
"""
from __future__ import annotations
import os
import json
import asyncio
from typing import Dict, Any, Optional
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
    return JSONResponse(twin.get_snapshot())


@app.post("/api/step")
async def step_simulation():
    """Advances simulation clock by 1 tick (15 mins) and returns updated state."""
    snapshot = twin.step()
    # Broadcast to websocket clients
    await broadcast_to_clients(snapshot)
    return JSONResponse(snapshot)


@app.get("/api/consumer/{consumer_id}")
async def get_consumer(consumer_id: str):
    """Returns telemetry, baseline, and anomaly analysis for a specific consumer."""
    snapshot = twin.get_snapshot()
    c_data = snapshot["consumers"].get(consumer_id)
    if not c_data:
        raise HTTPException(status_code=404, detail="Consumer not found")
    return JSONResponse(c_data)


@app.get("/api/report/{consumer_id}")
async def get_report(consumer_id: str):
    """Generates and returns an auditable investigation report."""
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


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Streams live simulation updates to frontend viewers."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        # Send initial snapshot
        await websocket.send_text(json.dumps(twin.get_snapshot()))
        while True:
            # Keepalive / listen for client commands
            msg = await websocket.receive_text()
            if msg == "step":
                snapshot = twin.step()
                await broadcast_to_clients(snapshot)
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
