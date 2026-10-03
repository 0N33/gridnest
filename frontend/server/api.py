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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from engine.digital_twin import SmartGridDigitalTwin
from models.telemetry import ScenarioType
from export.geojson_exporter import GeoJSONTwinExporter

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


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serves the 3D Digital Twin Viewer UI."""
    viewer_path = os.path.join(os.path.dirname(__file__), "..", "viewer", "twin_viewer.html")
    if os.path.exists(viewer_path):
        with open(viewer_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h3>Digital Twin Viewer file not found.</h3>")


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


@app.post("/api/inject/{consumer_id}")
async def inject_scenario_endpoint(
    consumer_id: str,
    scenario: str = Query(..., description="NORMAL, THEFT_BYPASS, METER_MALFUNCTION, COMM_FAILURE, LEGITIMATE_ABNORMAL"),
    mode: Optional[str] = Query(None),
    scaling_factor: Optional[float] = Query(None),
):
    """Dynamically injects an operational scenario on a consumer."""
    try:
        scen_type = ScenarioType(scenario.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scenario type: {scenario}")

    params = {}
    if mode: params["mode"] = mode
    if scaling_factor: params["scaling_factor"] = scaling_factor

    twin.inject_scenario(consumer_id, scen_type, params)
    # Re-evaluate step
    snapshot = twin.step()
    await broadcast_to_clients(snapshot)
    return JSONResponse({"status": "success", "consumer_id": consumer_id, "scenario": scen_type.value})


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
