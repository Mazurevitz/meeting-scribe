"""Auto-record monitor for Zoom and Teams calls.

Detection strategy:
1. Check if call audio devices exist (Zoom/Teams virtual devices)
2. Check if call-specific subprocess is running (CptHost, teams2.call)
3. Require both conditions for 2 consecutive polls before triggering

This avoids false triggers when Teams/Zoom is open but not in a call.
"""

import logging
import subprocess
import threading
from datetime import datetime
from typing import Callable, Optional

import sounddevice as sd

log = logging.getLogger(__name__)


# How many consecutive active polls before triggering a call start
_CONFIRM_POLLS = 2


class CallMonitor:
    """Monitors for Zoom/Teams calls and triggers recording.

    Uses a two-step detection:
    1. Check if call audio devices exist (Zoom/Teams virtual devices)
    2. Check if the call process is actively using audio via macOS APIs

    This avoids false triggers when Teams/Zoom is open but idle.
    """

    CALL_AUDIO_DEVICES = {
        "ZoomAudioDevice",
        "Microsoft Teams Audio",
    }

    # Process names that indicate an active call (not just the app running)
    # These are child processes spawned only during active calls
    CALL_INDICATOR_PROCESSES = [
        "CptHost",                  # Teams calling host process
        "com.microsoft.teams2.call",  # Teams new arch call process
    ]

    def __init__(
        self,
        on_call_start: Optional[Callable[[], None]] = None,
        on_call_end: Optional[Callable[[], None]] = None,
        weekdays_only: bool = True,
        poll_interval: float = 5.0,
    ):
        self.on_call_start = on_call_start
        self.on_call_end = on_call_end
        self.weekdays_only = weekdays_only
        self.poll_interval = poll_interval

        self._enabled = False
        self._monitoring = False
        self._in_call = False
        self._active_count = 0
        self._silent_count = 0
        self._consecutive_errors = 0
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _has_call_audio_device(self) -> bool:
        """Check if any call audio device is registered."""
        try:
            devices = sd.query_devices()
            for device in devices:
                if device["max_input_channels"] > 0:
                    for call_device in self.CALL_AUDIO_DEVICES:
                        if call_device in device["name"]:
                            return True
            self._consecutive_errors = 0
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                log.warning("Device query error: %s", e)
        return False

    def _has_active_call_process(self) -> bool:
        """Check if a call-specific subprocess is running.

        Teams and Zoom spawn specific processes only during active calls.
        This is more reliable than checking the audio device which is
        always registered when the app is open.
        """
        try:
            # Check for Zoom active meeting window
            result = subprocess.run(
                ["pgrep", "-f", "zoom.*meeting|CptHost|teams2.*call"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except Exception:
            pass

        # Fallback: check macOS audio server for active audio streams
        try:
            # lsof checks if Zoom/Teams have open audio file descriptors
            result = subprocess.run(
                ["lsof", "-c", "zoom", "-c", "Teams", "-a", "+D", "/dev"],
                capture_output=True, text=True, timeout=3,
            )
            # If there are audio device handles, a call is likely active
            if "audio" in result.stdout.lower():
                return True
        except Exception:
            pass

        return False

    def _is_call_active(self) -> bool:
        """Detect active call. Requires both device presence AND active process."""
        if not self._has_call_audio_device():
            return False
        return self._has_active_call_process()

    def _is_weekday(self) -> bool:
        return datetime.now().weekday() < 5

    def _should_monitor(self) -> bool:
        if not self._enabled:
            return False
        if self.weekdays_only and not self._is_weekday():
            return False
        return True

    def _monitor_loop(self):
        """Background thread that monitors for calls."""
        while not self._stop_event.is_set():
            try:
                if self._should_monitor():
                    call_active = self._is_call_active()

                    if call_active:
                        self._silent_count = 0
                        self._active_count += 1
                    else:
                        self._active_count = 0
                        if self._in_call:
                            self._silent_count += 1

                    # Require consecutive active polls to start
                    if self._active_count >= _CONFIRM_POLLS and not self._in_call:
                        self._in_call = True
                        self._silent_count = 0
                        if self.on_call_start:
                            try:
                                self.on_call_start()
                            except Exception as e:
                                log.error("Callback error: %s", e)

                    # Require consecutive silent polls to end
                    elif self._silent_count >= _CONFIRM_POLLS and self._in_call:
                        self._in_call = False
                        self._active_count = 0
                        if self.on_call_end:
                            try:
                                self.on_call_end()
                            except Exception as e:
                                log.error("Callback error: %s", e)

            except Exception as e:
                log.error("Monitor loop error: %s", e)

            self._stop_event.wait(self.poll_interval)

    def start_monitoring(self):
        """Start the monitoring thread."""
        if self._monitoring:
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._safe_monitor_loop, daemon=True
        )
        self._monitor_thread.start()
        self._monitoring = True

    def _safe_monitor_loop(self):
        """Wrapper that restarts _monitor_loop on crash."""
        while not self._stop_event.is_set():
            try:
                self._monitor_loop()
            except Exception as e:
                log.error("Monitor thread crashed, restarting in 5s: %s", e)
                self._stop_event.wait(5.0)

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
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @property
    def in_call(self) -> bool:
        return self._in_call

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring
