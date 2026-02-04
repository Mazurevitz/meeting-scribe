"""Speaker diarization transcription using whisperx."""

import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
from functools import wraps

# Fix for PyTorch 2.6+ weights_only security - must be done BEFORE importing pyannote
import torch
_torch_load_original = torch.load

@wraps(_torch_load_original)
def _torch_load_patched(*args, **kwargs):
    # Force weights_only=False for pyannote model loading
    kwargs['weights_only'] = False
    return _torch_load_original(*args, **kwargs)

torch.load = _torch_load_patched


class DiarizedTranscriber:
    """Transcribes audio with speaker diarization using whisperx."""

    DEFAULT_MODEL = "medium.en"

    def __init__(
        self,
        model_name: Optional[str] = None,
        hf_token: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        # whisperx uses ctranslate2 which doesn't support MPS, use CPU
        self.device = device or "cpu"
        self._model = None
        self._diarize_model = None
        self._align_model = None
        self._align_metadata = None

    def _load_models(self):
        """Lazy-load whisperx models."""
        if self._model is not None:
            return

        import whisperx

        # Load whisper model - can use MPS for speed
        compute_type = "float32"
        self._model = whisperx.load_model(
            self.model_name,
            self.device,
            compute_type=compute_type
        )

    def _load_align_model(self, language_code: str):
        """Load alignment model for word-level timestamps."""
        import whisperx

        if self._align_model is None:
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=language_code,
                device=self.device
            )

    def _load_diarize_model(self):
        """Load speaker diarization model."""
        if self._diarize_model is not None:
            return

        if not self.hf_token:
            raise ValueError(
                "HuggingFace token required for speaker diarization. "
                "Set HF_TOKEN environment variable or pass hf_token parameter. "
                "Get token at: https://huggingface.co/settings/tokens"
            )

        from whisperx.diarize import DiarizationPipeline

        self._diarize_model = DiarizationPipeline(
            use_auth_token=self.hf_token,
            device=self.device
        )

    def transcribe(
        self,
        audio_path: Union[Path, str],
        output_path: Optional[Union[Path, str]] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> str:
        """
        Transcribe audio with speaker diarization.

        Args:
            audio_path: Path to audio file
            output_path: Where to save transcript (default: next to audio)
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum expected speakers
            max_speakers: Maximum expected speakers

        Returns:
            Formatted transcript with speaker labels
        """
        import whisperx

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Load models
        self._load_models()

        # Load and transcribe audio
        audio = whisperx.load_audio(str(audio_path))
        result = self._model.transcribe(audio, batch_size=16)

        # Align whisper output for word-level timestamps
        language = result.get("language", "en")
        self._load_align_model(language)
        result = whisperx.align(
            result["segments"],
            self._align_model,
            self._align_metadata,
            audio,
            self.device,
            return_char_alignments=False
        )

        # Perform speaker diarization
        self._load_diarize_model()
        diarize_segments = self._diarize_model(
            audio,
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )

        # Assign speakers to words/segments
        result = whisperx.assign_word_speakers(diarize_segments, result)

        # Format output
        formatted = self._format_transcript(result, audio_path)

        # Save transcript
        if output_path is None:
            output_path = audio_path.with_suffix(".txt")
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        return formatted

    def _format_transcript(self, result: Dict, audio_path: Path) -> str:
        """Format diarized transcript with speaker labels."""
        lines = []

        # Header
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Transcription of: {audio_path.name}")
        lines.append(f"Date: {timestamp}")
        lines.append(f"Model: {self.model_name} (whisperx + diarization)")
        lines.append("=" * 50)
        lines.append("")

        # Group consecutive segments by speaker
        segments = result.get("segments", [])
        current_speaker = None
        current_text = []
        current_start = None

        for segment in segments:
            speaker = segment.get("speaker", "UNKNOWN")
            text = segment.get("text", "").strip()
            start = segment.get("start", 0)

            if speaker != current_speaker:
                # Save previous speaker's text
                if current_speaker is not None and current_text:
                    time_str = self._format_time(current_start)
                    combined_text = " ".join(current_text)
                    lines.append(f"[{time_str}] {current_speaker}:")
                    lines.append(f"  {combined_text}")
                    lines.append("")

                # Start new speaker
                current_speaker = speaker
                current_text = [text] if text else []
                current_start = start
            else:
                if text:
                    current_text.append(text)

        # Don't forget last speaker
        if current_speaker is not None and current_text:
            time_str = self._format_time(current_start)
            combined_text = " ".join(current_text)
            lines.append(f"[{time_str}] {current_speaker}:")
            lines.append(f"  {combined_text}")
            lines.append("")

        return "\n".join(lines)

    def _format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def get_speakers(self, audio_path: Union[Path, str]) -> List[str]:
        """Get list of detected speakers from an audio file."""
        import whisperx

        audio_path = Path(audio_path)
        audio = whisperx.load_audio(str(audio_path))

        self._load_diarize_model()
        diarize_segments = self._diarize_model(audio)

        speakers = set()
        for segment in diarize_segments:
            if hasattr(segment, 'speaker'):
                speakers.add(segment.speaker)

        return sorted(list(speakers))

    @staticmethod
    def is_available() -> Tuple[bool, str]:
        """Check if whisperx and dependencies are available."""
        try:
            import whisperx
            return True, "whisperx available"
        except ImportError as e:
            return False, f"whisperx not installed: {e}"

    @staticmethod
    def check_hf_token() -> Tuple[bool, str]:
        """Check if HuggingFace token is configured."""
        token = os.environ.get("HF_TOKEN")
        if token:
            return True, "HF_TOKEN is set"
        return False, "HF_TOKEN not set. Required for speaker diarization."
