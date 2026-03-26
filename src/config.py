"""Configuration management for Meeting Scribe.

Central source of truth for all persistent settings and paths.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

# Default paths (used across the app)
RECORDINGS_DIR = Path.home() / "Documents" / "MeetingRecordings"
CONFIG_DIR = Path.home() / ".config" / "meeting-scribe"
SPEAKERS_DIR = Path.home() / ".meeting-recorder"

# Model descriptions shown in the UI
MODEL_INFO = {
    "qwen3": {"tier": "mid", "desc": "Best all-rounder for 16GB"},
    "qwen2.5": {"tier": "mid", "desc": "Great quality, 128K context"},
    "llama3.1": {"tier": "mid", "desc": "Solid general purpose"},
    "llama3.2": {"tier": "low", "desc": "Lightweight, fast"},
    "gemma2": {"tier": "mid", "desc": "Good at summarization"},
    "gemma3": {"tier": "low", "desc": "Fast, small footprint"},
    "mistral": {"tier": "low", "desc": "Fast and capable"},
    "mixtral": {"tier": "high", "desc": "MoE, needs 32GB+"},
    "phi4": {"tier": "low", "desc": "Tiny but smart"},
    "phi3": {"tier": "low", "desc": "Compact, decent quality"},
    "deepseek": {"tier": "mid", "desc": "Strong reasoning"},
    "command-r": {"tier": "mid", "desc": "Good at structured output"},
    "llama3.3": {"tier": "high", "desc": "70B, needs 48GB+"},
}


def _atomic_json_write(path: Path, data: dict):
    """Write JSON to a file atomically (write to temp, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class Config:
    """Manages persistent configuration."""

    DEFAULT_CONFIG = {
        "auto_record_enabled": False,
        "auto_transcribe": True,
        "auto_summarize": True,
        "ollama_model": "qwen3:8b",
        "whisper_model": "distil-large-v3",
        "diarization_model": "distil-large-v3",
        "prefer_diarization": True,
        "weekdays_only": True,
    }

    def __init__(self, config_path: Path = None):
        self.config_path = config_path or (CONFIG_DIR / "config.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from file, merging with defaults for missing keys."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    loaded = json.load(f)
                    return {**self.DEFAULT_CONFIG, **loaded}
            except (json.JSONDecodeError, IOError):
                pass
        return self.DEFAULT_CONFIG.copy()

    def _save(self):
        _atomic_json_write(self.config_path, self._config)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._config[key] = value
        self._save()

    @property
    def auto_record_enabled(self) -> bool:
        return self._config.get("auto_record_enabled", False)

    @auto_record_enabled.setter
    def auto_record_enabled(self, value: bool):
        self.set("auto_record_enabled", value)

    @property
    def auto_transcribe(self) -> bool:
        return self._config.get("auto_transcribe", True)

    @auto_transcribe.setter
    def auto_transcribe(self, value: bool):
        self.set("auto_transcribe", value)

    @property
    def auto_summarize(self) -> bool:
        return self._config.get("auto_summarize", True)

    @auto_summarize.setter
    def auto_summarize(self, value: bool):
        self.set("auto_summarize", value)

    @property
    def ollama_model(self) -> str:
        return self._config.get("ollama_model", "qwen3:8b")

    @property
    def whisper_model(self) -> str:
        return self._config.get("whisper_model", "distil-large-v3")

    @property
    def diarization_model(self) -> str:
        return self._config.get("diarization_model", "distil-large-v3")

    @property
    def prefer_diarization(self) -> bool:
        return self._config.get("prefer_diarization", True)

    @prefer_diarization.setter
    def prefer_diarization(self, value: bool):
        self.set("prefer_diarization", value)
