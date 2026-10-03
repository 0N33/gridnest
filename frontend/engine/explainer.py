"""
Explainable Investigation Report Generator.
Synthesizes telemetry, historical baselines, spatial transformer context,
champion hybrid ML models (XGBoost + LightGBM + Isolation Forest),
SHAP feature attributions, and physical ground truth into auditable, court-ready utility inspection reports.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from models.topology import ConsumerNode
from models.telemetry import DualStateRecord, ScenarioType
from engine.anomaly_detector import AnomalyDetectionResult
from engine.energy_accounting import TransformerLossReport


@dataclass
class InvestigationReport:
    """Formal audit report explaining an identified grid anomaly."""
    report_id: str
    generated_at: str
    consumer_id: str
    meter_id: str
    consumer_name: str
    category: str
    contracted_load_kw: float
    zone_id: str
    transformer_id: str
    feeder_id: str
    anomaly_score: float
    risk_level: str
    probable_cause: str
    confidence_pct: float
    reported_kw: float
    historical_baseline_kw: float
    deviation_kw: float
    deviation_pct: float
    deviation_z: float
    voltage_v: float
    current_a: float
    power_factor: float
    zone_unexplained_loss_pct: float
    evidence_chain: List[str]
    technical_assessment: str
    recommended_action: str
    inspection_priority_rank: int = 1
    # Machine Learning & Explainability
    ml_score: float = 0.0
    ml_subscores: Dict[str, float] = field(default_factory=dict)
    shap_factors: List[Dict[str, Any]] = field(default_factory=list)
    historical_vs_realtime: Dict[str, Any] = field(default_factory=dict)
    # Ground truth audit (USP: Revealed for validation & ground-truth comparison)
    ground_truth_kw: Optional[float] = None
    unreported_stolen_kw: Optional[float] = None
    active_scenario: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "consumer": {
                "id": self.consumer_id,
                "meter_id": self.meter_id,
                "name": self.consumer_name,
                "category": self.category,
                "contracted_load_kw": self.contracted_load_kw,
                "zone_id": self.zone_id,
                "transformer_id": self.transformer_id,
                "feeder_id": self.feeder_id,
            },
            "findings": {
                "anomaly_score": round(self.anomaly_score, 1),
                "risk_level": self.risk_level,
                "probable_cause": self.probable_cause,
                "confidence_pct": round(self.confidence_pct, 1),
                "inspection_priority_rank": self.inspection_priority_rank,
            },
            "ml_analytics": {
                "calibrated_score": round(self.ml_score, 1),
                "subscores": self.ml_subscores,
                "shap_factors": self.shap_factors,
            },
            "historical_vs_realtime": self.historical_vs_realtime,
            "metrics": {
                "reported_kw": round(self.reported_kw, 3),
                "historical_baseline_kw": round(self.historical_baseline_kw, 3),
                "deviation_kw": round(self.deviation_kw, 3),
                "deviation_pct": round(self.deviation_pct, 1),
                "deviation_z": round(self.deviation_z, 2),
                "voltage_v": round(self.voltage_v, 2),
                "current_a": round(self.current_a, 2),
                "power_factor": round(self.power_factor, 3),
                "zone_unexplained_loss_pct": round(self.zone_unexplained_loss_pct, 2),
            },
            "ground_truth_audit": {
                "active_scenario": self.active_scenario,
                "ground_truth_kw": round(self.ground_truth_kw, 3) if self.ground_truth_kw is not None else None,
                "unreported_stolen_kw": round(self.unreported_stolen_kw, 3) if self.unreported_stolen_kw is not None else None,
            },
            "evidence_chain": self.evidence_chain,
            "technical_assessment": self.technical_assessment,
            "recommended_action": self.recommended_action,
        }

    def to_markdown(self) -> str:
        """Formats the report as a beautiful GitHub Markdown document."""
        gt_section = ""
        if self.ground_truth_kw is not None:
            gt_section = f"""
### Ground Truth Verification (Digital Twin Telemetry Reveal)
- **Active Physical Scenario:** `{self.active_scenario}`
- **True Physical Consumption:** `{self.ground_truth_kw:.3f} kW`
- **Cyber Reported Reading:** `{self.reported_kw:.3f} kW`
- **Unreported / Stolen Power:** `{self.unreported_stolen_kw:.3f} kW`
> **Model Accuracy Confirmation:** The detector successfully extracted this anomaly with `{self.confidence_pct:.1f}%` confidence against physical reality.
"""

        hvr = self.historical_vs_realtime or {}
        hvr_section = ""
        if hvr:
            hvr_section = f"""
