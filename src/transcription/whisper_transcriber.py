"""Whisper-based transcription using lightning-whisper-mlx."""

from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Union


class WhisperTranscriber:
    """Transcribes audio files using lightning-whisper-mlx (Apple Silicon optimized)."""

    DEFAULT_MODEL = "distil-medium.en"

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._whisper = None

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._whisper is None:
            from lightning_whisper_mlx import LightningWhisperMLX
            self._whisper = LightningWhisperMLX(model=self.model_name, batch_size=12, quant=None)

    def transcribe(self, audio_path: Union[Path, str], output_path: Optional[Union[Path, str]] = None) -> str:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file (WAV, MP3, etc.)
            output_path: Optional path to save the transcript. If None, saves next to audio file.

        Returns:
            The transcribed text.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        self._load_model()

        result = self._whisper.transcribe(str(audio_path))
        text = result.get("text", "").strip()

        if output_path is None:
            output_path = audio_path.with_suffix(".txt")
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"Transcription of: {audio_path.name}\nDate: {timestamp}\nModel: {self.model_name}\n"
        header += "=" * 50 + "\n\n"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(text)

        return text

    def transcribe_with_timestamps(self, audio_path: Union[Path, str]) -> List[Dict]:
        """
        Transcribe with word-level timestamps.

        Returns:
            List of segments with start, end, and text.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        self._load_model()

        result = self._whisper.transcribe(str(audio_path))

        segments = result.get("segments", [])
        return [
            {
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip()
            }
            for seg in segments
        ]

    def is_model_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self._whisper is not None

    @staticmethod
    def available_models() -> List[str]:
        """Return list of recommended models."""
        return [
            "tiny.en",
            "base.en",
            "small.en",
            "medium.en",
            "distil-medium.en",
            "distil-large-v3",
            "large-v3",
        ]
