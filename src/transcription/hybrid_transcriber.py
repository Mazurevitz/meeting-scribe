"""Hybrid transcriber: fast MLX transcription + pyannote diarization.

Uses subprocess isolation to prevent memory leaks - all model memory
is released when the worker process exits.

Supports speaker identification via voice fingerprinting.
"""

import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Union

from .speaker_db import SpeakerDatabase


# Worker script template - executed in separate process
_WORKER_SCRIPT = '''
import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime
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

def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b) + 1e-8)
    return float(np.dot(a_norm, b_norm))

def main():
    # Read config from stdin
    config = json.loads(sys.stdin.read())

    audio_path = Path(config["audio_path"])
    output_path = Path(config["output_path"])
    whisper_model = config["whisper_model"]
    hf_token = config["hf_token"]
    target_sample_rate = config["target_sample_rate"]
    num_speakers = config.get("num_speakers")
    min_speakers = config.get("min_speakers")
    max_speakers = config.get("max_speakers")
    known_speakers = config.get("known_speakers", {})  # name -> embedding
    similarity_threshold = config.get("similarity_threshold", 0.75)

    try:
        # Step 0: Downsample audio
        print("Downsampling audio...", flush=True)
        sample_rate, audio = wavfile.read(audio_path)

        if sample_rate != target_sample_rate:
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0

            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)

            num_samples = int(len(audio) * target_sample_rate / sample_rate)
            audio_resampled = signal.resample(audio, num_samples)

            temp_audio = Path(tempfile.mktemp(suffix=".wav"))
            audio_int16 = (audio_resampled * 32767).astype(np.int16)
            wavfile.write(temp_audio, target_sample_rate, audio_int16)

            del audio, audio_resampled, audio_int16
        else:
            temp_audio = audio_path

        # Step 1: Fast transcription with lightning-whisper-mlx
        print("Loading Whisper model...", flush=True)
        from lightning_whisper_mlx import LightningWhisperMLX
        whisper = LightningWhisperMLX(
            model=whisper_model,
            batch_size=12,
            quant=None
        )

        print("Running fast transcription (MLX)...", flush=True)
        whisper_result = whisper.transcribe(str(temp_audio))
        segments = whisper_result.get("segments", [])

        # Free whisper model memory
        del whisper
        if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
            torch.mps.empty_cache()

        # Step 2: Run diarization
        print("Loading diarization model...", flush=True)
        from pyannote.audio import Pipeline, Audio
        from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

        diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )

        print("Running speaker diarization...", flush=True)
        diarization = diarization_pipeline(
            str(temp_audio),
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )

        # Step 3: Extract speaker embeddings for identification
        print("Extracting speaker embeddings...", flush=True)
        embedding_model = PretrainedSpeakerEmbedding(
            "pyannote/embedding",
            use_auth_token=hf_token
        )

        audio_loader = Audio(sample_rate=16000, mono=True)
        waveform, sr = audio_loader(str(temp_audio))

        # Get unique speakers and their segments
        speaker_segments = {}
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_segments:
                speaker_segments[speaker] = []
            speaker_segments[speaker].append((turn.start, turn.end))

        # Extract embedding for each speaker (use longest segment)
        speaker_embeddings = {}
        for speaker, segs in speaker_segments.items():
            # Find longest segment for best embedding
            longest = max(segs, key=lambda x: x[1] - x[0])
            start_sample = int(longest[0] * sr)
            end_sample = int(longest[1] * sr)

            # Ensure we have enough audio (at least 1 second)
            if end_sample - start_sample < sr:
                continue

            speaker_waveform = waveform[:, start_sample:end_sample]
            embedding = embedding_model(speaker_waveform.unsqueeze(0))
            speaker_embeddings[speaker] = embedding.squeeze().cpu().numpy().tolist()

        # Step 4: Match speakers to known voices
        speaker_names = {}
        new_embeddings = {}  # For speakers we couldn't match

        for speaker, embedding in speaker_embeddings.items():
            best_match = None
            best_score = 0.0

            for name, known_emb in known_speakers.items():
                score = cosine_similarity(np.array(embedding), np.array(known_emb))
                if score > best_score:
                    best_score = score
                    best_match = name

            if best_match and best_score >= similarity_threshold:
                speaker_names[speaker] = best_match
                print(f"  Matched {speaker} -> {best_match} (score: {best_score:.2f})", flush=True)
            else:
                speaker_names[speaker] = speaker  # Keep original label
                new_embeddings[speaker] = embedding
                if best_match:
                    print(f"  {speaker} best match {best_match} (score: {best_score:.2f}) below threshold", flush=True)

        # Step 5: Merge results with identified names
        print("Merging transcription with speakers...", flush=True)
        merged = []
        for segment in segments:
            # Handle [start_ms, end_ms, text] format from lightning-whisper-mlx
            if isinstance(segment, (list, tuple)):
                seg_start = segment[0] / 1000.0
                seg_end = segment[1] / 1000.0
                text = segment[2].strip() if len(segment) > 2 else ""
            else:
                seg_start = segment.get("start", 0)
                seg_end = segment.get("end", 0)
                text = segment.get("text", "").strip()

            seg_mid = (seg_start + seg_end) / 2

            if not text:
                continue

            speaker = "UNKNOWN"
            for turn, _, spk in diarization.itertracks(yield_label=True):
                if turn.start <= seg_mid <= turn.end:
                    # Use identified name if available
                    speaker = speaker_names.get(spk, spk)
                    break

            merged.append({
                "start": seg_start,
                "end": seg_end,
                "text": text,
                "speaker": speaker,
            })

        # Clean up temp file
        if temp_audio != audio_path and temp_audio.exists():
            temp_audio.unlink()

        # Format output
        lines = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Transcription of: {audio_path.name}")
        lines.append(f"Date: {timestamp}")
        lines.append(f"Model: {whisper_model} (hybrid MLX + pyannote)")
        lines.append("=" * 50)
        lines.append("")

        current_speaker = None
        current_text = []
        current_start = None

        for segment in merged:
            speaker = segment.get("speaker", "UNKNOWN")
            text = segment.get("text", "").strip()
            start = segment.get("start", 0)

            if speaker != current_speaker:
                if current_speaker is not None and current_text:
                    mins, secs = int(current_start // 60), int(current_start % 60)
                    combined_text = " ".join(current_text)
                    lines.append(f"[{mins:02d}:{secs:02d}] {current_speaker}:")
                    lines.append(f"  {combined_text}")
                    lines.append("")

                current_speaker = speaker
                current_text = [text] if text else []
                current_start = start
            else:
                if text:
                    current_text.append(text)

        if current_speaker is not None and current_text:
            mins, secs = int(current_start // 60), int(current_start % 60)
            combined_text = " ".join(current_text)
            lines.append(f"[{mins:02d}:{secs:02d}] {current_speaker}:")
            lines.append(f"  {combined_text}")
            lines.append("")

        formatted = "\\n".join(lines)

        # Save transcript
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        # Output success result as JSON (include new embeddings for learning)
        print("\\n__RESULT_START__", flush=True)
        print(json.dumps({
            "success": True,
            "transcript": formatted,
            "new_embeddings": new_embeddings,  # Unmatched speakers
            "speaker_names": speaker_names,    # All speaker mappings used
        }), flush=True)
        print("__RESULT_END__", flush=True)

    except Exception as e:
        import traceback
        print("\\n__RESULT_START__", flush=True)
        print(json.dumps({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), flush=True)
        print("__RESULT_END__", flush=True)

if __name__ == "__main__":
    main()
'''


