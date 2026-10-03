"""
Report Exporter for Smart Grid Digital Twin.
Generates individual markdown/JSON investigation reports and bulk CSV summaries.
"""
from __future__ import annotations
import os
import json
import csv
from typing import Dict, List, Any, Optional
from engine.digital_twin import SmartGridDigitalTwin
from engine.explainer import InvestigationReport


class ReportExporter:
    """Exports investigation reports and grid summary audits."""

    def __init__(self, twin: SmartGridDigitalTwin):
        self.twin = twin

    def export_consumer_report_markdown(self, consumer_id: str, file_path: str) -> Optional[InvestigationReport]:
        report = self.twin.generate_investigation_report(consumer_id)
        if not report:
            return None

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report.to_markdown())

        return report

    def export_consumer_report_json(self, consumer_id: str, file_path: str) -> Optional[InvestigationReport]:
        report = self.twin.generate_investigation_report(consumer_id)
        if not report:
            return None

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)

        return report

    def export_grid_summary_csv(self, file_path: str):
        """Exports tabular CSV summary of all consumers with risk scores and causes."""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        rows = []
        for c_id, consumer in self.twin.topology.consumers.items():
            res = self.twin.latest_anomaly_results.get(c_id)
            dual = self.twin.latest_dual_records.get(c_id)
            rep_kw = dual.reported.active_power_kw if dual and dual.reported else 0.0
            true_kw = dual.ground_truth.active_power_kw if dual else 0.0

            rows.append({
                "consumer_id": consumer.id,
                "meter_id": consumer.meter_id,
                "name": consumer.name,
                "category": consumer.category,
                "contracted_load_kw": consumer.contracted_load_kw,
                "zone_id": consumer.zone_id,
                "transformer_id": consumer.transformer_id,
                "reported_kw": round(rep_kw, 3),
                "true_physical_kw": round(true_kw, 3),
                "baseline_mean_kw": round(res.baseline_mean_kw, 3) if res else 0.0,
                "deviation_pct": round(res.deviation_pct, 1) if res else 0.0,
                "anomaly_score": round(res.anomaly_score, 1) if res else 0.0,
                "risk_level": res.risk_level if res else "NORMAL",
                "probable_cause": res.probable_cause if res else "NORMAL",
                "confidence_pct": round(res.confidence_pct, 1) if res else 0.0,
                "action": res.recommended_action if res else "None",
            })

        fieldnames = [
            "consumer_id", "meter_id", "name", "category", "contracted_load_kw",
            "zone_id", "transformer_id", "reported_kw", "true_physical_kw",
            "baseline_mean_kw", "deviation_pct", "anomaly_score", "risk_level",
            "probable_cause", "confidence_pct", "action",
        ]

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
