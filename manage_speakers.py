#!/usr/bin/env python3
"""CLI tool to manage speaker voice profiles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.transcription.speaker_db import SpeakerDatabase


def main():
    db = SpeakerDatabase()

    if len(sys.argv) < 2:
        print("Speaker Management")
        print("==================")
        print()
        print("Usage:")
        print("  python manage_speakers.py list              - List known speakers")
        print("  python manage_speakers.py rename OLD NEW    - Rename a speaker")
        print("  python manage_speakers.py remove NAME       - Remove a speaker")
        print()
        print("To add new speakers: run a transcription, then use the menu bar")
        print("app or call transcriber.name_speaker('SPEAKER_XX', 'Name')")
        return

    cmd = sys.argv[1].lower()

    if cmd == "list":
        speakers = db.list_speakers()
        if not speakers:
            print("No speakers in database yet.")
            print("Run a transcription and name the speakers to build the database.")
        else:
            print(f"Known speakers ({len(speakers)}):")
            print()
            for s in speakers:
                print(f"  • {s['name']} ({s['sample_count']} samples, updated: {s['updated'][:10]})")

    elif cmd == "rename" and len(sys.argv) == 4:
        old_name = sys.argv[2]
        new_name = sys.argv[3]
        if db.rename_speaker(old_name, new_name):
            print(f"Renamed '{old_name}' to '{new_name}'")
        else:
            print(f"Speaker '{old_name}' not found")

    elif cmd == "remove" and len(sys.argv) == 3:
        name = sys.argv[2]
        if db.remove_speaker(name):
            print(f"Removed '{name}'")
        else:
            print(f"Speaker '{name}' not found")

    else:
        print(f"Unknown command: {cmd}")
        print("Run without arguments for help.")


if __name__ == "__main__":
    main()
