# GridNest: Smart Grid Digital Twin & AI-Driven NTL Anomaly Detection

Welcome to **GridNest**, an enterprise-grade cyber-physical Digital Twin for electrical distribution networks featuring real-time energy reconciliation, anti-theft anomaly detection, and interactive 3D geospatial visualization.

---

## 📁 Repository Structure

```
GridNest/
├── run_twin.py               # Root helper runner (delegates to frontend/run_twin.py)
├── README.md                 # Root repository overview
└── frontend/                 # Complete 3D Digital Twin, Simulation Engine & UI
    ├── config.py             # Electrical and GIS configuration parameters
    ├── run_twin.py           # Core CLI and HTTP server runner
    ├── requirements.txt      # Python dependencies
    ├── README.md             # Detailed engineering and architecture specification
    ├── engine/               # Anomaly detection & energy accounting algorithms
    ├── export/               # GeoJSON & markdown report generators
    ├── models/               # Electrical models & telemetry schema
    ├── output/               # Generated GeoJSON maps, CSVs, and audit reports
    ├── server/               # FastAPI / ASGI real-time twin endpoint server
    ├── simulation/           # City generator, clock, and scenario injector
    ├── tests/                # Test suite with unit tests
    └── viewer/               # Three.js 3D CAD WebGL interactive viewer (twin_viewer.html)
```

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r frontend/requirements.txt
```

### 2. Run the Digital Twin & 3D Viewer
From repository root:
```bash
python run_twin.py --serve --port 8000
```
Or directly from `frontend/`:
```bash
cd frontend
python run_twin.py --serve --port 8000
```

Open your browser at **[http://localhost:8000](http://localhost:8000)**.

### 3. Run Automated Tests
```bash
python -m unittest discover frontend/tests
```

---

## 🌟 Key Highlights
- **3-Zone Electrical Hierarchy**:
  - **Zone 0**: 33kV Central Power Station & Switchyard Hub
  - **Zone 1**: West Commercial District (11kV Distribution Transformer TX-101)
  - **Zone 2**: East Residential District (11kV Distribution Transformer TX-102)
- **Energy Accounting Audit**: Tracks bulk transformer intake against aggregate consumer smart meters, calculating non-technical loss (NTL) in real time ("Done for!" alert if NTL > 6%).
- **3D Floating Pin Badges**: Interactive vertical mounting masts with circular score badges floating above flagged anomalous buildings.
- **Physical Ground Truth Unmasking**: Toggle to expose hidden meter shunts, tampering jumpers, and unreported diverted power.
