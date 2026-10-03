"""
Energy Accounting Engine & Non-Technical Loss (NTL) Auditor.
Calculates energy balance at Substation, Feeder, and Transformer levels.
Differentiates physical technical losses from unexplained non-technical theft/losses.
Tracks: Power Inputted vs Meters Added Up in the zone ("If it's not adding up, it's done for!").
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from config import CONFIG
from models.topology import TransformerNode
from models.telemetry import DualStateRecord
from models.electrical import TechnicalLossCalculator


@dataclass
class TransformerLossReport:
    """Detailed real-time energy accounting balance for a single distribution transformer zone."""
    transformer_id: str
    zone_id: str
    timestamp: str
    transformer_input_kw: float           # Current power input into zone (kW)
    consumer_true_load_kw: float          # Sum of true physical consumer consumption (kW)
    consumer_reported_load_kw: float      # Sum of reported meter consumption (kW)
    technical_losses_kw: float            # Allowed physical I^2*R copper + transformer core loss (kW)
    technical_loss_pct: float             # Tech loss as % of transformer input
    unexplained_loss_kw: float            # Non-Technical Loss / Theft (kW)
    unexplained_loss_pct: float           # NTL as % of transformer input
    reporting_consumers: int              # Meters that reported in this interval
    total_consumers: int                  # Total connected meters
    reporting_completeness_pct: float
    status: str                           # "OPTIMAL", "TECHNICAL_LOSS_HIGH", "SUSPICIOUS_NTL", "CRITICAL_THEFT_CLUSTER"
    
    # Cumulative Energy Accounting (Inputted vs Meters Added Up in kWh)
    cumulative_energy_input_kwh: float = 0.0
    cumulative_reported_kwh: float = 0.0
    cumulative_tech_loss_kwh: float = 0.0
    cumulative_unexplained_kwh: float = 0.0
    is_done_for: bool = False
    status_label: str = "BALANCED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transformer_id": self.transformer_id,
            "zone_id": self.zone_id,
            "timestamp": self.timestamp,
            "transformer_input_kw": round(self.transformer_input_kw, 2),
            "consumer_true_load_kw": round(self.consumer_true_load_kw, 2),
            "consumer_reported_load_kw": round(self.consumer_reported_load_kw, 2),
            "technical_losses_kw": round(self.technical_losses_kw, 2),
            "technical_loss_pct": round(self.technical_loss_pct, 2),
            "unexplained_loss_kw": round(self.unexplained_loss_kw, 2),
            "unexplained_loss_pct": round(self.unexplained_loss_pct, 2),
            "reporting_consumers": self.reporting_consumers,
            "total_consumers": self.total_consumers,
            "reporting_completeness_pct": round(self.reporting_completeness_pct, 1),
            "status": self.status,
            # Prominent Accounting Totals
            "power_inputted_kwh": round(self.cumulative_energy_input_kwh, 2),
            "meters_added_kwh": round(self.cumulative_reported_kwh, 2),
            "tech_loss_kwh": round(self.cumulative_tech_loss_kwh, 2),
            "missing_kwh": round(self.cumulative_unexplained_kwh, 2),
            "missing_pct": round((self.cumulative_unexplained_kwh / max(0.1, self.cumulative_energy_input_kwh)) * 100.0, 1),
            "is_done_for": self.is_done_for,
            "status_label": self.status_label,
            "reconciliation_summary": (
                f"Inputted: {self.cumulative_energy_input_kwh:.1f} kWh | "
                f"Meters Added: {self.cumulative_reported_kwh:.1f} kWh | "
                f"Tech Loss: {self.cumulative_tech_loss_kwh:.1f} kWh | "
                f"Missing: {self.cumulative_unexplained_kwh:.1f} kWh ({self.status_label})"
            ),
        }


class EnergyAccountingEngine:
    """Performs real-time energy reconciliation across transformer zones."""

    def __init__(self):
        self.loss_calc = TechnicalLossCalculator()
        # transformer_id -> cumulative kWh counters
        self.cumulative_input_kwh: Dict[str, float] = {}
        self.cumulative_reported_kwh: Dict[str, float] = {}
        self.cumulative_tech_loss_kwh: Dict[str, float] = {}
        self.cumulative_unexplained_kwh: Dict[str, float] = {}

    def calculate_transformer_balance(
        self,
        transformer: TransformerNode,
        consumer_records: List[DualStateRecord],
        timestamp: str,
        interval_hours: float = 0.25, # 15 minutes = 0.25h
    ) -> TransformerLossReport:
        """
        Calculates energy balance for the given transformer using the latest tick records.
        """
        tx_id = transformer.id
        if tx_id not in self.cumulative_input_kwh:
            self.cumulative_input_kwh[tx_id] = 0.0
            self.cumulative_reported_kwh[tx_id] = 0.0
            self.cumulative_tech_loss_kwh[tx_id] = 0.0
            self.cumulative_unexplained_kwh[tx_id] = 0.0

        # Sum true physical consumption and line losses
        total_true_load_kw = 0.0
        total_line_loss_kw = 0.0
        total_reactive_kvar = 0.0
        total_reported_kw = 0.0
        reporting_count = 0

        for rec in consumer_records:
            total_true_load_kw += rec.ground_truth.active_power_kw
            total_line_loss_kw += rec.line_loss_kw
            total_reactive_kvar += rec.ground_truth.reactive_power_kvar

            # Reported by meter (if received and not missing)
            if rec.reported is not None and not rec.reported.is_missing:
                total_reported_kw += rec.reported.active_power_kw
                reporting_count += 1

        # Transformer internal losses (core + copper)
        tx_internal_loss_kw = self.loss_calc.compute_transformer_technical_loss(
            total_active_load_kw=total_true_load_kw,
            total_reactive_load_kvar=total_reactive_kvar,
            transformer_capacity_kva=transformer.capacity_kva,
        )

        total_technical_loss_kw = total_line_loss_kw + tx_internal_loss_kw
        # True physical input measured by the bulk distribution transformer meter
        transformer_input_kw = total_true_load_kw + total_technical_loss_kw

        # Unexplained loss = Physical Intake - Reported Sum - Technical Losses
        discrepancy_kw = max(0.0, transformer_input_kw - total_reported_kw - total_technical_loss_kw)

        # Update cumulative kWh counters
        self.cumulative_input_kwh[tx_id] += transformer_input_kw * interval_hours
        self.cumulative_reported_kwh[tx_id] += total_reported_kw * interval_hours
        self.cumulative_tech_loss_kwh[tx_id] += total_technical_loss_kw * interval_hours
        self.cumulative_unexplained_kwh[tx_id] += discrepancy_kw * interval_hours

        # Percentage metrics
        denom = max(0.1, transformer_input_kw)
        tech_loss_pct = (total_technical_loss_kw / denom) * 100.0
        unexplained_loss_pct = (discrepancy_kw / denom) * 100.0
        completeness_pct = (reporting_count / max(1, len(consumer_records))) * 100.0

        # Determine Zone Status: "If it's not adding up, it's done for!"
        is_done_for = unexplained_loss_pct >= CONFIG.TRANSFORMER_UNEXPLAINED_LOSS_ALERT_PCT

        if unexplained_loss_pct > CONFIG.TRANSFORMER_UNEXPLAINED_LOSS_ALERT_PCT * 1.8:
            status = "CRITICAL_THEFT_CLUSTER"
            status_label = "CRITICAL LEAKAGE (DONE FOR!)"
        elif unexplained_loss_pct > CONFIG.TRANSFORMER_UNEXPLAINED_LOSS_ALERT_PCT:
            status = "SUSPICIOUS_NTL"
            status_label = "DISCREPANCY DETECTED (DONE FOR!)"
        elif tech_loss_pct > 12.0:
            status = "TECHNICAL_LOSS_HIGH"
            status_label = "HIGH LINE LOSS"
        else:
            status = "OPTIMAL"
            status_label = "BALANCED & VERIFIED"

        return TransformerLossReport(
            transformer_id=tx_id,
            zone_id=transformer.zone_id,
            timestamp=timestamp,
            transformer_input_kw=transformer_input_kw,
            consumer_true_load_kw=total_true_load_kw,
            consumer_reported_load_kw=total_reported_kw,
            technical_losses_kw=total_technical_loss_kw,
            technical_loss_pct=tech_loss_pct,
            unexplained_loss_kw=discrepancy_kw,
            unexplained_loss_pct=unexplained_loss_pct,
            reporting_consumers=reporting_count,
            total_consumers=len(consumer_records),
            reporting_completeness_pct=completeness_pct,
            status=status,
            cumulative_energy_input_kwh=self.cumulative_input_kwh[tx_id],
            cumulative_reported_kwh=self.cumulative_reported_kwh[tx_id],
            cumulative_tech_loss_kwh=self.cumulative_tech_loss_kwh[tx_id],
            cumulative_unexplained_kwh=self.cumulative_unexplained_kwh[tx_id],
            is_done_for=is_done_for,
            status_label=status_label,
        )
