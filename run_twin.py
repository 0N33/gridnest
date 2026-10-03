"""
Master Execution Script for Smart Grid Digital Twin (3-Zone Architecture).
Runs end-to-end cyber-physical simulation, executes anomaly detection,
prints 3-zone energy accounting audits (Inputted vs Meters Added Up),
and exports GIS 3D datasets, roads, and investigation reports.
"""
from __future__ import annotations
import os
import sys
import argparse

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.digital_twin import SmartGridDigitalTwin
from export.geojson_exporter import GeoJSONTwinExporter
from export.report_exporter import ReportExporter


def run_digital_twin_demo(ticks: int = 4, export_dir: str = "output"):
    print("=" * 85)
    print("      SMART GRID DIGITAL TWIN | 3-ZONE CYBER-PHYSICAL SIMULATION ENGINE       ")
    print("                 Problem Statement 2: Power Station & City Grid               ")
    print("=" * 85)

    # 1. Initialize Twin
    print("\n[*] Initializing 3-Zone 3D Grid Topology & Smart Meter Network...")
    twin = SmartGridDigitalTwin(seed=42)
    twin.initialize(setup_scenarios=True)

    summary = twin.topology.get_topology_summary()
    ps = twin.topology.power_station
    print(f"    - Zone 0: Power Station Hub: {ps.name if ps else 'None'} ({ps.capacity_mva} MVA, {ps.transmission_voltage_kv}kV)")
    print(f"    - Zone 1: North City Sector (Commercial / Residential - TX-101)")
    print(f"    - Zone 2: South City Sector (Suburban Residential - TX-102)")
    print(f"    - Primary Feeders: {summary['feeders']} (11kV Trunks)")
    print(f"    - High-Voltage Pylons: {summary['pylons']}")
    print(f"    - Road Network Segments: {summary['roads']}")
    print(f"    - Distribution Poles: {summary['poles']}")
    print(f"    - Smart Meters / Consumers: {summary['consumers']}")

    # 2. Run Simulation Steps
    print(f"\n[*] Advancing Discrete Event Simulation ({ticks} intervals of 15-mins)...")
    for t in range(ticks):
        snapshot = twin.step()
        clock = snapshot["clock"]
        grid = snapshot["grid_summary"]
        print(f"    -> Tick #{clock['tick']:02d} [{clock['iso_time']}] | Total Input: {grid['total_grid_input_kw']} kW | Tech Loss: {grid['total_technical_loss_kw']} kW | Unexplained Loss: {grid['total_unexplained_loss_kw']} kW ({grid['grid_unexplained_ntl_pct']}%)")

    # 3. 3-Zone Energy Accounting Audit (Inputted vs Meters Added Up)
    print("\n" + "=" * 95)
    print("          3-ZONE ENERGY RECONCILIATION AUDIT: INPUTTED vs METERS ADDED UP          ")
    print("=" * 95)
    print(f"{'Zone':<16} | {'Transformer':<11} | {'Input (kWh)':<11} | {'Meters Sum':<11} | {'Tech Loss':<10} | {'Missing kWh':<12} | {'Loss %':<7} | {'Status'}")
    print("-" * 105)
    for tx_id, r in twin.latest_transformer_reports.items():
        print(f"{r.zone_id:<16} | {tx_id:<11} | {r.cumulative_energy_input_kwh:<11.2f} | {r.cumulative_reported_kwh:<11.2f} | {r.cumulative_tech_loss_kwh:<6.2f} kWh | {r.cumulative_unexplained_kwh:<7.2f} kWh ({r.unexplained_loss_pct:4.1f}%) | {r.unexplained_loss_pct:<5.1f}% | {r.status_label}")

    # 4. Multi-Signal Anomaly Detection & Ground Truth Verification
    print("\n" + "=" * 95)
    print("            DETECTED CONSUMER ANOMALIES & GROUND TRUTH REVEAL          ")
    print("=" * 95)
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

    # 5. Field Inspection Prioritization Queue
    print("\n" + "=" * 95)
    print("             FIELD ENFORCEMENT & ON-SITE INSPECTION PRIORITY QUEUE           ")
    print("=" * 95)
    print("Target Consumers Prioritized for Field Audit & Enforcement:")
    for t in twin.latest_inspection_targets[:5]:
        print(f"  Rank #{t.rank} -> {t.consumer_id} ({t.consumer_name}) | Score: {t.anomaly_score:.1f} | Cause: {t.probable_cause} | Unreported Loss: {t.unreported_loss_kw:.2f} kW")

    # 6. Export 3D GIS Layers, Roads, and Investigation Reports
    print(f"\n[*] Exporting GeoJSON 3D files and Investigation Reports to '{export_dir}'...")
    exporter = GeoJSONTwinExporter(twin)
    exporter.export_all_to_files(export_dir)

    rep_exporter = ReportExporter(twin)
    reports_dir = os.path.join(export_dir, "reports")

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
    print(f"    - Exported City Roads: {export_dir}/roads.geojson")
    print(f"    - Exported Electrical Lines: {export_dir}/grid_lines.geojson")

    print("\n" + "=" * 95)
    print("   DIGITAL TWIN SIMULATION COMPLETED SUCCESSFULLY - READY FOR AUDIT   ")
    print("=" * 95)
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
