"""Dual-stream audio recorder for mic and system audio.

Streams audio to disk in chunks to avoid OOM on long recordings.
"""

import struct
import threading
import queue
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Union

import numpy as np
import sounddevice as sd

from .devices import AudioDeviceManager, AudioDevice

# WAV header size (44 bytes) — we write a placeholder then patch at end
_WAV_HEADER_SIZE = 44


def _write_wav_header(f, sample_rate: int, channels: int, num_samples: int):
    """Write a complete WAV header at the current position."""
    data_size = num_samples * channels * 2  # 16-bit = 2 bytes
    f.write(b'RIFF')
    f.write(struct.pack('<I', 36 + data_size))
    f.write(b'WAVE')
    f.write(b'fmt ')
    f.write(struct.pack('<I', 16))              # chunk size
    f.write(struct.pack('<H', 1))               # PCM
    f.write(struct.pack('<H', channels))
    f.write(struct.pack('<I', sample_rate))
    f.write(struct.pack('<I', sample_rate * channels * 2))  # byte rate
    f.write(struct.pack('<H', channels * 2))    # block align
    f.write(struct.pack('<H', 16))              # bits per sample
    f.write(b'data')
    f.write(struct.pack('<I', data_size))


class AudioRecorder:
    """Records audio from microphone and/or system audio (via BlackHole).

    Streams mixed audio to disk every few seconds so memory stays flat
    regardless of recording length. If the process dies mid-recording,
    the WAV file is still readable up to the last flushed chunk.
    """

    SAMPLE_RATE = 44100
    CHANNELS = 1
    DTYPE = np.float32
    BLOCK_SIZE = 1024
    FLUSH_INTERVAL = 5.0  # seconds between disk flushes

    def __init__(self, output_dir: Optional[Union[Path, str]] = None):
        self.device_manager = AudioDeviceManager()
        self.output_dir = Path(output_dir) if output_dir else Path.home() / "Documents" / "MeetingRecordings"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._recording = False
        self._start_time: Optional[float] = None
        self._mic_device: Optional[AudioDevice] = None
        self._system_device: Optional[AudioDevice] = None

        self._mic_queue: queue.Queue = queue.Queue()
        self._system_queue: queue.Queue = queue.Queue()

        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self._writer_thread: Optional[threading.Thread] = None

        self._current_filepath: Optional[Path] = None
        self._wav_file = None
        self._total_samples_written = 0

    def set_microphone(self, device: Optional[AudioDevice]) -> None:
        """Set the microphone device to use."""
        self._mic_device = device

    def set_system_audio_device(self, device: Optional[AudioDevice]) -> None:
        """Set the system audio device (BlackHole) to use."""
        self._system_device = device

    def auto_configure(self) -> Tuple[Optional[AudioDevice], Optional[AudioDevice]]:
        """Auto-configure devices with default mic and BlackHole if available."""
        self._mic_device = self.device_manager.get_default_microphone()
        self._system_device = self.device_manager.get_blackhole_device()
        return self._mic_device, self._system_device

    def _create_mic_callback(self):
        """Create callback for microphone stream."""
        def callback(indata, frames, time_info, status):
            if status:
                print(f"Mic status: {status}")
            self._mic_queue.put(indata.copy())
        return callback

    def _create_system_callback(self):
        """Create callback for system audio stream."""
        def callback(indata, frames, time_info, status):
            if status:
                print(f"System status: {status}")
            self._system_queue.put(indata.copy())
        return callback

    def _drain_queue(self, q: queue.Queue):
        """Drain all items from a queue into a list."""
        chunks = []
        try:
            while True:
                chunks.append(q.get_nowait())
        except queue.Empty:
            pass
        return chunks

    def _mix_and_flush(self, mic_chunks, sys_chunks):
        """Mix mic + system chunks and write int16 samples to disk."""
        mic_audio = np.concatenate(mic_chunks) if mic_chunks else np.array([], dtype=self.DTYPE)
        sys_audio = np.concatenate(sys_chunks) if sys_chunks else np.array([], dtype=self.DTYPE)

        if mic_audio.ndim > 1:
            mic_audio = mic_audio.mean(axis=1)
        if sys_audio.ndim > 1:
            sys_audio = sys_audio.mean(axis=1)

        if len(mic_audio) == 0 and len(sys_audio) == 0:
            return

        if len(mic_audio) == 0:
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

        samples_int16 = (mixed * 32767).astype(np.int16)
        self._wav_file.write(samples_int16.tobytes())
        self._total_samples_written += len(samples_int16)

    def _writer_loop(self):
        """Background thread: periodically drain queues and flush to disk."""
        last_flush = time.time()

        while self._recording or not self._mic_queue.empty() or not self._system_queue.empty():
            mic_chunks = self._drain_queue(self._mic_queue)
            sys_chunks = self._drain_queue(self._system_queue)

            if mic_chunks or sys_chunks:
                try:
                    self._mix_and_flush(mic_chunks, sys_chunks)
                except Exception as e:
                    print(f"Audio flush error: {e}")

            now = time.time()
            if now - last_flush >= self.FLUSH_INTERVAL:
                try:
                    self._wav_file.flush()
                except Exception:
                    pass
                last_flush = now

            time.sleep(0.01)

        # Final flush
        try:
            self._wav_file.flush()
        except Exception:
            pass

    def start_recording(self) -> Path:
        """Start recording audio. Returns the output file path."""
        if self._recording:
            raise RuntimeError("Already recording")

        if not self._mic_device and not self._system_device:
            self.auto_configure()

        if not self._mic_device and not self._system_device:
            raise RuntimeError("No audio devices available")

        while not self._mic_queue.empty():
            self._mic_queue.get_nowait()
        while not self._system_queue.empty():
            self._system_queue.get_nowait()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_filepath = self.output_dir / f"meeting_{timestamp}.wav"

        # Open WAV file and write placeholder header
        self._wav_file = open(self._current_filepath, 'wb')
        self._total_samples_written = 0
        _write_wav_header(self._wav_file, self.SAMPLE_RATE, self.CHANNELS, 0)

        self._recording = True
        self._start_time = time.time()

        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        if self._mic_device:
            self._mic_stream = sd.InputStream(
                device=self._mic_device.index,
                channels=self.CHANNELS,
                samplerate=self.SAMPLE_RATE,
                dtype=self.DTYPE,
                blocksize=self.BLOCK_SIZE,
                callback=self._create_mic_callback()
            )
            self._mic_stream.start()

        if self._system_device:
            self._system_stream = sd.InputStream(
                device=self._system_device.index,
                channels=self.CHANNELS,
                samplerate=self.SAMPLE_RATE,
                dtype=self.DTYPE,
                blocksize=self.BLOCK_SIZE,
                callback=self._create_system_callback()
            )
            self._system_stream.start()

        return self._current_filepath

    def stop_recording(self) -> Path:
        """Stop recording and finalize the WAV file. Returns the file path."""
        if not self._recording:
            raise RuntimeError("Not recording")

        self._recording = False

        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
            self._mic_stream = None

        if self._system_stream:
            self._system_stream.stop()
            self._system_stream.close()
            self._system_stream = None

        if self._writer_thread:
            self._writer_thread.join(timeout=10.0)
            self._writer_thread = None

        # Patch WAV header with final sample count
        if self._wav_file and not self._wav_file.closed:
            self._wav_file.seek(0)
            _write_wav_header(
                self._wav_file, self.SAMPLE_RATE, self.CHANNELS,
                self._total_samples_written
            )
            self._wav_file.close()
            self._wav_file = None

        self._start_time = None
        return self._current_filepath

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    @property
    def duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def duration_formatted(self) -> str:
        """Get current recording duration as MM:SS string."""
        seconds = int(self.duration)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def current_filepath(self) -> Optional[Path]:
        """Get the current recording file path."""
        return self._current_filepath
