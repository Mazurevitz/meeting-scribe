"""Smart transcriber with automatic fallback between diarization and basic transcription."""

from pathlib import Path
from typing import Optional, Tuple, Union
import os

from .whisper_transcriber import WhisperTranscriber


class SmartTranscriber:
    """
    Transcriber that tries diarization first, falls back to basic transcription.

    Priority:
    1. whisperx with speaker diarization (if available + HF_TOKEN set)
    2. lightning-whisper-mlx (fast, Apple Silicon optimized)
    """

    def __init__(
        self,
        prefer_diarization: bool = True,
        hf_token: Optional[str] = None,
        whisper_model: str = "distil-medium.en",
        diarization_model: str = "medium.en",
    ):
        self.prefer_diarization = prefer_diarization
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.whisper_model = whisper_model
        self.diarization_model = diarization_model

        self._diarized_transcriber = None
        self._basic_transcriber = None

        # Check what's available
        self._diarization_available, self._diarization_status = self._check_diarization()

    def _check_diarization(self) -> Tuple[bool, str]:
        """Check if diarization is available."""
        try:
            from .diarized_transcriber import DiarizedTranscriber

            available, msg = DiarizedTranscriber.is_available()
            if not available:
                return False, msg

            if not self.hf_token:
                return False, "HF_TOKEN not set (required for speaker diarization)"

            return True, "Diarization available"
        except Exception as e:
            return False, f"Diarization check failed: {e}"

    def _get_diarized_transcriber(self):
        """Get or create diarized transcriber."""
        if self._diarized_transcriber is None:
            from .diarized_transcriber import DiarizedTranscriber
            self._diarized_transcriber = DiarizedTranscriber(
                model_name=self.diarization_model,
                hf_token=self.hf_token,
            )
        return self._diarized_transcriber

    def _get_basic_transcriber(self):
        """Get or create basic transcriber."""
        if self._basic_transcriber is None:
            self._basic_transcriber = WhisperTranscriber(
                model_name=self.whisper_model
            )
        return self._basic_transcriber

    def transcribe(
        self,
        audio_path: Union[Path, str],
        output_path: Optional[Union[Path, str]] = None,
        force_diarization: bool = False,
        force_basic: bool = False,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        Transcribe audio with smart fallback.

        Args:
            audio_path: Path to audio file
            output_path: Where to save transcript
            force_diarization: Force diarization (fail if unavailable)
            force_basic: Force basic transcription (skip diarization)
            num_speakers: Hint for exact number of speakers
            min_speakers: Minimum expected speakers
            max_speakers: Maximum expected speakers

        Returns:
            Tuple of (transcript_text, method_used)
        """
        audio_path = Path(audio_path)

        # Determine which method to use
        use_diarization = (
            self.prefer_diarization
            and self._diarization_available
            and not force_basic
        ) or force_diarization

        if use_diarization:
            try:
                transcriber = self._get_diarized_transcriber()
                text = transcriber.transcribe(
                    audio_path,
                    output_path=output_path,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                return text, "diarization"
            except Exception as e:
                if force_diarization:
                    raise
                # Fall back to basic
                print(f"Diarization failed ({e}), falling back to basic transcription")

        # Basic transcription
        transcriber = self._get_basic_transcriber()
        text = transcriber.transcribe(audio_path, output_path=output_path)
        return text, "basic"

    def get_status(self) -> dict:
        """Get status of available transcription methods."""
        return {
            "diarization_available": self._diarization_available,
            "diarization_status": self._diarization_status,
            "hf_token_set": bool(self.hf_token),
            "prefer_diarization": self.prefer_diarization,
            "whisper_model": self.whisper_model,
            "diarization_model": self.diarization_model,
        }

    @property
    def can_diarize(self) -> bool:
        """Check if diarization is currently possible."""
        return self._diarization_available
