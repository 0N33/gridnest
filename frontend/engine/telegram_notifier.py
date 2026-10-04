"""
Telegram Notification Engine for GridNest Smart Grid.
Dispatches instant, real-time alert messages to utility dispatchers/admins
when critical power theft or anomalous energy deficits are detected.
"""
import os
import json
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional
from pathlib import Path


class TelegramNotifier:
    """Dispatches formatted alert notifications to Telegram groups or individual chats."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        alert_threshold: float = 75.0,
        cooldown_seconds: float = 300.0,  # 5 min cooldown per node to prevent spam
    ):
        try:
            from config import CONFIG
            cfg_token = getattr(CONFIG, "TELEGRAM_BOT_TOKEN", "")
            cfg_chat = getattr(CONFIG, "TELEGRAM_CHAT_ID", "")
        except Exception:
            cfg_token, cfg_chat = "", ""

        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or cfg_token.strip()
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip() or cfg_chat.strip()
        self.alert_threshold = alert_threshold
        self.cooldown_seconds = cooldown_seconds
        
        # Track last alert timestamp per entity to prevent alert storms: entity_id -> timestamp
        self._last_alert_time: Dict[str, float] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def update_credentials(self, bot_token: str, chat_id: str):
        """Dynamically update bot credentials at runtime."""
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    def send_message(self, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
        """
        Sends an HTTP POST request to Telegram's sendMessage API.
        Uses pure standard library urllib - zero external pip dependencies needed.
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "Telegram Bot Token or Chat ID not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
            }

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        last_err = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    resp_body = resp.read().decode("utf-8")
                    res_json = json.loads(resp_body)
                    return {"success": True, "result": res_json}
            except urllib.error.HTTPError as e:
                err_msg = e.read().decode("utf-8")
                return {"success": False, "error": f"HTTP {e.code}: {err_msg}"}
            except Exception as e:
                last_err = str(e)
                time.sleep(1.0)

        return {"success": False, "error": f"Failed after 3 attempts: {last_err}"}

    def check_and_alert_consumer_anomaly(
        self,
        consumer_id: str,
        anomaly_score: float,
        probable_cause: str,
        reported_kw: float,
        true_kw: float,
        zone: str = "Zone 1 (TX-101)",
        consumer_name: str = "",
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates an anomaly score. If >= alert_threshold and outside cooldown,
        dispatches a structured theft incident dossier to Telegram.
        """
        if anomaly_score < self.alert_threshold and not force:
            return None

        # Cooldown check
        now = time.time()
        last_sent = self._last_alert_time.get(consumer_id, 0.0)
        if (now - last_sent < self.cooldown_seconds) and not force:
            return None  # Cooldown active, suppress duplicate alert

        diverted_kw = max(0.0, true_kw - reported_kw)
        loss_pct = (diverted_kw / (true_kw + 1e-4) * 100.0) if true_kw > 0 else 0.0

        risk_emoji = "🚨" if anomaly_score >= 85 else "⚠️"
        risk_level = "CRITICAL THEFT" if anomaly_score >= 85 else "SUSPICIOUS DEFICIT"

        msg = (
            f"{risk_emoji} <b>GRIDNEST SCADA ALERT: {risk_level}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Node ID:</b> <code>{consumer_id}</code>\n"
            f"🏢 <b>Target:</b> {consumer_name or consumer_id}\n"
            f"⚡ <b>Feeder Sector:</b> {zone}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Threat Score:</b> <b>{anomaly_score:.1f} / 100</b>\n"
            f"🔍 <b>Probable Cause:</b> <code>{probable_cause}</code>\n"
            f"📊 <b>Reported Load:</b> {reported_kw:.2f} kW\n"
            f"⚡ <b>True Physical Load:</b> {true_kw:.2f} kW\n"
            f"📉 <b>Unmetered Power Diverted:</b> <b>{diverted_kw:.2f} kW ({loss_pct:.1f}%)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛠️ <b>Action Mandated:</b> Dispatch field inspection squad immediately. Check physical meter shunt tap / meter seal integrity.\n"
            f"⏱️ <i>Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</i>"
        )

        res = self.send_message(msg)
        if res.get("success"):
            self._last_alert_time[consumer_id] = now
        return res

    def check_and_alert_transformer_loss(
        self,
        tx_id: str,
        ntl_percentage: float,
        supplied_kw: float,
        metered_kw: float,
        unexplained_loss_kw: float,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Dispatches an alert if a transformer's Non-Technical Loss (NTL) exceeds the critical 6% limit.
        """
        if ntl_percentage < 6.0 and not force:
            return None

        now = time.time()
        last_sent = self._last_alert_time.get(tx_id, 0.0)
        if (now - last_sent < self.cooldown_seconds) and not force:
            return None

        msg = (
            f"⚡ <b>GRIDNEST FEEDER ALERT: MASS-BALANCE VIOLATION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔌 <b>Transformer:</b> <code>{tx_id}</code>\n"
            f"🚨 <b>Feeder NTL:</b> <b>{ntl_percentage:.2f}%</b> (Threshold: > 6.0%)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>Bulk Intake Supplied:</b> {supplied_kw:.2f} kW\n"
            f"📤 <b>Sum Metered Consumption:</b> {metered_kw:.2f} kW\n"
            f"⚠️ <b>Unexplained Grid Leakage:</b> <b>{unexplained_loss_kw:.2f} kW</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚁 <b>Autonomous Drone:</b> Dispatching aerial thermographic feeder audit.\n"
            f"⏱️ <i>Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</i>"
        )

        res = self.send_message(msg)
        if res.get("success"):
            self._last_alert_time[tx_id] = now
        return res


# Global singleton
TELEGRAM_NOTIFIER = TelegramNotifier()


if __name__ == "__main__":
    import sys
    print("Testing TelegramNotifier...")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[INFO] To test live dispatch, run with environment variables:")
        print("  $env:TELEGRAM_BOT_TOKEN='your_token'")
        print("  $env:TELEGRAM_CHAT_ID='your_chat_id'")
        print("  python frontend/engine/telegram_notifier.py")
    else:
        notifier = TelegramNotifier(token, chat)
        res = notifier.check_and_alert_consumer_anomaly(
            consumer_id="CONS_N_004",
            anomaly_score=94.5,
            probable_cause="PHYSICAL_SHUNT_TAP",
            reported_kw=0.75,
            true_kw=3.85,
            zone="Zone 1 (TX-101 North)",
            consumer_name="Building 4 (Commercial Test Node)",
            force=True
        )
        print("Dispatch result:", res)
