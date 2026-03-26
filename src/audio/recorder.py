"""Dual-stream audio recorder for mic and system audio.

Records mic and system audio to separate temp files, then mixes
them into a single WAV at stop time. This avoids timing/stuttering
issues from trying to mix streams in realtime.
"""

import struct
import threading
import queue
import time
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Union

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from ..config import RECORDINGS_DIR
from .devices import AudioDeviceManager, AudioDevice

_WAV_HEADER_SIZE = 44


def _write_wav_header(f, sample_rate: int, channels: int, num_samples: int):
    """Write a complete WAV header."""
    data_size = num_samples * channels * 2
    f.write(b'RIFF')
    f.write(struct.pack('<I', 36 + data_size))
    f.write(b'WAVE')
    f.write(b'fmt ')
    f.write(struct.pack('<I', 16))
    f.write(struct.pack('<H', 1))  # PCM
    f.write(struct.pack('<H', channels))
    f.write(struct.pack('<I', sample_rate))
    f.write(struct.pack('<I', sample_rate * channels * 2))
    f.write(struct.pack('<H', channels * 2))
    f.write(struct.pack('<H', 16))  # 16-bit
    f.write(b'data')
    f.write(struct.pack('<I', data_size))


class _StreamWriter:
    """Writes a single audio stream to a temp WAV file."""

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._queue: queue.Queue = queue.Queue()
        self._file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._path = Path(self._file.name)
        self._samples_written = 0
        # Write placeholder header
        _write_wav_header(self._file, sample_rate, 1, 0)

    def put(self, data: np.ndarray):
        self._queue.put(data)

    def flush_queue(self):
        """Drain queue and write to disk."""
        chunks = []
        try:
            while True:
                chunks.append(self._queue.get_nowait())
        except queue.Empty:
            pass

        if not chunks:
            return

        audio = np.concatenate(chunks)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        samples = (audio * 32767).astype(np.int16)
        self._file.write(samples.tobytes())
        self._samples_written += len(samples)

    def finalize(self) -> Path:
        """Flush remaining data, patch header, close file. Returns path."""
        self.flush_queue()
        # Patch WAV header
        self._file.seek(0)
        _write_wav_header(self._file, self.sample_rate, 1, self._samples_written)
        self._file.close()
        return self._path

    def cleanup(self):
        """Delete the temp file."""
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass


