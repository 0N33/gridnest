"""
Virtual Simulation Clock.
Supports real-time ticking, discrete event stepping, time acceleration,
and synchronization between physical grid processes and smart meter interval reporting.
"""
from __future__ import annotations
import datetime
from typing import Dict, Any, Optional
from config import CONFIG


class SimulationClock:
    """Controls simulated calendar time and interval progression."""

    def __init__(
        self,
        start_datetime: Optional[datetime.datetime] = None,
        step_minutes: int = CONFIG.REPORTING_INTERVAL_MINS,
    ):
        if start_datetime is None:
            # Start at a realistic weekday morning
            self.current_time = datetime.datetime(2026, 10, 5, 6, 0, 0)
        else:
            self.current_time = start_datetime

        self.step_delta = datetime.timedelta(minutes=step_minutes)
        self.step_minutes = step_minutes
        self.tick_count = 0
        self.is_paused = False

    def tick(self) -> datetime.datetime:
        """Advance time by one reporting interval (default 15 mins)."""
        if not self.is_paused:
            self.current_time += self.step_delta
            self.tick_count += 1
        return self.current_time

    def step_forward(self, steps: int = 1) -> datetime.datetime:
        """Manually advance clock by N steps."""
        self.current_time += self.step_delta * steps
        self.tick_count += steps
        return self.current_time

    @property
    def hour_float(self) -> float:
        """Returns hour as float (e.g., 14.5 for 2:30 PM)."""
        return self.current_time.hour + self.current_time.minute / 60.0 + self.current_time.second / 3600.0

    @property
    def is_weekend(self) -> bool:
        """Saturday (5) or Sunday (6)."""
        return self.current_time.weekday() in [5, 6]

    @property
    def iso_format(self) -> str:
        return self.current_time.isoformat()

    def get_time_state(self) -> Dict[str, Any]:
        return {
            "iso_time": self.iso_format,
            "tick": self.tick_count,
            "hour": self.current_time.hour,
            "minute": self.current_time.minute,
            "hour_float": round(self.hour_float, 2),
            "day_name": self.current_time.strftime("%A"),
            "date": self.current_time.strftime("%Y-%m-%d"),
            "is_weekend": self.is_weekend,
            "is_paused": self.is_paused,
            "step_minutes": self.step_minutes,
        }
