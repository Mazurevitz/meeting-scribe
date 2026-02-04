#!/usr/bin/env python3
"""Meeting AI Notes - macOS Meeting Recorder Application.

A menu bar app that records meetings, transcribes locally with Whisper,
and summarizes with Ollama.
"""

import sys


def check_dependencies():
    """Check if required dependencies are installed."""
    missing = []

    try:
        import rumps
    except ImportError:
        missing.append("rumps")

    try:
        import sounddevice
    except ImportError:
        missing.append("sounddevice")

    try:
        import numpy
    except ImportError:
        missing.append("numpy")

    try:
        import scipy
    except ImportError:
        missing.append("scipy")

    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print("Missing required dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with: pip install -r requirements.txt")
        sys.exit(1)


def main():
    """Main entry point."""
    check_dependencies()

    from .menu_bar import run
    run()


if __name__ == "__main__":
    main()
