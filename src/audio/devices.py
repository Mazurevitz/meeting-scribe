"""Audio device discovery and management."""

from typing import List, Optional
import sounddevice as sd
from dataclasses import dataclass


@dataclass
class AudioDevice:
    """Represents an audio input device."""
    index: int
    name: str
    channels: int
    sample_rate: float
    is_blackhole: bool = False


class AudioDeviceManager:
    """Discovers and manages audio input devices."""

    BLACKHOLE_NAMES = ["BlackHole 2ch", "BlackHole 16ch", "BlackHole"]

    def __init__(self):
        self._devices: List[AudioDevice] = []
        self.refresh_devices()

    def refresh_devices(self) -> None:
        """Refresh the list of available audio devices."""
        self._devices = []
        devices = sd.query_devices()

        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                is_blackhole = any(
                    bh in device["name"] for bh in self.BLACKHOLE_NAMES
                )
                self._devices.append(AudioDevice(
                    index=i,
                    name=device["name"],
                    channels=device["max_input_channels"],
                    sample_rate=device["default_samplerate"],
                    is_blackhole=is_blackhole
                ))

    def get_all_input_devices(self) -> List[AudioDevice]:
        """Return all input devices."""
        return self._devices.copy()

    def get_microphone_devices(self) -> List[AudioDevice]:
        """Return non-BlackHole input devices (microphones)."""
        return [d for d in self._devices if not d.is_blackhole]

    def get_blackhole_device(self) -> Optional[AudioDevice]:
        """Return the BlackHole device if available."""
        for device in self._devices:
            if device.is_blackhole:
                return device
        return None

    def get_default_microphone(self) -> Optional[AudioDevice]:
        """Return the default microphone device."""
        try:
            default_idx = sd.default.device[0]
            if default_idx is not None:
                for device in self._devices:
                    if device.index == default_idx and not device.is_blackhole:
                        return device
        except Exception:
            pass

        mics = self.get_microphone_devices()
        return mics[0] if mics else None

    def get_device_by_name(self, name: str) -> Optional[AudioDevice]:
        """Find a device by name (partial match)."""
        for device in self._devices:
            if name.lower() in device.name.lower():
                return device
        return None

    def is_blackhole_available(self) -> bool:
        """Check if BlackHole is installed and available."""
        return self.get_blackhole_device() is not None


def list_devices() -> None:
    """Print all available audio devices (utility function)."""
    manager = AudioDeviceManager()

    print("Available Input Devices:")
    print("-" * 50)

    for device in manager.get_all_input_devices():
        bh_marker = " [BlackHole]" if device.is_blackhole else ""
        print(f"  [{device.index}] {device.name}{bh_marker}")
        print(f"      Channels: {device.channels}, Sample Rate: {device.sample_rate}")

    print()
    blackhole = manager.get_blackhole_device()
    if blackhole:
        print(f"✓ BlackHole detected: {blackhole.name}")
    else:
        print("✗ BlackHole not detected - system audio capture unavailable")


if __name__ == "__main__":
    list_devices()