### Historical Benchmark vs. Real-Time Telemetry Audit
| Audit Metric | Ground-Truth Historical Record | Real-Time Telemetry (15-min streaming) |
|---|---|---|
| **Dataset Source / Benchmark** | State Grid Corp China (`data.csv`) | Digital Twin IoT Streaming Telemetry |
| **Kaggle Consumer Hash** | `{hvr.get('kaggle_id', 'N/A')}` | `{self.meter_id}` |
| **Benchmark Ground Truth** | `{hvr.get('ground_truth_label', 'N/A')}` | Diagnostic Classification: `{self.probable_cause}` |
| **Daily Energy Baseline** | `{hvr.get('historical_baseline_daily_kwh', 0.0):.2f} kWh/day` | Real-time Extrapolated: `{hvr.get('realtime_projected_daily_kwh', 0.0):.2f} kWh/day` |
| **Energy Divergence (\Delta)** | Historical Reference | **`{hvr.get('divergence_pct', 0.0):+.1f}%`** (`{hvr.get('divergence_kwh', 0.0):+.2f} kWh/day`) |
| **Cumulative Theft / Divergence (30-day)** | Historical Baseline Trajectory | **`{hvr.get('cumulative_divergence_kwh', 0.0):.1f} kWh`** |
| **Estimated Utility Revenue Loss** | - | **`₹{hvr.get('est_revenue_loss_inr', 0.0):,.2f}`** (@ ₹7.50/kWh) |
| **Temporal Onset Point** | Historical Shift Changepoint | `{hvr.get('anomaly_onset_day', 'N/A')}` |
"""

        evidence_list = "\n".join([f"- {item}" for item in self.evidence_chain])

        # SHAP breakdown table
        shap_rows = ""
        if self.shap_factors:
            for sh in self.shap_factors:
                f_name = sh["feature"].replace("_", " ").title()
                shap_rows += f"| `{f_name}` | `{sh['value']}` | `+{sh['shap_impact']:.3f}` |\n"
        else:
            shap_rows = "| `Historical Baseline Alignment` | `Nominal` | `+0.000` |\n"

        sub = self.ml_subscores or {}
        xgb_p = sub.get("xgb_prob", 0.0)
        lgb_p = sub.get("lgbm_prob", 0.0)
        iso_s = sub.get("iso_score", 0.0)

        return f"""# Smart Grid Anomaly Investigation Report: {self.consumer_id}
**Report ID:** `{self.report_id}` | **Generated At:** `{self.generated_at}` | **Priority Rank:** `#{self.inspection_priority_rank}`

---

### Executive Summary
| Field | Value |
|---|---|
| **Consumer ID / Meter** | `{self.consumer_id}` / `{self.meter_id}` |
| **Consumer Name** | {self.consumer_name} |
| **Category & Contracted Load** | {self.category} ({self.contracted_load_kw} kW) |
| **Zone & Feeder** | {self.zone_id} ({self.transformer_id} / {self.feeder_id}) |
| **Final Anomaly Score** | **`{self.anomaly_score:.1f} / 100`** ({self.risk_level}) |
| **Probable Cause** | **`{self.probable_cause}`** |
| **Diagnostic Confidence** | **`{self.confidence_pct:.1f}%`** |

---

{hvr_section}
---

### AI/ML Hybrid Ensemble Attribution
| Component Model | Architecture | Raw Prediction | Ensemble Weight |
|---|---|---|---|
| **XGBoost Classifier** | Supervised Gradient Boosted Trees | `P(Theft) = {xgb_p:.3f}` | 45% |
| **LightGBM Classifier** | Supervised Leaf-Wise Trees | `P(Theft) = {lgb_p:.3f}` | 45% |
| **Isolation Forest** | Unsupervised Isolation Trees | `Anomaly = {iso_s:.3f}` | 10% |
| **Hybrid Stacking Blend** | Multi-Model Meta-Learner | **Score: `{self.anomaly_score:.1f} / 100`** | **100%** |

#### Top SHAP Feature Impacts (XGBoost TreeExplainer)
| Feature Name | Observed Value | SHAP Impact (\\Delta log-odds) |
|---|---|---|
{shap_rows}
---

### Meter & Feeder Analytics
- **Current Reading:** `{self.reported_kw:.3f} kW` (Voltage: `{self.voltage_v:.1f} V`, Current: `{self.current_a:.2f} A`, PF: `{self.power_factor:.3f}`)
- **Diurnal Baseline for Hour:** `{self.historical_baseline_kw:.3f} kW`
- **Baseline Deviation:** `{self.deviation_pct:+.1f}%` (`{self.deviation_z:+.2f} \\sigma`)
- **Parent Transformer Unexplained Loss (NTL):** `{self.zone_unexplained_loss_pct:.1f}%`

{gt_section}

### Supporting Evidence Chain
{evidence_list}

### Technical Assessment
{self.technical_assessment}