class AudioRecorder:
    """Records audio from microphone and/or system audio (via BlackHole).

    Each source streams to its own temp file. At stop time, both files
    are read back and mixed into the final WAV. This eliminates stutter
    caused by realtime mixing of streams with slightly different timing.
    """

    DEFAULT_SAMPLE_RATE = 48000
    CHANNELS = 1
    DTYPE = np.float32
    BLOCK_SIZE = 1024

    def __init__(self, output_dir: Optional[Union[Path, str]] = None):
        self.device_manager = AudioDeviceManager()
        self.output_dir = Path(output_dir) if output_dir else RECORDINGS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.SAMPLE_RATE = self.DEFAULT_SAMPLE_RATE
        self._recording = False
        self._start_time: Optional[float] = None
        self._mic_device: Optional[AudioDevice] = None
        self._system_device: Optional[AudioDevice] = None

        self._mic_writer: Optional[_StreamWriter] = None
        self._sys_writer: Optional[_StreamWriter] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self._writer_thread: Optional[threading.Thread] = None

        self._current_filepath: Optional[Path] = None

    def set_microphone(self, device: Optional[AudioDevice]) -> None:
        self._mic_device = device

    def set_system_audio_device(self, device: Optional[AudioDevice]) -> None:
        self._system_device = device

    def auto_configure(self) -> Tuple[Optional[AudioDevice], Optional[AudioDevice]]:
        self._mic_device = self.device_manager.get_default_microphone()
        self._system_device = self.device_manager.get_blackhole_device()
        return self._mic_device, self._system_device

    def _detect_sample_rate(self):
        for device in [self._system_device, self._mic_device]:
            if device is not None:
                try:
                    info = sd.query_devices(device.index)
                    rate = int(info["default_samplerate"])
                    if rate > 0:
                        return rate
                except Exception:
                    pass
        return self.DEFAULT_SAMPLE_RATE

    def _create_callback(self, writer: _StreamWriter):
        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            writer.put(indata.copy())
        return callback

    def _writer_loop(self):
        """Periodically flush both stream writers to disk."""
        while self._recording:
            if self._mic_writer:
                self._mic_writer.flush_queue()
            if self._sys_writer:
                self._sys_writer.flush_queue()
            time.sleep(0.05)

        # Final drain
        if self._mic_writer:
            self._mic_writer.flush_queue()
        if self._sys_writer:
            self._sys_writer.flush_queue()

    def start_recording(self) -> Path:
        if self._recording:
            raise RuntimeError("Already recording")

        if not self._mic_device and not self._system_device:
            self.auto_configure()
        if not self._mic_device and not self._system_device:
            raise RuntimeError("No audio devices available")

        self.SAMPLE_RATE = self._detect_sample_rate()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_filepath = self.output_dir / f"meeting_{timestamp}.wav"

        # Create stream writers
        if self._mic_device:
            self._mic_writer = _StreamWriter(self.SAMPLE_RATE)
        if self._system_device:
            self._sys_writer = _StreamWriter(self.SAMPLE_RATE)

        self._recording = True
        self._start_time = time.time()

        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        if self._mic_device and self._mic_writer:
            self._mic_stream = sd.InputStream(
                device=self._mic_device.index,
                channels=self.CHANNELS,
                samplerate=self.SAMPLE_RATE,
                dtype=self.DTYPE,
                blocksize=self.BLOCK_SIZE,
                callback=self._create_callback(self._mic_writer),
            )
            self._mic_stream.start()

        if self._system_device and self._sys_writer:
            self._system_stream = sd.InputStream(
                device=self._system_device.index,
                channels=self.CHANNELS,
                samplerate=self.SAMPLE_RATE,
                dtype=self.DTYPE,
                blocksize=self.BLOCK_SIZE,
                callback=self._create_callback(self._sys_writer),
            )
            self._system_stream.start()

        return self._current_filepath

    def stop_recording(self) -> Path:
        if not self._recording:
            raise RuntimeError("Not recording")

        self._recording = False

        # Stop streams
        for stream in [self._mic_stream, self._system_stream]:
            if stream:
                stream.stop()
                stream.close()
        self._mic_stream = None
        self._system_stream = None

        # Wait for writer thread
        if self._writer_thread:
            self._writer_thread.join(timeout=10.0)
            self._writer_thread = None

        # Finalize temp files and mix
        mic_path = self._mic_writer.finalize() if self._mic_writer else None
        sys_path = self._sys_writer.finalize() if self._sys_writer else None

        self._mix_files(mic_path, sys_path, self._current_filepath)

        # Cleanup temp files
        if self._mic_writer:
            self._mic_writer.cleanup()
            self._mic_writer = None
        if self._sys_writer:
            self._sys_writer.cleanup()
            self._sys_writer = None

        self._start_time = None
        return self._current_filepath

    def _mix_files(self, mic_path: Optional[Path], sys_path: Optional[Path], output_path: Path):
        """Read both temp WAVs and mix into final output."""
        mic_audio = np.array([], dtype=np.float32)
        sys_audio = np.array([], dtype=np.float32)

        if mic_path and mic_path.exists():
            sr, data = wavfile.read(mic_path)
            mic_audio = data.astype(np.float32) / 32768.0
            if mic_audio.ndim > 1:
                mic_audio = mic_audio.mean(axis=1)

        if sys_path and sys_path.exists():
            sr, data = wavfile.read(sys_path)
            sys_audio = data.astype(np.float32) / 32768.0
            if sys_audio.ndim > 1:
                sys_audio = sys_audio.mean(axis=1)

        # Mix
        if len(mic_audio) == 0 and len(sys_audio) == 0:
            mixed = np.zeros(self.SAMPLE_RATE, dtype=np.float32)  # 1s silence
        elif len(mic_audio) == 0:
            mixed = sys_audio
        elif len(sys_audio) == 0:
            mixed = mic_audio
        else:
            max_len = max(len(mic_audio), len(sys_audio))
            if len(mic_audio) < max_len:
                mic_audio = np.pad(mic_audio, (0, max_len - len(mic_audio)))
            if len(sys_audio) < max_len:
                sys_audio = np.pad(sys_audio, (0, max_len - len(sys_audio)))
            mixed = mic_audio * 0.5 + sys_audio * 0.5

        max_val = np.max(np.abs(mixed))
        if max_val > 1.0:
            mixed = mixed / max_val

        audio_int16 = (mixed * 32767).astype(np.int16)
        wavfile.write(str(output_path), self.SAMPLE_RATE, audio_int16)

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def duration_formatted(self) -> str:
        seconds = int(self.duration)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def current_filepath(self) -> Optional[Path]:
        return self._current_filepath
