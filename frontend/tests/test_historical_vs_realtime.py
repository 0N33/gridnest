"""
Unit tests for Historical vs. Real-Time Benchmark Analysis Engine.
Verifies authentic Kaggle CONS_NO binding, 30-day baseline comparisons,
divergence/financial loss estimates, and court-ready markdown reports.
"""
import unittest
from engine.digital_twin import SmartGridDigitalTwin


class TestHistoricalVsRealTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.twin = SmartGridDigitalTwin()
        cls.twin.initialize(setup_scenarios=True)

    def test_snapshot_contains_historical_vs_realtime(self):
        snapshot = self.twin.get_snapshot()
        self.assertIn("consumers", snapshot)
        self.assertEqual(len(snapshot["consumers"]), 48)

        # Check CONS_N_004 (Theft Bypass)
        c004 = snapshot["consumers"].get("CONS_N_004")
        self.assertIsNotNone(c004)
        analysis = c004.get("analysis")
        self.assertIsNotNone(analysis)
        self.assertIn("historical_vs_realtime", analysis)

        hvr = analysis["historical_vs_realtime"]
        self.assertEqual(hvr["kaggle_flag"], 1)
        self.assertTrue(len(hvr["kaggle_id"]) > 10)
        self.assertGreater(hvr["historical_baseline_daily_kwh"], 0.0)
        self.assertIn("trend_30d", hvr)
        self.assertGreaterEqual(len(hvr["trend_30d"]), 10)
        self.assertLess(hvr["divergence_pct"], -30.0)
        self.assertGreater(hvr["est_revenue_loss_inr"], 0.0)

    def test_normal_consumer_historical_alignment(self):
        snapshot = self.twin.get_snapshot()
        c001 = snapshot["consumers"].get("CONS_N_001")
        self.assertIsNotNone(c001)
        hvr = c001["analysis"]["historical_vs_realtime"]
        self.assertEqual(hvr["kaggle_flag"], 0)
        self.assertGreater(hvr["historical_baseline_daily_kwh"], 0.0)
        self.assertIn("trend_30d", hvr)

    def test_investigation_report_markdown_contains_hvr_audit(self):
        report = self.twin.generate_investigation_report("CONS_N_004")
        self.assertIsNotNone(report)
        md = report.to_markdown()

        self.assertIn("Historical Benchmark vs. Real-Time Telemetry Audit", md)
        self.assertIn("State Grid Corp China (`data.csv`)", md)
        self.assertIn("Kaggle Consumer Hash", md)
        self.assertIn("Cumulative Theft / Divergence", md)
        self.assertIn("Estimated Utility Revenue Loss", md)

        structured = report.to_dict()
        self.assertIn("historical_vs_realtime", structured)
        self.assertEqual(structured["historical_vs_realtime"]["kaggle_flag"], 1)


if __name__ == "__main__":
    unittest.main()