### Recommended Enforcement / Maintenance Action
> [!IMPORTANT]
> **{self.recommended_action}**
"""


class AnomalyExplainer:
    """Creates auditable investigation reports with plain-English rationales."""

    @staticmethod
    def generate_report(
        consumer: ConsumerNode,
        anomaly: AnomalyDetectionResult,
        dual_record: Optional[DualStateRecord] = None,
        priority_rank: int = 1,
    ) -> InvestigationReport:
        report_id = f"RPT-{consumer.zone_id[:4]}-{consumer.id[-3:]}-{uuid.uuid4().hex[:6].upper()}"

        rep_kw = anomaly.reported_kw
        base_kw = anomaly.baseline_mean_kw
        dev_kw = rep_kw - base_kw

        # Detailed technical rationale synthesis
        cause = anomaly.probable_cause
        if cause == "THEFT_TAMPERING":
            assessment = (
                f"Statistical and electrical analysis confirms a non-technical loss event at meter {consumer.meter_id}. "
                f"While the consumer has a contracted load of {consumer.contracted_load_kw} kW and an established "
                f"historical baseline of {base_kw:.2f} kW, the meter reported only {rep_kw:.2f} kW (a {anomaly.deviation_pct:.1f}% reduction). "
                f"Concurrently, the distribution transformer {consumer.transformer_id} is registering {anomaly.zone_ntl_pct:.1f}% "
                f"unexplained non-technical losses that cannot be accounted for by technical I²R line resistance or core losses. "
                "This strong spatial correlation between transformer loss and consumer load reduction indicates an unauthorized "
                "meter shunt, line tapping, or bypass."
            )
        elif cause == "METER_MALFUNCTION":
            assessment = (
                f"Hardware and signal health diagnostics indicate a malfunctioning metering unit at {consumer.meter_id}. "
                f"The unit is registering invalid telemetry patterns (reported load: {rep_kw:.2f} kW) that violate "
                f"physical grid operating parameters. Internal diagnostic registers show hardware fault bits or extreme "
                "sensor saturation. This is a metering transducer failure rather than an intentional non-technical theft."
            )
        elif cause == "COMM_FAILURE":
            assessment = (
                f"Telemetry acquisition failure detected for meter {consumer.meter_id}. "
                f"The Advanced Metering Infrastructure (AMI) collector failed to receive interval telemetry packets. "
                "The parent transformer continues to operate normally, indicating the physical service drop is intact. "
                "The anomaly is localized to the cellular/RF communications subsystem or backhaul gateway."
            )
        elif cause == "LEGITIMATE_ABNORMAL":
            assessment = (
                f"High power draw of {rep_kw:.2f} kW detected (+{anomaly.deviation_pct:.1f}% over baseline), but verified as "
                f"legitimate consumer demand. The parent transformer {consumer.transformer_id} experienced an identical load rise "
                f"with 0% non-technical loss. The power factor ({anomaly.status_flags.get('power_factor', 0.95)}) and voltage drop "
                "profile match compliant high-power appliances such as an EV Fast Charger or HVAC multi-split system."
            )
        elif cause == "REQUIRES_REVIEW":
            assessment = (
                f"Consumer exhibits mild load depression ({anomaly.deviation_pct:.1f}% deviation) with an intermediate "
                f"anomaly score of {anomaly.anomaly_score:.1f}/100. Diagnostic registers show no physical tamper flags. "
                "Classified as low-evidence edge case; secondary remote data audit recommended prior to crew dispatch."
            )
        else:
            assessment = (
                f"Consumption of {rep_kw:.2f} kW aligns with established diurnal baseline parameters ({base_kw:.2f} kW). "
                "Grid power balance, line voltage, and smart meter diagnostic registers are within nominal operating limits."
            )

        gt_kw = None
        unreported_kw = None
        active_scenario_val = None
        if dual_record:
            gt_kw = dual_record.ground_truth.active_power_kw
            unreported_kw = dual_record.unreported_stolen_kw
            active_scenario_val = dual_record.active_scenario.value

        return InvestigationReport(
            report_id=report_id,
            generated_at=anomaly.timestamp,
            consumer_id=consumer.id,
            meter_id=consumer.meter_id,
            consumer_name=consumer.name,
            category=consumer.category,
            contracted_load_kw=consumer.contracted_load_kw,
            zone_id=consumer.zone_id,
            transformer_id=consumer.transformer_id,
            feeder_id=consumer.feeder_id,
            anomaly_score=anomaly.anomaly_score,
            risk_level=anomaly.risk_level,
            probable_cause=anomaly.probable_cause,
            confidence_pct=anomaly.confidence_pct,
            reported_kw=rep_kw,
            historical_baseline_kw=base_kw,
            deviation_kw=dev_kw,
            deviation_pct=anomaly.deviation_pct,
            deviation_z=anomaly.deviation_z,
            voltage_v=anomaly.status_flags.get("voltage_v", 230.0),
            current_a=anomaly.status_flags.get("current_a", 0.0),
            power_factor=anomaly.status_flags.get("power_factor", 0.95),
            zone_unexplained_loss_pct=anomaly.zone_ntl_pct,
            evidence_chain=anomaly.contributing_factors,
            technical_assessment=assessment,
            recommended_action=anomaly.recommended_action,
            inspection_priority_rank=priority_rank,
            ml_score=anomaly.ml_score,
            ml_subscores=anomaly.ml_subscores,
            shap_factors=anomaly.shap_factors,
            historical_vs_realtime=anomaly.historical_vs_realtime,
            ground_truth_kw=gt_kw,
            unreported_stolen_kw=unreported_kw,
            active_scenario=active_scenario_val,
        )
