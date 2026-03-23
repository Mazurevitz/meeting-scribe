"""Pipeline state management — tracks progress through record/transcribe/summarize stages.

Writes a small JSON checkpoint file alongside each meeting so work can be
resumed after a crash.  The checkpoint file is named
``meeting_XXXXXX.pipeline.json`` and lives in the same directory as the
audio file.
"""

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional


class Stage(str, Enum):
    RECORDED = "recorded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"


class PipelineState:
    """Persistent checkpoint for a single meeting's processing pipeline."""

    def __init__(self, audio_path: Path):
        self.audio_path = Path(audio_path)
        self.state_path = self.audio_path.with_suffix(".pipeline.json")
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "audio": str(self.audio_path),
            "stage": Stage.RECORDED.value,
            "error": None,
            "updated": datetime.now().isoformat(),
        }

    def _save(self):
        self._state["updated"] = datetime.now().isoformat()
        fd, tmp = tempfile.mkstemp(
            dir=self.state_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @property
    def stage(self) -> Stage:
        return Stage(self._state.get("stage", Stage.RECORDED.value))

    @property
    def error(self) -> Optional[str]:
        return self._state.get("error")

    def set_stage(self, stage: Stage, error: Optional[str] = None):
        self._state["stage"] = stage.value
        self._state["error"] = error
        self._save()

    @property
    def needs_transcription(self) -> bool:
        return self.stage in (Stage.RECORDED, Stage.FAILED) and self._state.get("error_stage") != "transcribe"

    @property
    def needs_summarization(self) -> bool:
        return self.stage == Stage.TRANSCRIBED

    @property
    def can_retry_transcription(self) -> bool:
        return self.stage == Stage.FAILED

    @property
    def can_retry_summarization(self) -> bool:
        return self.stage in (Stage.TRANSCRIBED, Stage.FAILED)

    def mark_transcribing(self):
        self.set_stage(Stage.TRANSCRIBING)

    def mark_transcribed(self):
        self.set_stage(Stage.TRANSCRIBED)

    def mark_summarizing(self):
        self.set_stage(Stage.SUMMARIZING)

    def mark_done(self):
        self.set_stage(Stage.DONE)

    def mark_failed(self, error: str, failed_stage: str = ""):
        self._state["error_stage"] = failed_stage
        self.set_stage(Stage.FAILED, error=error)

    def cleanup(self):
        """Remove the checkpoint file (call when meeting is deleted)."""
        if self.state_path.exists():
            self.state_path.unlink()

    @staticmethod
    def find_incomplete(recordings_dir: Path):
        """Find meetings with incomplete pipelines that can be resumed."""
        incomplete = []
        for state_file in sorted(recordings_dir.glob("*.pipeline.json")):
            try:
                ps = PipelineState(state_file.with_suffix("").with_suffix(".wav"))
                if ps.stage not in (Stage.DONE,):
                    incomplete.append(ps)
            except Exception:
                pass
        return incomplete
