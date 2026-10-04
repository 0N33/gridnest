"""
GridNest Mock Adafruit IO Cloud Broker & Hardware Test Harness.
Emulates the Adafruit IO REST API (v2) locally on port 8002, allowing you to:
1. Test your Adafruit bridge (adafruit_bridge.py) without needing a real Adafruit account.
2. Simulate realistic ESP32 telemetry packets for Zone B Transformer (TX_102) & Consumer (CONS_S_001).
3. Switch with 1 click between Normal Balanced Flow and Line Tap Theft to see the 3D twin react live.
4. Provide a sleek interactive web dashboard at http://localhost:8002.
"""
from __future__ import annotations

import os
import json
import time
import math
import random
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

GRIDNEST_TWIN_URL = os.environ.get("GRIDNEST_URL", "http://localhost:8000/api/iot/telemetry")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(auto_stream_worker())
    yield
    task.cancel()

app = FastAPI(
    title="Mock Adafruit IO Broker — GridNest IoT Test Harness",
    description="Local emulation of Adafruit IO REST API for ESP32 energy telemetry testing.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# In-Memory Feed Database
# -----------------------------------------------------------------------------
class MockFeedStore:
    def __init__(self):
        self.entry_counter = 1000
        # Stores feed_key -> list of records (most recent first)
        self.feeds: Dict[str, List[dict]] = {}
        # Configuration
        self.direct_forward_to_twin = True
        self.auto_stream_active = True
        self.auto_stream_mode = "normal"  # "normal" or "theft"
        self.auto_stream_interval = 1.5
        self.total_packets_sent = 0

        # Cumulative energy tracking
        self.last_calc_time = time.time()
        self.trans_energy_wh = 0.0150
        self.cons_energy_wh = 0.0145

        # Seed initial default balanced reading
        self.set_reading(
            trans_v=4.51, trans_c=465.0, trans_w=2.10,
            cons_v=4.38, cons_c=472.0, cons_w=2.07,
            loss_w=0.03, feed_key="energy-telemetry", note="System initialized"
        )

    def set_reading(
        self,
        trans_v: float,
        trans_c: float,
        trans_w: float,
        cons_v: float,
        cons_c: float,
        cons_w: float,
        loss_w: float,
        feed_key: str = "energy-telemetry",
        note: str = ""
    ) -> dict:
        self.entry_counter += 1
        now_dt = datetime.now(timezone.utc)
        iso_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Accumulate energy
        now_sec = time.time()
        delta_hours = max(0.0, (now_sec - self.last_calc_time) / 3600.0)
        self.last_calc_time = now_sec
        self.trans_energy_wh += trans_w * delta_hours
        self.cons_energy_wh += cons_w * delta_hours
        energy_loss_wh = max(0.0, self.trans_energy_wh - self.cons_energy_wh)

        telemetry_payload = {
            "transVoltage": round(trans_v, 2),
            "transCurrent": round(trans_c, 1),
            "transPower_W": round(trans_w, 2),
            "transEnergy_Wh": round(self.trans_energy_wh, 4),
            "consVoltage": round(cons_v, 2),
            "consCurrent": round(cons_c, 1),
            "consPower_W": round(cons_w, 2),
            "consEnergy_Wh": round(self.cons_energy_wh, 4),
            "powerLoss_W": round(loss_w, 2),
            "energyLoss_Wh": round(energy_loss_wh, 4),
            "target_consumer_id": "CONS_S_001",
            "target_transformer_id": "TX_102",
            "timestamp": iso_str,
            "note": note
        }

        # Value serialized as JSON string (standard Adafruit IO pattern for structured ESP32 payloads)
        value_str = json.dumps(telemetry_payload)

        record = {
            "id": f"rec_{self.entry_counter}",
            "value": value_str,
            "feed_id": 40401,
            "feed_key": feed_key,
            "created_at": iso_str,
            "created_epoch": int(now_sec),
            "telemetry": telemetry_payload,
        }

        if feed_key not in self.feeds:
            self.feeds[feed_key] = []
        self.feeds[feed_key].insert(0, record)
        # Keep latest 100 entries
        self.feeds[feed_key] = self.feeds[feed_key][:100]
        self.total_packets_sent += 1

        return record

store = MockFeedStore()


# -----------------------------------------------------------------------------
# Background Forwarder & Auto-Stream Task
# -----------------------------------------------------------------------------
async def forward_to_gridnest(telemetry: dict):
    """Pushes telemetry payload asynchronously to GridNest Twin API."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(GRIDNEST_TWIN_URL, json=telemetry)
            if resp.status_code == 200:
                print(f"[FORWARD OK] Pushed to GridNest Twin: Loss={telemetry.get('powerLoss_W')}W | Tx={telemetry.get('transPower_W')}W")
                return True
            else:
                print(f"[FORWARD FAIL {resp.status_code}] {resp.text}")
    except Exception as e:
        print(f"[FORWARD ERROR] {e}")
    return False


async def auto_stream_worker():
    """Background simulator generating realistic packets continuously."""
    while True:
        try:
            if store.auto_stream_active:
                feed_key = "energy-telemetry"
                noise_v = random.uniform(-0.04, 0.04)
                noise_c = random.uniform(-8.0, 8.0)

                if store.auto_stream_mode == "theft":
                    # Simulated Theft / Tap: Transformer outputs ~2.8-3.0 W, but Consumer only sees ~1.1 W
                    tv = 4.62 + noise_v
                    tc = 630.0 + noise_c
                    tw = tv * (tc / 1000.0)

                    cv = 4.05 + noise_v
                    cc = 275.0 + noise_c
                    cw = cv * (cc / 1000.0)

                    loss = max(0.0, tw - cw)
                    record = store.set_reading(
                        tv, tc, tw, cv, cc, cw, loss,
                        feed_key=feed_key,
                        note="AUTO-STREAM: Active Wire Tap Theft (~60% diversion)"
                    )
                else:
                    # Simulated Balanced Flow: Minimal resistive line loss (~0.02 - 0.06 W)
                    tv = 4.50 + noise_v
                    tc = 465.0 + noise_c
                    tw = tv * (tc / 1000.0)

                    cv = 4.38 + noise_v
                    cc = 470.0 + noise_c
                    cw = cv * (cc / 1000.0)

                    loss = max(0.01, round(tw - cw, 2))
                    record = store.set_reading(
                        tv, tc, tw, cv, cc, cw, loss,
                        feed_key=feed_key,
                        note="AUTO-STREAM: Balanced Normal Flow"
                    )

                if store.direct_forward_to_twin:
                    await forward_to_gridnest(record["telemetry"])

            await asyncio.sleep(store.auto_stream_interval)
        except Exception:
            await asyncio.sleep(2.0)

# -----------------------------------------------------------------------------
# Official Adafruit IO REST API v2 Emulation
# -----------------------------------------------------------------------------
@app.get("/api/v2/{username}/feeds/{feed_key}/data/last")
def get_feed_last_data(username: str, feed_key: str):
    """
    Adafruit IO endpoint: GET latest data record in feed.
    Called directly by adafruit_bridge.py!
    """
    records = store.feeds.get(feed_key, [])
    if not records:
        # Default fallback
        record = store.set_reading(4.50, 460.0, 2.07, 4.35, 470.0, 2.04, 0.03, feed_key=feed_key)
        records = [record]

    last = records[0]
    return {
        "id": last["id"],
        "value": last["value"],
        "feed_id": last.get("feed_id", 40401),
        "feed_key": feed_key,
        "created_at": last["created_at"],
        "created_epoch": last.get("created_epoch", int(time.time())),
        "expiration": "2026-11-04T00:00:00Z",
    }


@app.post("/api/v2/{username}/feeds/{feed_key}/data")
async def post_feed_data(username: str, feed_key: str, payload: dict = Body(...)):
    """
    Adafruit IO endpoint: POST new reading to feed.
    ESP32 firmware or testing scripts post here.
    """
    raw_val = payload.get("value", "")

    # Parse value if it is JSON
    parsed = {}
    if isinstance(raw_val, dict):
        parsed = raw_val
        val_str = json.dumps(raw_val)
    elif isinstance(raw_val, str):
        try:
            parsed = json.loads(raw_val)
            val_str = raw_val
        except Exception:
            val_str = raw_val
    else:
        val_str = str(raw_val)

    # If telemetry details supplied, update store with accurate numbers
    if parsed and "transPower_W" in parsed:
        rec = store.set_reading(
            trans_v=float(parsed.get("transVoltage", 4.5)),
            trans_c=float(parsed.get("transCurrent", 460.0)),
            trans_w=float(parsed.get("transPower_W", 2.07)),
            cons_v=float(parsed.get("consVoltage", 4.35)),
            cons_c=float(parsed.get("consCurrent", 470.0)),
            cons_w=float(parsed.get("consPower_W", 2.04)),
            loss_w=float(parsed.get("powerLoss_W", 0.03)),
            feed_key=feed_key,
            note="Posted via Adafruit REST POST"
        )
    else:
        # Generic single value
        store.entry_counter += 1
        now_dt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec = {
            "id": f"rec_{store.entry_counter}",
            "value": val_str,
            "feed_id": 40401,
            "feed_key": feed_key,
            "created_at": now_dt,
            "created_epoch": int(time.time()),
            "telemetry": parsed or {"value": val_str}
        }
        if feed_key not in store.feeds:
            store.feeds[feed_key] = []
        store.feeds[feed_key].insert(0, rec)

    if store.direct_forward_to_twin and isinstance(rec.get("telemetry"), dict) and "transPower_W" in rec["telemetry"]:
        await forward_to_gridnest(rec["telemetry"])

    return rec


@app.get("/api/v2/{username}/feeds/{feed_key}/data")
def get_feed_data_history(username: str, feed_key: str, limit: int = 20):
    records = store.feeds.get(feed_key, [])[:limit]
    return records


@app.get("/api/v2/{username}/feeds")
def list_feeds(username: str):
    return [
        {
            "id": 40401,
            "name": k,
            "key": k,
            "last_value": store.feeds[k][0]["value"] if store.feeds[k] else "",
            "updated_at": store.feeds[k][0]["created_at"] if store.feeds[k] else "",
        }
        for k in store.feeds
    ]


# -----------------------------------------------------------------------------
# Control Panel & Simulation API
# -----------------------------------------------------------------------------
@app.get("/api/mock/status")
def get_mock_status():
    records = store.feeds.get("energy-telemetry", [])
    latest_rec = records[0] if records else None
    return {
        "status": "online",
        "total_packets": store.total_packets_sent,
        "direct_forwarding": store.direct_forward_to_twin,
        "auto_stream_active": store.auto_stream_active,
        "auto_stream_mode": store.auto_stream_mode,
        "latest": latest_rec["telemetry"] if latest_rec else None,
        "twin_url": GRIDNEST_TWIN_URL
    }


@app.post("/api/mock/scenario/{scenario_name}")
async def trigger_scenario(scenario_name: str):
    """Triggers preset test scenarios instantly."""
    feed_key = "energy-telemetry"
    if scenario_name == "normal":
        store.auto_stream_mode = "normal"
        rec = store.set_reading(
            trans_v=4.51, trans_c=465.0, trans_w=2.10,
            cons_v=4.38, cons_c=472.0, cons_w=2.07,
            loss_w=0.03, feed_key=feed_key,
            note="PRESET: Normal Balanced Grid Operation"
        )
    elif scenario_name == "theft":
        store.auto_stream_mode = "theft"
        # 1.87W loss (~62% theft!) -> triggers critical red alert on 3D viewer
        rec = store.set_reading(
            trans_v=4.65, trans_c=650.0, trans_w=3.02,
            cons_v=4.08, cons_c=282.0, cons_w=1.15,
            loss_w=1.87, feed_key=feed_key,
            note="PRESET: Shunt Tap Theft / Meter Bypass Detected!"
        )
    elif scenario_name == "sag":
        store.auto_stream_mode = "normal"
        rec = store.set_reading(
            trans_v=4.15, trans_c=780.0, trans_w=3.24,
            cons_v=3.65, cons_c=760.0, cons_w=2.77,
            loss_w=0.47, feed_key=feed_key,
            note="PRESET: Voltage Sag / High Line Impedance"
        )
    else:
        raise HTTPException(status_code=400, detail="Unknown scenario. Use 'normal', 'theft', or 'sag'.")

    forwarded = False
    if store.direct_forward_to_twin:
        forwarded = await forward_to_gridnest(rec["telemetry"])

    return {
        "status": "success",
        "scenario": scenario_name,
        "record": rec,
        "forwarded_to_gridnest": forwarded
    }


@app.post("/api/mock/toggle_autostream")
def toggle_autostream(active: Optional[bool] = None, mode: Optional[str] = None):
    if active is not None:
        store.auto_stream_active = active
    else:
        store.auto_stream_active = not store.auto_stream_active

    if mode and mode in ["normal", "theft"]:
        store.auto_stream_mode = mode

    return {
        "auto_stream_active": store.auto_stream_active,
        "auto_stream_mode": store.auto_stream_mode
    }


@app.post("/api/mock/toggle_forwarding")
def toggle_forwarding(enabled: Optional[bool] = None):
    if enabled is not None:
        store.direct_forward_to_twin = enabled
    else:
        store.direct_forward_to_twin = not store.direct_forward_to_twin
    return {"direct_forward_to_twin": store.direct_forward_to_twin}


# -----------------------------------------------------------------------------
# Interactive Web Dashboard
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GridNest · Mock Adafruit IO Cloud Broker</title>
<style>
  :root {
    --bg-dark: #0a0d14;
    --card-bg: #121824;
    --border: #1e293b;
    --primary: #38bdf8;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --text-dim: #94a3b8;
    --text-light: #f8fafc;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { background: var(--bg-dark); color: var(--text-light); padding: 24px; min-height: 100vh; }
  .container { max-width: 1200px; margin: 0 auto; }
  
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
  .logo-title h1 { font-size: 20px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }
  .logo-title p { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
  .badge { padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; }
  .badge-live { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #059669; }
  .badge-theft { background: rgba(239, 68, 68, 0.25); color: #f87171; border: 1px solid #dc2626; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; margin-bottom: 24px; }
  .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card-title { font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }

  .metric-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .metric-box { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 12px; }
  .metric-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; }
  .metric-val { font-size: 22px; font-weight: 700; color: #fff; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .metric-unit { font-size: 13px; color: var(--text-dim); font-weight: 400; margin-left: 2px; }

  .loss-banner { border-radius: 8px; padding: 16px; margin-top: 14px; display: flex; justify-content: space-between; align-items: center; }
  .loss-banner.normal { background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); }
  .loss-banner.theft { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); }

  .btn-group { display: flex; flex-direction: column; gap: 10px; }
  .btn { padding: 12px 18px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: all 0.2s; }
  .btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
  .btn:active { transform: translateY(0); }
  .btn-green { background: #059669; color: #fff; }
  .btn-red { background: #dc2626; color: #fff; }
  .btn-amber { background: #d97706; color: #fff; }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text-light); }
  .btn-outline:hover { background: rgba(255, 255, 255, 0.05); }

  .controls-row { display: flex; gap: 12px; align-items: center; margin-top: 14px; }
  .toggle-btn { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid var(--border); background: #1a2233; color: #fff; font-size: 12px; font-weight: 600; cursor: pointer; text-align: center; }
  .toggle-btn.active { background: #2563eb; border-color: #3b82f6; }

  .console { background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 14px; font-family: monospace; font-size: 12px; height: 180px; overflow-y: auto; color: #38bdf8; line-height: 1.5; }
  .info-box { background: rgba(56, 189, 248, 0.08); border-left: 3px solid #38bdf8; padding: 12px; border-radius: 4px; font-size: 12px; color: #bae6fd; line-height: 1.4; margin-bottom: 20px; }
  a { color: #38bdf8; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo-title">
      <h1>☁️ GridNest · Mock Adafruit IO Cloud Broker</h1>
      <p>Simulated Adafruit IO REST API for ESP32 Energy Telemetry & Hardware Twin Testing</p>
    </div>
    <div style="display: flex; gap: 12px; align-items: center;">
      <span class="badge badge-live">Broker Active :8002</span>
      <a href="http://localhost:8000" target="_blank" class="btn btn-outline" style="padding: 6px 14px; font-size: 12px;">Open 3D Twin Viewer ↗</a>
    </div>
  </header>

  <div class="info-box">
    <strong>💡 Testing Instructions:</strong> This local mock broker satisfies the exact Adafruit IO endpoint <code>GET /api/v2/{username}/feeds/energy-telemetry/data/last</code>. 
    Click <strong>"Simulate Line Tap Theft"</strong> to push stolen unmetered power, then inspect <strong>Zone B (House CONS_S_001 & Transformer TX_102)</strong> on the 3D twin viewer. The building will immediately turn red with a critical theft warning!
  </div>

  <div class="grid">
    <!-- Card 1: Transformer & Consumer Telemetry -->
    <div class="card">
      <div class="card-title">
        <span>⚡ Zone B Hardware Readings</span>
        <span id="theft-badge" class="badge badge-live">Grid Balanced</span>
      </div>

      <div style="font-size: 12px; color: var(--text-dim); margin-bottom: 8px;">Physical Drop Line: TX_102 ➔ CONS_S_001</div>
      
      <div class="metric-row">
        <div class="metric-box">
          <div class="metric-label">Transformer Power</div>
          <div class="metric-val"><span id="trans-w">2.10</span><span class="metric-unit">W</span></div>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 4px;"><span id="trans-v">4.51</span> V · <span id="trans-c">465</span> mA</div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Consumer Meter</div>
          <div class="metric-val"><span id="cons-w">2.07</span><span class="metric-unit">W</span></div>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 4px;"><span id="cons-v">4.38</span> V · <span id="cons-c">472</span> mA</div>
        </div>
      </div>

      <div class="metric-row">
        <div class="metric-box">
          <div class="metric-label">Tx Cumulative Energy</div>
          <div class="metric-val" style="font-size: 18px;"><span id="trans-wh">0.0150</span><span class="metric-unit">Wh</span></div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Cons Cumulative Energy</div>
          <div class="metric-val" style="font-size: 18px;"><span id="cons-wh">0.0145</span><span class="metric-unit">Wh</span></div>
        </div>
      </div>

      <div id="loss-banner" class="loss-banner normal">
        <div>
          <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.8;">Line Power Loss (Unmetered)</div>
          <div style="font-size: 22px; font-weight: 700;"><span id="loss-w">0.03</span> W <span style="font-size: 13px; font-weight: normal; opacity: 0.8;">(<span id="loss-pct">1.4</span>%)</span></div>
        </div>
        <div id="loss-status-text" style="font-size: 12px; font-weight: 600; text-align: right;">
          Healthy Drop Wire<br><span style="font-size: 10px; opacity: 0.7;">Nominal Jitter</span>
        </div>
      </div>
    </div>

    <!-- Card 2: Interactive Controls & Presets -->
    <div class="card">
      <div class="card-title">
        <span>🎮 Interactive Simulation Triggers</span>
        <span style="font-size: 11px; color: var(--text-dim);" id="packet-counter">Packets: 1</span>
      </div>

      <div class="btn-group">
        <button class="btn btn-green" onclick="sendScenario('normal')">
          <span>🟢</span> Send Balanced Normal Packet (2.1W / 0.03W Loss)
        </button>
        <button class="btn btn-red" onclick="sendScenario('theft')">
          <span>🔴</span> Simulate Line Tap Theft (3.0W Tx / 1.1W Cons / 1.87W Stolen!)
        </button>
        <button class="btn btn-amber" onclick="sendScenario('sag')">
          <span>🟡</span> Simulate Voltage Sag / Heavy Impedance (0.47W Loss)
        </button>
      </div>

      <hr style="border: 0; border-top: 1px solid var(--border); margin: 18px 0;">

      <div style="font-size: 12px; font-weight: 600; margin-bottom: 8px;">Auto-Stream Loop (1.5s interval):</div>
      <div class="controls-row">
        <button id="btn-stream" class="toggle-btn" onclick="toggleAutoStream()">Start Auto-Stream</button>
        <button id="btn-mode-normal" class="toggle-btn active" onclick="setAutoStreamMode('normal')">Normal Mode</button>
        <button id="btn-mode-theft" class="toggle-btn" onclick="setAutoStreamMode('theft')">Theft Mode</button>
      </div>

      <div style="margin-top: 14px; font-size: 12px; display: flex; align-items: center; justify-content: space-between;">
        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
          <input type="checkbox" id="chk-forward" checked onchange="toggleForwarding(this.checked)">
          <span>Auto-Forward directly to Digital Twin (Port 8000)</span>
        </label>
      </div>
    </div>
  </div>

  <!-- Card 3: Terminal Console -->
  <div class="card">
    <div class="card-title">
      <span>📡 Broker Telemetry Log (Adafruit IO Stream)</span>
      <button class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="document.getElementById('console').innerHTML=''">Clear Log</button>
    </div>
    <div class="console" id="console"></div>
  </div>
</div>

<script>
let autoStream = false;
let currentMode = "normal";

function log(msg, color="#38bdf8") {
  const c = document.getElementById('console');
  const d = new Date().toLocaleTimeString();
  const line = document.createElement('div');
  line.style.color = color;
  line.textContent = `[${d}] ${msg}`;
  c.prepend(line);
}

async function updateStatus() {
  try {
    const res = await fetch('/api/mock/status');
    const data = await res.json();
    
    document.getElementById('packet-counter').textContent = `Packets: ${data.total_packets}`;
    document.getElementById('chk-forward').checked = data.direct_forwarding;

    // Update buttons
    autoStream = data.auto_stream_active;
    const btnStream = document.getElementById('btn-stream');
    if (autoStream) {
      btnStream.classList.add('active');
      btnStream.textContent = '⏹ Stop Auto-Stream';
    } else {
      btnStream.classList.remove('active');
      btnStream.textContent = '▶ Start Auto-Stream';
    }

    currentMode = data.auto_stream_mode;
    document.getElementById('btn-mode-normal').classList.toggle('active', currentMode === 'normal');
    document.getElementById('btn-mode-theft').classList.toggle('active', currentMode === 'theft');

    if (data.latest) {
      renderTelemetry(data.latest);
      if (data.direct_forwarding && (!window.lastForwardedTime || Date.now() - window.lastForwardedTime > 1400)) {
        window.lastForwardedTime = Date.now();
        fetch('http://localhost:8000/api/iot/telemetry', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data.latest)
        }).catch(()=>{});
      }
    }
  } catch(e) {
    console.error(e);
  }
}

function renderTelemetry(t) {
  document.getElementById('trans-w').textContent = t.transPower_W?.toFixed(2) || '0.00';
  document.getElementById('trans-v').textContent = t.transVoltage?.toFixed(2) || '0.00';
  document.getElementById('trans-c').textContent = t.transCurrent?.toFixed(1) || '0.0';
  document.getElementById('trans-wh').textContent = t.transEnergy_Wh?.toFixed(4) || '0.0000';

  document.getElementById('cons-w').textContent = t.consPower_W?.toFixed(2) || '0.00';
  document.getElementById('cons-v').textContent = t.consVoltage?.toFixed(2) || '0.00';
  document.getElementById('cons-c').textContent = t.consCurrent?.toFixed(1) || '0.0';
  document.getElementById('cons-wh').textContent = t.consEnergy_Wh?.toFixed(4) || '0.0000';

  const loss = t.powerLoss_W || 0.0;
  const transW = t.transPower_W || 0.01;
  const lossPct = ((loss / transW) * 100).toFixed(1);
  
  document.getElementById('loss-w').textContent = loss.toFixed(2);
  document.getElementById('loss-pct').textContent = lossPct;

  const banner = document.getElementById('loss-banner');
  const badge = document.getElementById('theft-badge');
  const statusText = document.getElementById('loss-status-text');

  if (loss > 0.25 && parseFloat(lossPct) > 8.0) {
    banner.className = 'loss-banner theft';
    badge.className = 'badge badge-theft';
    badge.textContent = '⚠️ THEFT / WIRE TAP DETECTED';
    statusText.innerHTML = `<span style="color:#f87171;">CRITICAL TAMPERING</span><br><span style="font-size: 10px;">${lossPct}% Power Stolen</span>`;
  } else {
    banner.className = 'loss-banner normal';
    badge.className = 'badge badge-live';
    badge.textContent = 'GRID BALANCED';
    statusText.innerHTML = `Healthy Drop Wire<br><span style="font-size: 10px; opacity: 0.7;">Nominal Jitter</span>`;
  }
}

async function sendScenario(name) {
  try {
    const res = await fetch(`/api/mock/scenario/${name}`, { method: 'POST' });
    const data = await res.json();
    log(`Preset applied: ${name.toUpperCase()} -> Trans: ${data.record.telemetry.transPower_W}W, Cons: ${data.record.telemetry.consPower_W}W, Loss: ${data.record.telemetry.powerLoss_W}W`, name === 'theft' ? '#ef4444' : '#10b981');
    updateStatus();

    if (data.record && data.record.telemetry) {
      try {
        await fetch('http://localhost:8000/api/iot/telemetry', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data.record.telemetry)
        });
        log('⚡ Forwarded to Digital Twin (:8000)', '#34d399');
      } catch(fErr) {
        log('Notice: Forward to :8000 (' + fErr.message + ')', '#94a3b8');
      }
    }
  } catch(e) {
    log(`Error triggering scenario: ${e.message}`, '#ef4444');
  }
}

async function toggleAutoStream() {
  try {
    const res = await fetch('/api/mock/toggle_autostream', { method: 'POST' });
    const data = await res.json();
    log(`Auto-stream ${data.auto_stream_active ? 'STARTED' : 'STOPPED'} (Mode: ${data.auto_stream_mode})`);
    updateStatus();
  } catch(e) {
    console.error(e);
  }
}

async function setAutoStreamMode(mode) {
  try {
    const res = await fetch(`/api/mock/toggle_autostream?mode=${mode}`, { method: 'POST' });
    const data = await res.json();
    log(`Auto-stream mode switched to: ${mode.toUpperCase()}`);
    updateStatus();
  } catch(e) {
    console.error(e);
  }
}

async function toggleForwarding(enabled) {
  try {
    await fetch(`/api/mock/toggle_forwarding?enabled=${enabled}`, { method: 'POST' });
    log(`Direct Twin Forwarding: ${enabled ? 'ENABLED' : 'DISABLED'}`);
  } catch(e) {
    console.error(e);
  }
}

// Polling for UI refresh
setInterval(updateStatus, 1500);
updateStatus();
log("Connected to Mock Adafruit Broker at http://localhost:8002");
log("Ready to emulate feeds. Real-time REST endpoints active.");
</script>
</body>
</html>
"""


def main():
    print("\n=======================================================")
    print(" ☁️  GRIDNEST MOCK ADAFRUIT IO BROKER & HARNESS")
    print(" Dashboard:        http://localhost:8002")
    print(" Adafruit REST:    http://localhost:8002/api/v2/{user}/feeds/{feed}/data/last")
    print(" Twin Endpoint:    http://localhost:8000/api/iot/telemetry")
    print(" Target House:     CONS_S_001 (Zone B)")
    print(" Target Trans:     TX_102     (Zone B)")
    print("=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")


if __name__ == "__main__":
    main()
