#!/usr/bin/env python3
"""Convenience script to run the Meeting Recorder app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.app import main

if __name__ == "__main__":
    main()
