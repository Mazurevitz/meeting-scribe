"""Configuration management for Meeting Scribe."""

import json
from pathlib import Path
from typing import Any, Dict


class Config:
    """Manages persistent configuration."""

    DEFAULT_CONFIG = {
        "auto_record_enabled": False,
        "auto_transcribe": True,
        "auto_summarize": True,
        "ollama_model": "llama3.1:latest",
        "whisper_model": "distil-medium.en",
        "diarization_model": "medium.en",
        "prefer_diarization": True,
        "weekdays_only": True,
    }

    def __init__(self, config_path: Path = None):
        if config_path:
            self.config_path = config_path
        else:
            self.config_path = Path.home() / ".config" / "meeting-scribe" / "config.json"

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from file or return defaults."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    loaded = json.load(f)
                    # Merge with defaults for any missing keys
                    return {**self.DEFAULT_CONFIG, **loaded}
            except (json.JSONDecodeError, IOError):
                pass
        return self.DEFAULT_CONFIG.copy()

    def _save(self):
        """Save config to file."""
        with open(self.config_path, "w") as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a config value and save."""
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
        return self._config.get("ollama_model", "llama3.1:latest")

    @property
    def whisper_model(self) -> str:
        return self._config.get("whisper_model", "distil-medium.en")

    @property
    def diarization_model(self) -> str:
        return self._config.get("diarization_model", "medium.en")

    @property
    def prefer_diarization(self) -> bool:
        return self._config.get("prefer_diarization", True)

    @prefer_diarization.setter
    def prefer_diarization(self, value: bool):
        self.set("prefer_diarization", value)
