"""Hybrid transcriber: fast MLX transcription + pyannote diarization."""

import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
from functools import wraps

# Fix for PyTorch 2.6+ weights_only security
import torch
_torch_load_original = torch.load

@wraps(_torch_load_original)
def _torch_load_patched(*args, **kwargs):
    kwargs['weights_only'] = False
    return _torch_load_original(*args, **kwargs)

torch.load = _torch_load_patched

import numpy as np
from scipy.io import wavfile
from scipy import signal


class HybridTranscriber:
    """
    Fast hybrid transcription with speaker diarization.

    Uses lightning-whisper-mlx (Apple Silicon optimized) for transcription
    and pyannote for speaker diarization, then merges results.

    Much faster than full whisperx pipeline.
    """

    def __init__(
        self,
        whisper_model: str = "distil-medium.en",
        hf_token: Optional[str] = None,
        target_sample_rate: int = 16000,
    ):
        self.whisper_model = whisper_model
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.target_sample_rate = target_sample_rate

        self._whisper = None
        self._diarization_pipeline = None

    def _load_whisper(self):
        """Load lightning-whisper-mlx model."""
        if self._whisper is None:
            from lightning_whisper_mlx import LightningWhisperMLX
            self._whisper = LightningWhisperMLX(
                model=self.whisper_model,
                batch_size=12,
                quant=None
            )

    def _load_diarization(self):
        """Load pyannote diarization pipeline."""
        if self._diarization_pipeline is None:
            if not self.hf_token:
                raise ValueError("HF_TOKEN required for speaker diarization")

            from pyannote.audio import Pipeline
            self._diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=self.hf_token
            )

    def _downsample_audio(self, audio_path: Path) -> Path:
        """Downsample audio to target sample rate for faster processing."""
        sample_rate, audio = wavfile.read(audio_path)

        if sample_rate == self.target_sample_rate:
            return audio_path

        # Convert to float
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0

        # Handle stereo -> mono
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        # Resample
        num_samples = int(len(audio) * self.target_sample_rate / sample_rate)
        audio_resampled = signal.resample(audio, num_samples)

        # Save to temp file
        temp_path = Path(tempfile.mktemp(suffix=".wav"))
        audio_int16 = (audio_resampled * 32767).astype(np.int16)
        wavfile.write(temp_path, self.target_sample_rate, audio_int16)

        return temp_path

    def transcribe(
        self,
        audio_path: Union[Path, str],
        output_path: Optional[Union[Path, str]] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> str:
        """
        Transcribe audio with speaker diarization using hybrid approach.

        1. Downsample audio to 16kHz
        2. Run fast MLX transcription with timestamps
        3. Run pyannote diarization
        4. Merge transcription segments with speaker labels
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Downsample for faster processing
        print("Downsampling audio...")
        processed_audio = self._downsample_audio(audio_path)
        temp_file = processed_audio != audio_path

        try:
            # Step 1: Fast transcription with lightning-whisper-mlx
            print("Running fast transcription (MLX)...")
            self._load_whisper()
            whisper_result = self._whisper.transcribe(str(processed_audio))
            segments = whisper_result.get("segments", [])

            # Step 2: Run diarization
            print("Running speaker diarization...")
            self._load_diarization()
            diarization = self._diarization_pipeline(
                str(processed_audio),
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )

            # Step 3: Merge results
            print("Merging transcription with speakers...")
            merged_segments = self._merge_segments_with_speakers(segments, diarization)

            # Format output
            formatted = self._format_transcript(merged_segments, audio_path)

        finally:
            # Clean up temp file
            if temp_file and processed_audio.exists():
                processed_audio.unlink()

        # Save transcript
        if output_path is None:
            output_path = audio_path.with_suffix(".txt")
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        return formatted

    def _merge_segments_with_speakers(
        self,
        segments: List[Dict],
        diarization
    ) -> List[Dict]:
        """Merge whisper segments with pyannote speaker labels."""
        merged = []

        for segment in segments:
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", 0)
            seg_mid = (seg_start + seg_end) / 2
            text = segment.get("text", "").strip()

            if not text:
                continue

            # Find speaker at segment midpoint
            speaker = "UNKNOWN"
            for turn, _, spk in diarization.itertracks(yield_label=True):
                if turn.start <= seg_mid <= turn.end:
                    speaker = spk
                    break

            merged.append({
                "start": seg_start,
                "end": seg_end,
                "text": text,
                "speaker": speaker,
            })

        return merged

    def _format_transcript(self, segments: List[Dict], audio_path: Path) -> str:
        """Format merged transcript with speaker labels."""
        lines = []

        # Header
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Transcription of: {audio_path.name}")
        lines.append(f"Date: {timestamp}")
        lines.append(f"Model: {self.whisper_model} (hybrid MLX + pyannote)")
        lines.append("=" * 50)
        lines.append("")

        # Group consecutive segments by speaker
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

    @staticmethod
    def is_available() -> Tuple[bool, str]:
        """Check if hybrid transcription is available."""
        try:
            from lightning_whisper_mlx import LightningWhisperMLX
        except ImportError:
            return False, "lightning-whisper-mlx not installed"

        try:
            from pyannote.audio import Pipeline
        except ImportError:
            return False, "pyannote.audio not installed"

        if not os.environ.get("HF_TOKEN"):
            return False, "HF_TOKEN not set"

        return True, "Hybrid transcription available"
