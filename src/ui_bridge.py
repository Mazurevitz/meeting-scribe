"""Bridge between the pywebview JS frontend and the Python backend.

Every public method (no leading underscore) is automatically exposed
to JavaScript via ``window.pywebview.api.method_name()``.

All backend objects are stored as private (_prefixed) attributes so
pywebview does not try to introspect/serialize them.
"""

import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .audio import AudioRecorder, AudioDeviceManager
from .transcription import SmartTranscriber
from .summarization import OllamaClient
from .summarization.title_extractor import extract_metadata
from .storage import FileManager
from .auto_record import CallMonitor
from .config import Config, MODEL_INFO
from .pipeline import PipelineState, Stage

log = logging.getLogger(__name__)


class UIBridge:
    """Python API surface exposed to the webview frontend."""

    def __init__(
        self,
        config: Config,
        recorder: AudioRecorder,
        device_manager: AudioDeviceManager,
        transcriber: SmartTranscriber,
        ollama: OllamaClient,
        file_manager: FileManager,
    ):
        self._config = config
        self._recorder = recorder
        self._device_manager = device_manager
        self._transcriber = transcriber
        self._ollama = ollama
        self._file_manager = file_manager

        self._window = None
        self._status_bar = None

        self._processing = False
        self._cancelled = False
        self._progress: Optional[int] = None
        self._progress_stage: Optional[str] = None
        self._auto_recorded = False
        self._duration_ticker: Optional[threading.Thread] = None

        self._call_monitor = CallMonitor(
            on_call_start=self._on_call_start,
            on_call_end=self._on_call_end,
            weekdays_only=True,
            poll_interval=5.0,
        )
        self._call_monitor.enabled = config.auto_record_enabled
        self._call_monitor.start_monitoring()

        # Resume any interrupted pipelines from a previous crash
        threading.Thread(target=self._resume_incomplete, daemon=True).start()

    # ── Polling endpoint ──────────────────────────────────────────

    def get_state(self):
        """Returns all UI state in a single call (polled every 1s)."""
        incomplete = PipelineState.find_incomplete(self._file_manager.base_dir)
        return {
            "recording": self._recorder.is_recording,
            "duration": self._recorder.duration_formatted if self._recorder.is_recording else "",
            "processing": self._processing,
            "progress": self._progress,
            "progress_stage": self._progress_stage,
            "auto_record": self._config.auto_record_enabled,
            "auto_transcribe": self._config.auto_transcribe,
            "auto_summarize": self._config.auto_summarize,
            "diarization": self._config.prefer_diarization,
            "diarization_available": self._transcriber.can_diarize,
            "ollama_available": self._ollama.is_available(),
            "ollama_model": self._config.ollama_model,
            "incomplete_count": len(incomplete),
        }

    # ── Meetings list ─────────────────────────────────────────────

    def get_meetings(self):
        """List all meetings with file status and pipeline info."""
        result = []
        for m in self._file_manager.list_meetings():
            pipeline_stage = pipeline_error = meeting_title = None
            meeting_tags = []
            meeting_people = []
            if m.audio_path:
                ps = PipelineState(m.audio_path)
                if ps.state_path.exists():
                    pipeline_stage = ps.stage.value
                    pipeline_error = ps.error
                    meeting_title = ps.title
                    meeting_tags = ps.tags
                    meeting_people = ps.people

            result.append({
                "name": m.name,
                "title": meeting_title,
                "tags": meeting_tags,
                "people": meeting_people,
                "has_audio": m.has_audio,
                "has_transcript": m.has_transcript,
                "has_summary": m.has_summary,
                "audio_path": str(m.audio_path) if m.audio_path else None,
                "transcript_path": str(m.transcript_path) if m.transcript_path else None,
                "summary_path": str(m.summary_path) if m.summary_path else None,
                "created": m.created.strftime("%Y-%m-%d %H:%M") if m.created else "",
                "pipeline_stage": pipeline_stage,
                "pipeline_error": pipeline_error,
            })
        return result

    # ── Recording ─────────────────────────────────────────────────

    def toggle_recording(self):
        """Start or stop recording."""
        try:
            if self._recorder.is_recording:
                return self._stop_recording()
            else:
                return self._start_recording()
        except Exception as e:
            log.exception("Recording error")
            return {"ok": False, "error": str(e)}

    def _start_recording(self):
        filepath = self._recorder.start_recording()
        self._start_duration_ticker()
        return {"ok": True, "action": "started", "file": filepath.name}

    def _stop_recording(self):
        self._auto_recorded = False
        filepath = self._recorder.stop_recording()
        self._stop_duration_ticker()
        self._update_status_icon("idle")

        PipelineState(filepath)

        if self._config.auto_transcribe:
            self._run_pipeline(filepath)

        return {"ok": True, "action": "stopped", "file": filepath.name}

    # ── Pipeline actions ──────────────────────────────────────────

    def transcribe(self, audio_path):
        """Transcribe a specific recording."""
        if self._processing:
            return {"ok": False, "error": "Already processing"}
        path = Path(audio_path)
        if not path.exists():
            return {"ok": False, "error": "Audio file not found"}
        self._run_pipeline(path)
        return {"ok": True}

    def summarize(self, transcript_path):
        """Summarize a specific transcript."""
        if self._processing:
            return {"ok": False, "error": "Already processing"}
        path = Path(transcript_path)
        if not path.exists():
            return {"ok": False, "error": "Transcript not found"}

        audio_path = path.with_suffix(".wav")
        if audio_path.exists():
            ps = PipelineState(audio_path)
            ps.set_stage(Stage.TRANSCRIBED)
            self._run_pipeline(audio_path)
        else:
            self._summarize_standalone(path)
        return {"ok": True}

    def _summarize_standalone(self, transcript_path: Path):
        """Summarize without pipeline tracking (no matching audio file)."""
        self._processing = True
        self._progress_stage = "summarizing"

        def run():
            try:
                self._ollama.summarize_transcript_file(transcript_path)
            except Exception as e:
                log.exception("Standalone summarization failed")
            finally:
                self._processing = False
                self._progress = None
                self._progress_stage = None

        threading.Thread(target=run, daemon=True).start()

    def retry(self, meeting_name):
        """Retry a failed pipeline for a meeting."""
        if self._processing:
            return {"ok": False, "error": "Already processing"}

        audio_path = self._file_manager.find_audio_path(meeting_name)
        if not audio_path:
            return {"ok": False, "error": "Audio file not found"}

        ps = PipelineState(audio_path)
        ps.reset_for_retry()
        self._run_pipeline(audio_path)
        return {"ok": True}

    def cancel_processing(self):
        """Cancel the current transcription or summarization."""
        if not self._processing:
            return {"ok": False, "error": "Nothing is processing"}

        self._cancelled = True
        self._kill_worker_subprocesses()

        self._processing = False
        self._progress = None
        self._progress_stage = None
        self._update_status_icon("idle")
        return {"ok": True}

    def _kill_worker_subprocesses(self):
        """Kill any ML worker subprocesses (whisper, pyannote)."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "lightning_whisper_mlx|pyannote|worker.*\\.py"],
                capture_output=True, text=True, timeout=2,
            )
            for pid in result.stdout.strip().split("\n"):
                pid = pid.strip()
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except (ProcessLookupError, ValueError):
                        pass
        except Exception as e:
            log.warning("Cancel cleanup: %s", e)

    # ── Config ────────────────────────────────────────────────────

    def set_config(self, key, value):
        """Update a config value, applying any side effects."""
        self._config.set(key, value)

        if key == "auto_record_enabled":
            self._call_monitor.enabled = value
        elif key == "prefer_diarization":
            self._transcriber.prefer_diarization = value
        elif key == "ollama_model":
            self._ollama = OllamaClient(model=value)

        return {"ok": True}

    # ── Devices & Models ──────────────────────────────────────────

    def get_devices(self):
        """Get available audio devices."""
        mics = self._device_manager.get_microphone_devices()
        default = self._device_manager.get_default_microphone()
        blackhole = self._device_manager.get_blackhole_device()

        return {
            "mics": [
                {"name": m.name, "index": m.index,
                 "is_selected": default and m.index == default.index}
                for m in mics
            ],
            "system_audio": {
                "name": blackhole.name if blackhole else None,
                "available": blackhole is not None,
            },
        }

    def select_mic(self, index):
        mics = self._device_manager.get_microphone_devices()
        for m in mics:
            if m.index == index:
                self._recorder.set_microphone(m)
                return {"ok": True}
        return {"ok": False, "error": "Device not found"}

    def get_models(self):
        """Get available Ollama models with descriptions."""
        raw = self._ollama.list_models() if self._ollama.is_available() else []
        models = []
        for name in raw:
            family = name.split(":")[0].lower()
            info = next(
                (v for k, v in MODEL_INFO.items() if k in family),
                None,
            )
            models.append({
                "name": name,
                "tier": info["tier"] if info else "mid",
                "desc": info["desc"] if info else "",
            })
        return {"models": models, "current": self._config.ollama_model}

    def select_model(self, name):
        self._config.set("ollama_model", name)
        self._ollama = OllamaClient(model=name)
        return {"ok": True}

    # ── File actions ──────────────────────────────────────────────

    def ai_rename(self, meeting_name):
        """Ask the LLM to generate a short title from the summary."""
        audio_path = self._file_manager.find_audio_path(meeting_name)
        if not audio_path:
            return {"ok": False, "error": "Meeting not found"}

        summary_path = audio_path.with_suffix(".txt").with_suffix(".summary.md")
        if not summary_path.exists():
            summary_path = audio_path.with_suffix(".summary.md")
        if not summary_path.exists():
            return {"ok": False, "error": "No summary to generate title from"}

        if not self._ollama.is_available():
            return {"ok": False, "error": "Ollama not running"}

        try:
            content = summary_path.read_text(encoding="utf-8")[:2000]
            prompt = (
                "Give this meeting a short title (3-6 words, no quotes, no punctuation). "
                "Just the title, nothing else.\n\n" + content
            )
            title = self._ollama.generate(prompt).strip().strip('"\'')
            if title:
                PipelineState(audio_path).set_title(title)
                return {"ok": True, "title": title}
            return {"ok": False, "error": "Empty response"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_tags(self, meeting_name, tags):
        """Set custom tags for a meeting."""
        audio_path = self._file_manager.find_audio_path(meeting_name)
        if not audio_path:
            return {"ok": False, "error": "Meeting not found"}
        PipelineState(audio_path).set_metadata(tags=tags)
        return {"ok": True}

    def rename_meeting(self, meeting_name, new_title):
        """Set a custom title for a meeting."""
        audio_path = self._file_manager.find_audio_path(meeting_name)
        if not audio_path:
            return {"ok": False, "error": "Meeting not found"}
        PipelineState(audio_path).set_title(new_title.strip())
        return {"ok": True}

    def delete_meeting(self, meeting_name):
        """Delete all files for a meeting."""
        try:
            deleted = self._file_manager.delete_meeting(meeting_name)
            return {"ok": deleted}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_file(self, path):
        subprocess.run(["open", path])

    def open_folder(self):
        self._file_manager.open_recordings_folder()

    def copy_summary(self, summary_path):
        try:
            path = Path(summary_path)
            if not path.exists():
                return {"ok": False, "error": "Summary not found"}
            content = path.read_text(encoding="utf-8")
            proc = subprocess.Popen(
                ["pbcopy"], stdin=subprocess.PIPE, env={"LANG": "en_US.UTF-8"}
            )
            proc.communicate(content.encode("utf-8"))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_summary_text(self, summary_path):
        try:
            path = Path(summary_path)
            if not path.exists():
                return {"error": "Summary not found"}
            return {"text": path.read_text(encoding="utf-8")}
        except Exception as e:
            return {"error": str(e)}

    # ── Internal: status bar ──────────────────────────────────────

    def _update_progress(self, percent, stage):
        """Progress callback — only moves forward, never backwards."""
        if self._progress is not None and percent < self._progress:
            return
        self._progress = percent
        self._progress_stage = stage
        self._update_status_icon("processing", f"{percent}%")

    def _update_status_icon(self, state, text=None):
        if not self._status_bar:
            return
        if state == "idle":
            self._status_bar.set_title("\U0001f399")
        elif state == "recording":
            dur = self._recorder.duration_formatted if self._recorder.is_recording else ""
            self._status_bar.set_title(f"\U0001f534 {dur}")
        elif state == "processing":
            self._status_bar.set_title(f"\u23f3 {text or ''}")

    def _start_duration_ticker(self):
        def tick():
            while self._recorder.is_recording:
                self._update_status_icon("recording")
                time.sleep(1)
        self._duration_ticker = threading.Thread(target=tick, daemon=True)
        self._duration_ticker.start()

    def _stop_duration_ticker(self):
        self._duration_ticker = None

    # ── Internal: call monitor callbacks ──────────────────────────

    def _on_call_start(self):
        if self._recorder.is_recording:
            return
        self._auto_recorded = True
        try:
            self._recorder.start_recording()
            self._start_duration_ticker()
        except Exception as e:
            log.exception("Auto-record start error")

    def _on_call_end(self):
        if not self._recorder.is_recording or not self._auto_recorded:
            return
        self._auto_recorded = False
        try:
            filepath = self._recorder.stop_recording()
            self._stop_duration_ticker()
            self._update_status_icon("idle")
            PipelineState(filepath)
            if self._config.auto_transcribe:
                self._run_pipeline(filepath)
        except Exception as e:
            log.exception("Auto-record stop error")

    # ── Internal: pipeline ────────────────────────────────────────

    def _run_pipeline(self, audio_path: Path):
        """Run the transcribe → summarize pipeline in a background thread."""
        if self._processing:
            return
        self._processing = True
        self._cancelled = False
        self._progress = 0
        self._progress_stage = "starting"

        def process():
            ps = PipelineState(audio_path)
            try:
                self._pipeline_transcribe(ps, audio_path)
                self._pipeline_summarize(ps, audio_path)
            except Exception as e:
                if not self._cancelled:
                    stage = "transcribe" if ps.stage == Stage.TRANSCRIBING else "summarize"
                    ps.mark_failed(str(e), failed_stage=stage)
                    log.exception("Pipeline error (%s)", stage)
            finally:
                self._processing = False
                self._cancelled = False
                self._progress = None
                self._progress_stage = None
                self._update_status_icon("idle")

        threading.Thread(target=process, daemon=True).start()

    def _pipeline_transcribe(self, ps: PipelineState, audio_path: Path):
        """Transcription stage of the pipeline."""
        if ps.stage not in (Stage.RECORDED, Stage.FAILED):
            return
        if self._cancelled:
            return

        ps.mark_transcribing()
        self._progress_stage = "transcribing"

        text, method = self._transcriber.transcribe(
            audio_path, progress_callback=self._update_progress
        )

        if self._cancelled:
            ps.set_stage(Stage.RECORDED)
            return

        ps.mark_transcribed()

    def _pipeline_summarize(self, ps: PipelineState, audio_path: Path):
        """Summarization stage of the pipeline."""
        if ps.stage != Stage.TRANSCRIBED or not self._config.auto_summarize:
            if ps.stage == Stage.TRANSCRIBED:
                ps.mark_done()
            return
        if self._cancelled:
            return

        transcript_path = audio_path.with_suffix(".txt")
        if not self._ollama.is_available() or not transcript_path.exists():
            return

        ps.mark_summarizing()
        self._progress_stage = "summarizing"
        self._progress = None

        self._ollama.summarize_transcript_file(transcript_path)

        if self._cancelled:
            ps.set_stage(Stage.TRANSCRIBED)
            return

        ps.mark_done()

        # Auto-extract title, tags, people from the generated summary
        summary_path = transcript_path.with_suffix(".summary.md")
        meta = extract_metadata(summary_path)
        ps.set_metadata(
            title=meta.get("title"),
            tags=meta.get("tags", []),
            people=meta.get("people", []),
        )

    def _resume_incomplete(self):
        """On startup, reset stuck 'transcribing'/'summarizing' states to retryable.

        Does NOT auto-run pipelines — the user can click Retry in the UI
        when they're ready, avoiding surprise OOM on large recordings.
        """
        time.sleep(2)
        for ps in PipelineState.find_incomplete(self._file_manager.base_dir):
            if not ps.audio_path.exists():
                ps.cleanup()
            elif ps.stage in (Stage.TRANSCRIBING, Stage.SUMMARIZING):
                # Reset stuck states so they show as retryable in the UI
                ps.reset_for_retry()

    # ── Shutdown ──────────────────────────────────────────────────

    def shutdown(self):
        """Clean shutdown — stop monitoring, save recording, free models."""
        self._call_monitor.stop_monitoring()
        if self._recorder.is_recording:
            try:
                self._recorder.stop_recording()
            except Exception:
                log.exception("Error stopping recording during shutdown")
        self._transcriber.cleanup()
