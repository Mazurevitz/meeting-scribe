"""Pipeline state management — tracks progress through record/transcribe/summarize stages.

Each meeting gets a checkpoint file (``meeting_XXXX.pipeline.json``) that
persists the current stage, any error, and an optional title. This allows
the app to resume work after a crash and show per-meeting status in the UI.
"""

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional

from .config import _atomic_json_write


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
        _atomic_json_write(self.state_path, self._state)

    # ── Stage accessors ──────────────────────────────────────────

    @property
    def stage(self) -> Stage:
        return Stage(self._state.get("stage", Stage.RECORDED.value))

    @property
    def error(self) -> Optional[str]:
        return self._state.get("error")

    @property
    def failed_stage(self) -> Optional[str]:
        return self._state.get("error_stage")

    def set_stage(self, stage: Stage, error: Optional[str] = None):
        self._state["stage"] = stage.value
        self._state["error"] = error
        self._save()

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

    # ── Metadata (title, tags, people) ──────────────────────────

    @property
    def title(self) -> Optional[str]:
        return self._state.get("title")

    @property
    def tags(self) -> list:
        return self._state.get("tags", [])

    @property
    def people(self) -> list:
        return self._state.get("people", [])

    def set_title(self, title: str):
        self._state["title"] = title
        self._save()

    def set_metadata(self, title: Optional[str] = None, tags: list = None, people: list = None):
        """Set title, tags, and people in one write."""
        if title is not None:
            self._state["title"] = title
        if tags is not None:
            self._state["tags"] = tags
        if people is not None:
            self._state["people"] = people
        self._save()

    # ── Lifecycle ────────────────────────────────────────────────

    def reset_for_retry(self):
        """Reset from a failed/stuck state so the pipeline can be retried."""
        if self.stage in (Stage.FAILED, Stage.TRANSCRIBING):
            if self.failed_stage == "summarize":
                self.set_stage(Stage.TRANSCRIBED)
            else:
                self.set_stage(Stage.RECORDED)
        elif self.stage == Stage.SUMMARIZING:
            self.set_stage(Stage.TRANSCRIBED)

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
                if ps.stage != Stage.DONE:
                    incomplete.append(ps)
            except Exception:
                pass
        return incomplete
