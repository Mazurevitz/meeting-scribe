"""Auto-record monitor for Zoom and Teams calls."""

import threading
import time
from datetime import datetime
from typing import Callable, Optional, Set

import sounddevice as sd


class CallMonitor:
    """Monitors for Zoom/Teams calls and triggers recording."""

    CALL_AUDIO_DEVICES = {
        "ZoomAudioDevice",
        "Microsoft Teams Audio",
    }

    def __init__(
        self,
        on_call_start: Optional[Callable[[], None]] = None,
        on_call_end: Optional[Callable[[], None]] = None,
        weekdays_only: bool = True,
        poll_interval: float = 3.0,
    ):
        self.on_call_start = on_call_start
        self.on_call_end = on_call_end
        self.weekdays_only = weekdays_only
        self.poll_interval = poll_interval

        self._enabled = False
        self._monitoring = False
        self._in_call = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _get_active_call_devices(self) -> Set[str]:
        """Get currently active call audio devices."""
        active = set()
        try:
            devices = sd.query_devices()
            for device in devices:
                name = device["name"]
                if device["max_input_channels"] > 0:
                    for call_device in self.CALL_AUDIO_DEVICES:
                        if call_device in name:
                            active.add(call_device)
        except Exception:
            pass
        return active

    def _is_weekday(self) -> bool:
        """Check if today is a weekday (Monday=0 to Friday=4)."""
        return datetime.now().weekday() < 5

    def _should_monitor(self) -> bool:
        """Check if we should be monitoring for calls."""
        if not self._enabled:
            return False
        if self.weekdays_only and not self._is_weekday():
            return False
        return True

    def _monitor_loop(self):
        """Background thread that monitors for calls."""
        while not self._stop_event.is_set():
            if self._should_monitor():
                active_devices = self._get_active_call_devices()
                call_active = len(active_devices) > 0

                if call_active and not self._in_call:
                    self._in_call = True
                    if self.on_call_start:
                        try:
                            self.on_call_start()
                        except Exception as e:
                            print(f"Error in on_call_start: {e}")

                elif not call_active and self._in_call:
                    self._in_call = False
                    if self.on_call_end:
                        try:
                            self.on_call_end()
                        except Exception as e:
                            print(f"Error in on_call_end: {e}")

            self._stop_event.wait(self.poll_interval)

    def start_monitoring(self):
        """Start the monitoring thread."""
        if self._monitoring:
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self._monitoring = True

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        if not self._monitoring:
            return

        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        self._monitoring = False

    @property
    def enabled(self) -> bool:
        """Check if auto-record is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable auto-record."""
        self._enabled = value

    @property
    def in_call(self) -> bool:
        """Check if currently in a call."""
        return self._in_call

    @property
    def is_monitoring(self) -> bool:
        """Check if monitoring is active."""
        return self._monitoring
