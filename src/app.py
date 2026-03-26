#!/usr/bin/env python3
"""Meeting Recorder — macOS menu bar + window application.

Entry point that wires together the backend (recorder, transcriber, etc.)
with the frontend (pywebview window + PyObjC status bar icon).
"""

import logging
import sys

log = logging.getLogger(__name__)


def check_dependencies():
    """Check if required dependencies are installed."""
    missing = []
    for module, package in [
        ("webview", "pywebview"),
        ("sounddevice", "sounddevice"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("requests", "requests"),
    ]:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("Missing required dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with: pip install -r requirements.txt")
        sys.exit(1)


def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    check_dependencies()

    import webview
    from pathlib import Path

    from .config import Config
    from .audio import AudioRecorder, AudioDeviceManager
    from .transcription import SmartTranscriber
    from .summarization import OllamaClient
    from .storage import FileManager
    from .ui_bridge import UIBridge
    from .status_bar import StatusBarController

    # Create backend objects
    config = Config()
    recorder = AudioRecorder()
    device_manager = AudioDeviceManager()
    transcriber = SmartTranscriber(
        prefer_diarization=config.prefer_diarization,
        whisper_model=config.whisper_model,
        diarization_model=config.diarization_model,
    )
    ollama = OllamaClient(model=config.ollama_model)
    file_manager = FileManager()

    # Create bridge (API surface for the web UI)
    bridge = UIBridge(
        config=config,
        recorder=recorder,
        device_manager=device_manager,
        transcriber=transcriber,
        ollama=ollama,
        file_manager=file_manager,
    )

    # Create window (preloaded, starts hidden)
    ui_dir = Path(__file__).parent / "ui"
    window = webview.create_window(
        "Meeting Recorder",
        url=str(ui_dir / "index.html"),
        js_api=bridge,
        width=380,
        height=540,
        resizable=True,
        hidden=True,
    )
    bridge._window = window

    # Intercept window close — hide instead of quit
    _quitting = [False]

    def on_closing():
        if not _quitting[0]:
            window.hide()
            return False
        return True

    window.events.closing += on_closing

    # Status bar (menu bar icon)
    def toggle_window():
        if window.hidden:
            window.show()
        else:
            window.hide()

    def quit_app():
        _quitting[0] = True
        bridge.shutdown()
        window.destroy()

    status_bar = StatusBarController(
        toggle_window_fn=toggle_window,
        toggle_recording_fn=bridge.toggle_recording,
        quit_fn=quit_app,
    )
    bridge._status_bar = status_bar

    def on_start():
        # Hide from Dock once the Cocoa event loop is running
        try:
            import AppKit
            AppKit.NSApp.setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory
            )
        except Exception:
            log.warning("Could not hide from Dock", exc_info=True)
        status_bar.setup()

    # Start (blocks on main thread — runs Cocoa event loop)
    webview.start(func=on_start, debug=False)


if __name__ == "__main__":
    main()
