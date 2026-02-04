"""Dual-stream audio recorder for mic and system audio."""

import threading
import queue
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Union

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from .devices import AudioDeviceManager, AudioDevice


class AudioRecorder:
    """Records audio from microphone and/or system audio (via BlackHole)."""

    SAMPLE_RATE = 44100
    CHANNELS = 1
    DTYPE = np.float32
    BLOCK_SIZE = 1024

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
        self._mic_data: List[np.ndarray] = []
        self._system_data: List[np.ndarray] = []

        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self._writer_thread: Optional[threading.Thread] = None

        self._current_filepath: Optional[Path] = None

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

    def _writer_loop(self):
        """Background thread to collect audio data from queues."""
        while self._recording or not self._mic_queue.empty() or not self._system_queue.empty():
            try:
                while True:
                    data = self._mic_queue.get_nowait()
                    self._mic_data.append(data)
            except queue.Empty:
                pass

            try:
                while True:
                    data = self._system_queue.get_nowait()
                    self._system_data.append(data)
            except queue.Empty:
                pass

            time.sleep(0.01)

    def start_recording(self) -> Path:
        """Start recording audio. Returns the output file path."""
        if self._recording:
            raise RuntimeError("Already recording")

        if not self._mic_device and not self._system_device:
            self.auto_configure()

        if not self._mic_device and not self._system_device:
            raise RuntimeError("No audio devices available")

        self._mic_data = []
        self._system_data = []

        while not self._mic_queue.empty():
            self._mic_queue.get_nowait()
        while not self._system_queue.empty():
            self._system_queue.get_nowait()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_filepath = self.output_dir / f"meeting_{timestamp}.wav"

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
        """Stop recording and save the audio file. Returns the file path."""
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
            self._writer_thread.join(timeout=2.0)
            self._writer_thread = None

        combined = self._mix_audio()

        audio_int16 = (combined * 32767).astype(np.int16)
        wavfile.write(self._current_filepath, self.SAMPLE_RATE, audio_int16)

        self._start_time = None
        return self._current_filepath

    def _mix_audio(self) -> np.ndarray:
        """Mix microphone and system audio together."""
        mic_audio = np.concatenate(self._mic_data) if self._mic_data else np.array([], dtype=self.DTYPE)
        system_audio = np.concatenate(self._system_data) if self._system_data else np.array([], dtype=self.DTYPE)

        if mic_audio.ndim > 1:
            mic_audio = mic_audio.mean(axis=1)
        if system_audio.ndim > 1:
            system_audio = system_audio.mean(axis=1)

        if len(mic_audio) == 0:
            return system_audio
        if len(system_audio) == 0:
            return mic_audio

        max_len = max(len(mic_audio), len(system_audio))
        if len(mic_audio) < max_len:
            mic_audio = np.pad(mic_audio, (0, max_len - len(mic_audio)))
        if len(system_audio) < max_len:
            system_audio = np.pad(system_audio, (0, max_len - len(system_audio)))

        mixed = (mic_audio * 0.5 + system_audio * 0.5)

        max_val = np.max(np.abs(mixed))
        if max_val > 1.0:
            mixed = mixed / max_val

        return mixed

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