class HybridTranscriber:
    """
    Fast hybrid transcription with speaker diarization.

    Uses lightning-whisper-mlx (Apple Silicon optimized) for transcription
    and pyannote for speaker diarization, then merges results.

    Supports speaker identification via voice fingerprinting - known speakers
    are automatically identified, and new speakers can be named for future calls.

    Runs in subprocess to prevent memory leaks - all model memory is
    guaranteed to be released when transcription completes.
    """

    def __init__(
        self,
        whisper_model: str = "distil-medium.en",
        hf_token: Optional[str] = None,
        target_sample_rate: int = 16000,
        speaker_db: Optional[SpeakerDatabase] = None,
    ):
        self.whisper_model = whisper_model
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.target_sample_rate = target_sample_rate
        self.speaker_db = speaker_db or SpeakerDatabase()
        self._last_new_embeddings = {}  # Store for manual naming

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

        Known speakers are automatically identified. New speakers can be
        named using name_speaker() after transcription.

        Runs in isolated subprocess to prevent memory leaks.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if output_path is None:
            output_path = audio_path.with_suffix(".txt")
        else:
            output_path = Path(output_path)

        if not self.hf_token:
            raise ValueError("HF_TOKEN required for speaker diarization")

        # Get known speaker embeddings
        known_speakers = {
            data['name']: data['embedding']
            for data in self.speaker_db.speakers.values()
        }

        # Config to pass to worker
        config = {
            "audio_path": str(audio_path),
            "output_path": str(output_path),
            "whisper_model": self.whisper_model,
            "hf_token": self.hf_token,
            "target_sample_rate": self.target_sample_rate,
            "num_speakers": num_speakers,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
            "known_speakers": known_speakers,
            "similarity_threshold": self.speaker_db.SIMILARITY_THRESHOLD,
        }

        # Write worker script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(_WORKER_SCRIPT)
            worker_script = f.name

        try:
            # Run worker in subprocess
            process = subprocess.Popen(
                [sys.executable, '-u', worker_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Send config and get output
            stdout, _ = process.communicate(input=json.dumps(config))

            # Print progress output (everything before result)
            if "__RESULT_START__" in stdout:
                progress, rest = stdout.split("__RESULT_START__", 1)
                print(progress, end='', flush=True)

                # Extract result JSON
                if "__RESULT_END__" in rest:
                    result_json = rest.split("__RESULT_END__")[0].strip()
                    result = json.loads(result_json)
                else:
                    raise RuntimeError(f"Malformed worker output: {stdout}")
            else:
                raise RuntimeError(f"Worker failed: {stdout}")

            if result["success"]:
                # Store new embeddings for manual naming
                self._last_new_embeddings = result.get("new_embeddings", {})
                return result["transcript"]
            else:
                raise RuntimeError(
                    f"Transcription failed: {result['error']}\n{result.get('traceback', '')}"
                )

        finally:
            # Clean up worker script
            try:
                os.unlink(worker_script)
            except OSError:
                pass

    def get_unnamed_speakers(self) -> list:
        """Get list of speakers from last transcription that weren't identified."""
        return list(self._last_new_embeddings.keys())

    def name_speaker(self, speaker_label: str, name: str) -> bool:
        """
        Assign a name to a speaker from the last transcription.

        This saves the voice embedding so the speaker will be
        automatically identified in future calls.

        Args:
            speaker_label: The speaker label (e.g., "SPEAKER_03")
            name: The person's name

        Returns:
            True if successful, False if speaker not found
        """
        if speaker_label not in self._last_new_embeddings:
            return False

        embedding = self._last_new_embeddings[speaker_label]
        self.speaker_db.add_speaker(name, embedding)
        del self._last_new_embeddings[speaker_label]
        return True

    def list_known_speakers(self) -> list:
        """List all known speakers in the database."""
        return self.speaker_db.list_speakers()

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
