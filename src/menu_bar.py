"""Menu bar application using rumps."""

import threading
from pathlib import Path
from typing import Optional
import rumps

from .audio import AudioRecorder, AudioDeviceManager
from .transcription import WhisperTranscriber
from .summarization import OllamaClient
from .storage import FileManager
from .auto_record import CallMonitor
from .config import Config


class MeetingRecorderApp(rumps.App):
    """Menu bar application for recording and processing meetings."""

    def __init__(self):
        super().__init__(
            name="Meeting Recorder",
            title="🎙",
            quit_button=None
        )

        self.config = Config()
        self.recorder = AudioRecorder()
        self.device_manager = AudioDeviceManager()
        self.transcriber = WhisperTranscriber(model_name=self.config.whisper_model)
        self.ollama = OllamaClient(model=self.config.ollama_model)
        self.file_manager = FileManager()

        self._recording_timer: Optional[rumps.Timer] = None
        self._processing = False
        self._auto_recorded = False
        self._current_recording_path: Optional[Path] = None

        self.call_monitor = CallMonitor(
            on_call_start=self._on_call_start,
            on_call_end=self._on_call_end,
            weekdays_only=True,
            poll_interval=3.0,
        )
        self.call_monitor.enabled = self.config.auto_record_enabled
        self.call_monitor.start_monitoring()

        self._build_menu()

    def _build_menu(self):
        """Build the menu bar menu."""
        self._auto_record_item = rumps.MenuItem(
            "Auto-Record Calls (Mon-Fri)",
            callback=self._toggle_auto_record
        )
        self._auto_record_item.state = 1 if self.config.auto_record_enabled else 0

        self._auto_transcribe_item = rumps.MenuItem(
            "Auto-Transcribe",
            callback=self._toggle_auto_transcribe
        )
        self._auto_transcribe_item.state = 1 if self.config.auto_transcribe else 0

        self._auto_summarize_item = rumps.MenuItem(
            "Auto-Summarize",
            callback=self._toggle_auto_summarize
        )
        self._auto_summarize_item.state = 1 if self.config.auto_summarize else 0

        self.menu = [
            rumps.MenuItem("Start Recording", callback=self._toggle_recording),
            None,
            self._auto_record_item,
            self._auto_transcribe_item,
            self._auto_summarize_item,
            None,
            rumps.MenuItem("Transcribe Latest", callback=self._transcribe_latest),
            rumps.MenuItem("Summarize Latest", callback=self._summarize_latest),
            None,
            self._build_devices_menu(),
            None,
            rumps.MenuItem("Open Recordings Folder", callback=self._open_folder),
            None,
            self._build_status_menu(),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _build_devices_menu(self) -> rumps.MenuItem:
        """Build the device selection submenu."""
        devices_menu = rumps.MenuItem("Devices")

        mic_menu = rumps.MenuItem("Microphone")
        mics = self.device_manager.get_microphone_devices()
        default_mic = self.device_manager.get_default_microphone()

        for mic in mics:
            item = rumps.MenuItem(
                mic.name,
                callback=lambda sender, d=mic: self._select_mic(sender, d)
            )
            if default_mic and mic.index == default_mic.index:
                item.state = 1
                self.recorder.set_microphone(mic)
            mic_menu.add(item)

        devices_menu.add(mic_menu)

        blackhole = self.device_manager.get_blackhole_device()
        if blackhole:
            bh_item = rumps.MenuItem(f"System Audio: {blackhole.name}")
            bh_item.state = 1
            self.recorder.set_system_audio_device(blackhole)
        else:
            bh_item = rumps.MenuItem("System Audio: Not Available")
            bh_item.set_callback(None)
        devices_menu.add(bh_item)

        return devices_menu

    def _build_status_menu(self) -> rumps.MenuItem:
        """Build the status submenu."""
        status_menu = rumps.MenuItem("Status")

        blackhole = self.device_manager.get_blackhole_device()
        bh_status = "✓ Installed" if blackhole else "✗ Not Found"
        status_menu.add(rumps.MenuItem(f"BlackHole: {bh_status}"))

        ollama_status = "✓ Running" if self.ollama.is_available() else "✗ Not Running"
        status_menu.add(rumps.MenuItem(f"Ollama: {ollama_status}"))

        if self.ollama.is_available():
            models = self.ollama.list_models()
            model_str = ", ".join(models[:3]) if models else "None"
            if len(models) > 3:
                model_str += f" (+{len(models) - 3})"
            status_menu.add(rumps.MenuItem(f"Models: {model_str}"))

        return status_menu

    def _select_mic(self, sender, device):
        """Handle microphone selection."""
        for item in sender.parent.values():
            if isinstance(item, rumps.MenuItem):
                item.state = 0
        sender.state = 1
        self.recorder.set_microphone(device)

    def _toggle_auto_record(self, sender):
        """Toggle auto-record on/off."""
        self.call_monitor.enabled = not self.call_monitor.enabled
        self.config.auto_record_enabled = self.call_monitor.enabled
        sender.state = 1 if self.call_monitor.enabled else 0

        status = "enabled" if self.call_monitor.enabled else "disabled"
        rumps.notification(
            title="Auto-Record",
            subtitle="",
            message=f"Auto-record for Zoom/Teams calls {status} (Mon-Fri)"
        )

    def _toggle_auto_transcribe(self, sender):
        """Toggle auto-transcribe on/off."""
        self.config.auto_transcribe = not self.config.auto_transcribe
        sender.state = 1 if self.config.auto_transcribe else 0

    def _toggle_auto_summarize(self, sender):
        """Toggle auto-summarize on/off."""
        self.config.auto_summarize = not self.config.auto_summarize
        sender.state = 1 if self.config.auto_summarize else 0

    def _on_call_start(self):
        """Called when a Zoom/Teams call is detected."""
        if self.recorder.is_recording:
            return

        self._auto_recorded = True
        record_item = self.menu.get("Start Recording")
        if record_item:
            self._start_recording(record_item)

        rumps.notification(
            title="Auto-Recording Started",
            subtitle="Call detected",
            message="Recording Zoom/Teams call automatically"
        )

    def _on_call_end(self):
        """Called when a Zoom/Teams call ends."""
        if not self.recorder.is_recording:
            return

        if not self._auto_recorded:
            return

        self._auto_recorded = False
        record_item = self.menu.get("Start Recording")
        if record_item:
            self._stop_recording(record_item)

    def _toggle_recording(self, sender):
        """Toggle recording on/off."""
        if self.recorder.is_recording:
            self._auto_recorded = False
            self._stop_recording(sender)
        else:
            self._start_recording(sender)

    def _start_recording(self, sender):
        """Start recording."""
        try:
            filepath = self.recorder.start_recording()
            self._current_recording_path = filepath
            sender.title = "Stop Recording"
            self.title = "🔴 00:00"

            self._recording_timer = rumps.Timer(self._update_duration, 1)
            self._recording_timer.start()

            rumps.notification(
                title="Recording Started",
                subtitle="",
                message=f"Saving to: {filepath.name}"
            )
        except Exception as e:
            rumps.notification(
                title="Recording Error",
                subtitle="",
                message=str(e)
            )

    def _stop_recording(self, sender):
        """Stop recording."""
        try:
            if self._recording_timer:
                self._recording_timer.stop()
                self._recording_timer = None

            filepath = self.recorder.stop_recording()
            self._current_recording_path = filepath
            sender.title = "Start Recording"
            self.title = "🎙"

            rumps.notification(
                title="Recording Saved",
                subtitle="",
                message=f"Saved: {filepath.name}"
            )

            # Auto-process pipeline
            if self.config.auto_transcribe:
                self._auto_process_recording(filepath)

        except Exception as e:
            self.title = "🎙"
            rumps.notification(
                title="Recording Error",
                subtitle="",
                message=str(e)
            )

    def _auto_process_recording(self, audio_path: Path):
        """Auto-transcribe and optionally summarize a recording."""
        if self._processing:
            return

        self._processing = True
        self.title = "⏳"

        def process():
            try:
                # Transcribe
                rumps.notification(
                    title="Auto-Transcribing...",
                    subtitle="",
                    message=f"Processing: {audio_path.name}"
                )

                text = self.transcriber.transcribe(audio_path)
                transcript_path = audio_path.with_suffix(".txt")

                rumps.notification(
                    title="Transcription Complete",
                    subtitle="",
                    message=f"Saved: {transcript_path.name}"
                )

                # Summarize if enabled
                if self.config.auto_summarize and self.ollama.is_available():
                    rumps.notification(
                        title="Auto-Summarizing...",
                        subtitle="",
                        message=f"Processing: {transcript_path.name}"
                    )

                    self.ollama.summarize_transcript_file(transcript_path)

                    rumps.notification(
                        title="Summary Complete",
                        subtitle="",
                        message=f"Meeting processed: {audio_path.stem}"
                    )
                elif self.config.auto_summarize and not self.ollama.is_available():
                    rumps.notification(
                        title="Summarization Skipped",
                        subtitle="",
                        message="Ollama not running"
                    )

            except Exception as e:
                rumps.notification(
                    title="Processing Error",
                    subtitle="",
                    message=str(e)
                )
            finally:
                self._processing = False
                self.title = "🎙"

        thread = threading.Thread(target=process, daemon=True)
        thread.start()

    def _update_duration(self, timer):
        """Update the menu bar with recording duration."""
        if self.recorder.is_recording:
            self.title = f"🔴 {self.recorder.duration_formatted}"

    def _transcribe_latest(self, sender):
        """Transcribe the latest recording."""
        if self._processing:
            rumps.notification(
                title="Busy",
                subtitle="",
                message="Already processing. Please wait."
            )
            return

        latest = self.file_manager.get_latest_recording()
        if not latest:
            rumps.notification(
                title="No Recording",
                subtitle="",
                message="No recordings found to transcribe."
            )
            return

        self._processing = True
        self.title = "⏳"

        def transcribe():
            try:
                rumps.notification(
                    title="Transcribing...",
                    subtitle="",
                    message=f"Processing: {latest.name}"
                )

                text = self.transcriber.transcribe(latest)

                rumps.notification(
                    title="Transcription Complete",
                    subtitle="",
                    message=f"Saved transcript for {latest.name}"
                )
            except Exception as e:
                rumps.notification(
                    title="Transcription Error",
                    subtitle="",
                    message=str(e)
                )
            finally:
                self._processing = False
                self.title = "🎙"

        thread = threading.Thread(target=transcribe, daemon=True)
        thread.start()

    def _summarize_latest(self, sender):
        """Summarize the latest transcript."""
        if self._processing:
            rumps.notification(
                title="Busy",
                subtitle="",
                message="Already processing. Please wait."
            )
            return

        if not self.ollama.is_available():
            rumps.notification(
                title="Ollama Not Available",
                subtitle="",
                message="Please start Ollama: ollama serve"
            )
            return

        latest = self.file_manager.get_latest_transcript()
        if not latest:
            rumps.notification(
                title="No Transcript",
                subtitle="",
                message="No transcripts found. Transcribe a recording first."
            )
            return

        self._processing = True
        self.title = "⏳"

        def summarize():
            try:
                rumps.notification(
                    title="Summarizing...",
                    subtitle="",
                    message=f"Processing: {latest.name}"
                )

                self.ollama.summarize_transcript_file(latest)

                rumps.notification(
                    title="Summary Complete",
                    subtitle="",
                    message=f"Saved summary for {latest.name}"
                )
            except Exception as e:
                rumps.notification(
                    title="Summarization Error",
                    subtitle="",
                    message=str(e)
                )
            finally:
                self._processing = False
                self.title = "🎙"

        thread = threading.Thread(target=summarize, daemon=True)
        thread.start()

    def _open_folder(self, sender):
        """Open the recordings folder in Finder."""
        self.file_manager.open_recordings_folder()

    def _quit(self, sender):
        """Quit the application."""
        self.call_monitor.stop_monitoring()
        if self.recorder.is_recording:
            self.recorder.stop_recording()
        rumps.quit_application()


def run():
    """Run the menu bar application."""
    app = MeetingRecorderApp()
    app.run()
