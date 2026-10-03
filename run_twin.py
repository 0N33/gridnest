"""
Master Execution Script for Smart Grid Digital Twin.
Runs end-to-end cyber-physical simulation, executes anomaly detection,
prints energy accounting audits, and exports GIS 3D datasets and investigation reports.
"""
from __future__ import annotations
import os
import sys
import argparse
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.digital_twin import SmartGridDigitalTwin
from export.geojson_exporter import GeoJSONTwinExporter
from export.report_exporter import ReportExporter


def run_digital_twin_demo(ticks: int = 4, export_dir: str = "output"):
    print("=" * 80)
    print("      SMART GRID DIGITAL TWIN | CYBER-PHYSICAL SIMULATION ENGINE      ")
    print("               Problem Statement 2: Advanced Grid Twin               ")
    print("=" * 80)

    # 1. Initialize Twin
    print("\n[*] Initializing 2-Zone 3D Grid Topology & Smart Meter Network...")
    twin = SmartGridDigitalTwin(seed=42)
    twin.initialize(setup_scenarios=True)

    summary = twin.topology.get_topology_summary()
    print(f"    - Substation: {summary['substation']}")
    print(f"    - Distribution Feeders: {summary['feeders']} (11kV Trunks)")
    print(f"    - Distribution Transformers: {summary['transformers']} (TX-101 North & TX-102 South)")
    print(f"    - Utility Poles: {summary['poles']}")
    print(f"    - Smart Meters / Consumers: {summary['consumers']} across Zones: {summary['zones']}")

    # 2. Run Simulation Steps
    print(f"\n[*] Advancing Discrete Event Simulation ({ticks} intervals of 15-mins)...")
    for t in range(ticks):
        snapshot = twin.step()
        clock = snapshot["clock"]
        grid = snapshot["grid_summary"]
        print(f"    -> Tick #{clock['tick']:02d} [{clock['iso_time']}] | Total Input: {grid['total_grid_input_kw']} kW | Tech Loss: {grid['total_technical_loss_kw']} kW | Unexplained Loss: {grid['total_unexplained_loss_kw']} kW ({grid['grid_unexplained_ntl_pct']}%)")

    # 3. Energy Accounting Report per Transformer
    print("\n" + "=" * 80)
    print("               TRANSFORMER-LEVEL ENERGY ACCOUNTING AUDIT               ")
    print("=" * 80)
    print(f"{'Transformer':<10} | {'Zone':<14} | {'Intake (kW)':<11} | {'Rep Sum (kW)':<12} | {'Tech Loss':<10} | {'NTL Loss (kW)':<13} | {'NTL %':<7} | {'Status'}")
    print("-" * 105)
    for tx_id, r in twin.latest_transformer_reports.items():
        print(f"{tx_id:<10} | {r.zone_id:<14} | {r.transformer_input_kw:<11.2f} | {r.consumer_reported_load_kw:<12.2f} | {r.technical_losses_kw:<6.2f} kW | {r.unexplained_loss_kw:<7.2f} kW ({r.unexplained_loss_pct:4.1f}%) | {r.unexplained_loss_pct:<5.1f}% | {r.status}")

    # 4. Multi-Signal Anomaly Detection & Ground Truth Verification
    print("\n" + "=" * 80)
    print("            DETECTED CONSUMER ANOMALIES & GROUND TRUTH REVEAL          ")
    print("=" * 80)
    print(f"{'Consumer ID':<12} | {'Meter ID':<10} | {'Reported':<9} | {'Baseline':<9} | {'Dev %':<8} | {'True kW':<8} | {'Score':<6} | {'Risk':<8} | {'Probable Cause':<20} | {'Confidence'}")
    print("-" * 115)

    flagged_count = 0
    for c_id, res in twin.latest_anomaly_results.items():
        if res.risk_level in ["MEDIUM", "HIGH", "CRITICAL"] or res.probable_cause in ["THEFT_TAMPERING", "METER_MALFUNCTION"]:
            flagged_count += 1
            dual = twin.latest_dual_records.get(c_id)
            true_kw = dual.ground_truth.active_power_kw if dual else 0.0
            print(f"{c_id:<12} | {res.meter_id:<10} | {res.reported_kw:<6.2f} kW | {res.baseline_mean_kw:<6.2f} kW | {res.deviation_pct:>+6.1f}% | {true_kw:<5.2f} kW | {res.anomaly_score:<6.1f} | {res.risk_level:<8} | {res.probable_cause:<20} | {res.confidence_pct:.1f}%")

    print(f"\n[+] Total Anomalies Flagged: {flagged_count} (High/Critical: {sum(1 for r in twin.latest_anomaly_results.values() if r.risk_level in ['HIGH', 'CRITICAL'])})")

    # 5. Inspection Priority & Drone Flight Route
    print("\n" + "=" * 80)
    print("           AUTONOMOUS DRONE FLIGHT PATH & FIELD INSPECTION QUEUE       ")
    print("=" * 80)
    flight = twin.latest_drone_flight
    if flight:
        print(f"Base Hub: {flight.base_hub_id} | Total Inspection Trajectory: {flight.total_distance_m:.1f} meters | Est Flight Time: {flight.estimated_flight_minutes:.1f} mins")
        print("Inspection Queue Priority Sequence:")
        for t in twin.latest_inspection_targets[:5]:
            print(f"  Rank #{t.rank} -> {t.consumer_id} ({t.consumer_name}) | Score: {t.anomaly_score:.1f} | Cause: {t.probable_cause} | Unreported Loss: {t.unreported_loss_kw:.2f} kW")

    # 6. Export 3D GIS Layers and Investigation Reports
    print(f"\n[*] Exporting GeoJSON 3D files and Investigation Reports to '{export_dir}'...")
    exporter = GeoJSONTwinExporter(twin)
    exporter.export_all_to_files(export_dir)

    rep_exporter = ReportExporter(twin)
    reports_dir = os.path.join(export_dir, "reports")

    # Generate sample markdown report for top theft target
    top_target = twin.latest_inspection_targets[0] if twin.latest_inspection_targets else None
    if top_target:
        rpt_md_path = os.path.join(reports_dir, f"report_{top_target.consumer_id}.md")
        rpt_json_path = os.path.join(reports_dir, f"report_{top_target.consumer_id}.json")
        rep_exporter.export_consumer_report_markdown(top_target.consumer_id, rpt_md_path)
        rep_exporter.export_consumer_report_json(top_target.consumer_id, rpt_json_path)
        print(f"    - Generated Markdown Report: {rpt_md_path}")
        print(f"    - Generated JSON Audit Data: {rpt_json_path}")

    csv_path = os.path.join(export_dir, "all_consumers_audit_summary.csv")
    rep_exporter.export_grid_summary_csv(csv_path)
    print(f"    - Exported Tabular Grid CSV: {csv_path}")
    print(f"    - Exported 3D GeoJSON: {export_dir}/buildings_3d.geojson")
    print(f"    - Exported Electrical Lines: {export_dir}/grid_lines.geojson")

    print("\n" + "=" * 80)
    print("   DIGITAL TWIN SIMULATION COMPLETED SUCCESSFULLY - READY FOR AUDIT   ")
    print("=" * 80)
    return twin


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Grid Digital Twin Simulation Runner")
    parser.add_argument("--ticks", type=int, default=4, help="Number of 15-minute simulation intervals to advance")
    parser.add_argument("--output", type=str, default="output", help="Output directory for GeoJSON and reports")
    parser.add_argument("--serve", action="store_true", help="Launch FastAPI + WebSocket 3D Viewer web server")
    parser.add_argument("--port", type=int, default=8000, help="Port for server")

    args = parser.parse_args()

    twin = run_digital_twin_demo(ticks=args.ticks, export_dir=args.output)

    if args.serve:
        import uvicorn
        print(f"\n[+] Starting Smart Grid Digital Twin 3D Server on http://localhost:{args.port} ...")
        print(f"    Open your browser to http://localhost:{args.port} to view the 3D God's Eye Inspector!")
        uvicorn.run("server.api:app", host="0.0.0.0", port=args.port, reload=False)
