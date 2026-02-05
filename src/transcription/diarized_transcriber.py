"""Speaker diarization transcription using whisperx.

Uses subprocess isolation to prevent memory leaks - all model memory
is released when the worker process exits.
"""

import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Union


# Worker script template
_WORKER_SCRIPT = '''
import os
import sys
import json
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

import whisperx

def main():
    config = json.loads(sys.stdin.read())

    audio_path = Path(config["audio_path"])
    output_path = Path(config["output_path"])
    model_name = config["model_name"]
    hf_token = config["hf_token"]
    device = config["device"]
    num_speakers = config.get("num_speakers")
    min_speakers = config.get("min_speakers")
    max_speakers = config.get("max_speakers")

    try:
        # Load whisper model
        print("Loading whisperx model...", flush=True)
        compute_type = "float32"
        model = whisperx.load_model(model_name, device, compute_type=compute_type)

        # Transcribe
        print("Transcribing audio...", flush=True)
        audio = whisperx.load_audio(str(audio_path))
        result = model.transcribe(audio, batch_size=16)

        # Free model
        del model
        if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
            torch.mps.empty_cache()

        # Align
        print("Aligning transcript...", flush=True)
        language = result.get("language", "en")
        align_model, align_metadata = whisperx.load_align_model(
            language_code=language,
            device=device
        )
        result = whisperx.align(
            result["segments"],
            align_model,
            align_metadata,
            audio,
            device,
            return_char_alignments=False
        )

        del align_model, align_metadata
        if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
            torch.mps.empty_cache()

        # Diarize
        print("Running speaker diarization...", flush=True)
        from whisperx.diarize import DiarizationPipeline
        diarize_model = DiarizationPipeline(
            use_auth_token=hf_token,
            device=device
        )
        diarize_segments = diarize_model(
            audio,
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )

        print("Assigning speakers...", flush=True)
        result = whisperx.assign_word_speakers(diarize_segments, result)

        # Format output
        lines = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Transcription of: {audio_path.name}")
        lines.append(f"Date: {timestamp}")
        lines.append(f"Model: {model_name} (whisperx + diarization)")
        lines.append("=" * 50)
        lines.append("")

        segments = result.get("segments", [])
        current_speaker = None
        current_text = []
        current_start = None

        for segment in segments:
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

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        print("\\n__RESULT_START__", flush=True)
        print(json.dumps({"success": True, "transcript": formatted}), flush=True)
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


class DiarizedTranscriber:
    """
    Transcribes audio with speaker diarization using whisperx.

    Runs in subprocess to prevent memory leaks.
    """

    DEFAULT_MODEL = "medium.en"

    def __init__(
        self,
        model_name: Optional[str] = None,
        hf_token: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.device = device or "cpu"

    def transcribe(
        self,
        audio_path: Union[Path, str],
        output_path: Optional[Union[Path, str]] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> str:
        """Transcribe audio with speaker diarization in isolated subprocess."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if output_path is None:
            output_path = audio_path.with_suffix(".txt")
        else:
            output_path = Path(output_path)

        if not self.hf_token:
            raise ValueError("HF_TOKEN required for speaker diarization")

        config = {
            "audio_path": str(audio_path),
            "output_path": str(output_path),
            "model_name": self.model_name,
            "hf_token": self.hf_token,
            "device": self.device,
            "num_speakers": num_speakers,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(_WORKER_SCRIPT)
            worker_script = f.name

        try:
            process = subprocess.Popen(
                [sys.executable, '-u', worker_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            stdout, _ = process.communicate(input=json.dumps(config))

            if "__RESULT_START__" in stdout:
                progress, rest = stdout.split("__RESULT_START__", 1)
                print(progress, end='', flush=True)

                if "__RESULT_END__" in rest:
                    result_json = rest.split("__RESULT_END__")[0].strip()
                    result = json.loads(result_json)
                else:
                    raise RuntimeError(f"Malformed worker output: {stdout}")
            else:
                raise RuntimeError(f"Worker failed: {stdout}")

            if result["success"]:
                return result["transcript"]
            else:
                raise RuntimeError(
                    f"Transcription failed: {result['error']}\n{result.get('traceback', '')}"
                )

        finally:
            try:
                os.unlink(worker_script)
            except OSError:
                pass

    @staticmethod
    def is_available() -> Tuple[bool, str]:
        """Check if whisperx is available."""
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
        return False, "HF_TOKEN not set"
