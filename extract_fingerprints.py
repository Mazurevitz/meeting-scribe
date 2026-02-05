#!/usr/bin/env python3
"""Extract voice fingerprints from existing meetings."""

import os
import sys
import re
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.transcription.speaker_db import SpeakerDatabase

# Worker script for subprocess isolation
_WORKER_SCRIPT = '''
import os
import sys
import json
import tempfile
from pathlib import Path
from functools import wraps

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

def main():
    config = json.loads(sys.stdin.read())
    audio_path = Path(config["audio_path"])
    hf_token = config["hf_token"]
    speaker_names = config["speaker_names"]  # Names we want to extract

    try:
        # Downsample audio
        print("Loading audio...", flush=True)
        sample_rate, audio = wavfile.read(audio_path)

        if sample_rate != 16000:
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)

            num_samples = int(len(audio) * 16000 / sample_rate)
            audio = signal.resample(audio, num_samples)

            temp_audio = Path(tempfile.mktemp(suffix=".wav"))
            audio_int16 = (audio * 32767).astype(np.int16)
            wavfile.write(temp_audio, 16000, audio_int16)
        else:
            temp_audio = audio_path

        # Run diarization
        print("Running diarization...", flush=True)
        from pyannote.audio import Pipeline, Audio
        from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )
        diarization = pipeline(str(temp_audio))

        # Load embedding model
        print("Extracting embeddings...", flush=True)
        embedding_model = PretrainedSpeakerEmbedding(
            "pyannote/embedding",
            use_auth_token=hf_token
        )

        audio_loader = Audio(sample_rate=16000, mono=True)
        waveform, sr = audio_loader(str(temp_audio))

        # Get segments per speaker
        speaker_segments = {}
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_segments:
                speaker_segments[speaker] = []
            speaker_segments[speaker].append((turn.start, turn.end))

        # Extract embeddings
        embeddings = {}
        for speaker, segs in speaker_segments.items():
            # Use longest segment
            longest = max(segs, key=lambda x: x[1] - x[0])
            start_sample = int(longest[0] * sr)
            end_sample = int(longest[1] * sr)

            if end_sample - start_sample < sr:  # Need at least 1 sec
                continue

            speaker_waveform = waveform[:, start_sample:end_sample]
            emb = embedding_model(speaker_waveform.unsqueeze(0))
            emb = emb.squeeze()
            # Handle both torch tensor and numpy array returns
            if hasattr(emb, 'cpu'):
                emb = emb.cpu().numpy()
            elif hasattr(emb, 'numpy'):
                emb = emb.numpy()
            embeddings[speaker] = emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            print(f"  Extracted embedding for {speaker}", flush=True)

        # Cleanup
        if temp_audio != audio_path and temp_audio.exists():
            temp_audio.unlink()

        print("\\n__RESULT_START__", flush=True)
        print(json.dumps({"success": True, "embeddings": embeddings, "segments": {k: len(v) for k, v in speaker_segments.items()}}), flush=True)
        print("__RESULT_END__", flush=True)

    except Exception as e:
        import traceback
        print("\\n__RESULT_START__", flush=True)
        print(json.dumps({"success": False, "error": str(e), "traceback": traceback.format_exc()}), flush=True)
        print("__RESULT_END__", flush=True)

if __name__ == "__main__":
    main()
'''


def get_names_from_transcript(transcript_path):
    """Extract speaker names used in transcript."""
    content = transcript_path.read_text()
    pattern = r'\[\d+:\d+\]\s+([^:]+):'
    speakers = set(re.findall(pattern, content))
    # Filter out generic labels
    return {s.strip() for s in speakers if not s.startswith('SPEAKER_') and s != 'UNKNOWN'}


def extract_fingerprints(audio_path, transcript_path, hf_token):
    """Extract fingerprints from audio, matching to names in transcript."""

    names = get_names_from_transcript(transcript_path)
    if not names:
        print(f"No named speakers in {transcript_path.name}")
        return {}

    print(f"Found named speakers: {', '.join(names)}")

    config = {
        "audio_path": str(audio_path),
        "hf_token": hf_token,
        "speaker_names": list(names),
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
            result_json = rest.split("__RESULT_END__")[0].strip()
            result = json.loads(result_json)
        else:
            print(f"Worker failed: {stdout}")
            return {}

        if not result["success"]:
            print(f"Error: {result['error']}")
            return {}

        return result["embeddings"], result["segments"]

    finally:
        try:
            os.unlink(worker_script)
        except OSError:
            pass


def match_embeddings_to_names(embeddings, segments, transcript_path):
    """Match diarization speakers to names based on segment counts."""
    content = transcript_path.read_text()

    # Count segments per name in transcript
    pattern = r'\[\d+:\d+\]\s+([^:]+):'
    name_counts = {}
    for name in re.findall(pattern, content):
        name = name.strip()
        name_counts[name] = name_counts.get(name, 0) + 1

    # Sort both by count
    sorted_names = sorted([(n, c) for n, c in name_counts.items()
                           if not n.startswith('SPEAKER_') and n != 'UNKNOWN'],
                          key=lambda x: -x[1])
    sorted_speakers = sorted(segments.items(), key=lambda x: -x[1])

    # Match by rank (most frequent speaker = most frequent name)
    matches = {}
    for i, (name, _) in enumerate(sorted_names):
        if i < len(sorted_speakers):
            speaker = sorted_speakers[i][0]
            if speaker in embeddings:
                matches[name] = embeddings[speaker]
                print(f"  Matched {speaker} -> {name}")

    return matches


def main():
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("HF_TOKEN not set")
        return

    recordings_dir = Path.home() / "Documents" / "MeetingRecordings"
    db = SpeakerDatabase()

    # Find meetings with named speakers
    meetings = []
    for audio in sorted(recordings_dir.glob("*.wav")):
        transcript = audio.with_suffix(".txt")
        if transcript.exists():
            names = get_names_from_transcript(transcript)
            if names:
                meetings.append((audio, transcript, names))

    if not meetings:
        print("No meetings with named speakers found.")
        return

    print(f"Found {len(meetings)} meeting(s) with named speakers:\n")
    for audio, transcript, names in meetings:
        print(f"  {audio.name}: {', '.join(names)}")
    print()

    for audio, transcript, names in meetings:
        print(f"\n{'='*50}")
        print(f"Processing: {audio.name}")
        print(f"{'='*50}")

        result = extract_fingerprints(audio, transcript, hf_token)
        if not result:
            continue

        embeddings, segments = result
        matches = match_embeddings_to_names(embeddings, segments, transcript)

        for name, embedding in matches.items():
            db.add_speaker(name, embedding)
            print(f"  ✓ Saved fingerprint for {name}")

    print(f"\n{'='*50}")
    print("Done! Known speakers:")
    for s in db.list_speakers():
        print(f"  • {s['name']} ({s['sample_count']} sample(s))")


if __name__ == "__main__":
    main()
