#!/usr/bin/env python3
"""Interactive tool to name speakers from a transcript."""

import sys
import re
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.transcription.speaker_db import SpeakerDatabase

PEOPLE_FILE = Path.home() / ".meeting-recorder" / "people.json"


def load_known_people():
    """Load known people list."""
    if PEOPLE_FILE.exists():
        try:
            with open(PEOPLE_FILE) as f:
                data = json.load(f)
                return data.get("people", {}), data.get("teams", {})
        except (json.JSONDecodeError, IOError):
            pass
    return {}, {}


def show_known_people():
    """Display known people grouped by team."""
    people, teams = load_known_people()
    if not people:
        return

    print("Known people:")
    for team_id, team_data in teams.items():
        members = team_data.get("members", [])
        print(f"  {team_data['name']}: {', '.join(members)}")

    # Show people without teams
    no_team = [p["name"] for p in people.values() if not p.get("team")]
    if no_team:
        print(f"  Other: {', '.join(no_team)}")
    print()


def get_latest_transcript():
    """Find the most recent transcript file."""
    recordings_dir = Path.home() / "Documents" / "MeetingRecordings"
    if not recordings_dir.exists():
        return None

    transcripts = sorted(recordings_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    # Skip summary files
    transcripts = [t for t in transcripts if not t.name.endswith('.summary.md')]
    return transcripts[0] if transcripts else None


def parse_transcript(filepath):
    """Parse transcript and extract speaker segments."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Pattern: [MM:SS] SPEAKER_XX: or [MM:SS] Name:
    pattern = r'\[(\d+:\d+)\]\s+([^:]+):\s*\n\s+(.+?)(?=\n\n|\n\[|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)

    speakers = {}
    for timestamp, speaker, text in matches:
        speaker = speaker.strip()
        text = text.strip()[:200]  # First 200 chars

        if speaker not in speakers:
            speakers[speaker] = []
        speakers[speaker].append((timestamp, text))

    return speakers


def get_speaker_summary(segments, max_quotes=2):
    """Get a brief summary of what a speaker said."""
    quotes = []
    for timestamp, text in segments[:max_quotes]:
        # Clean up and truncate
        text = ' '.join(text.split())  # Normalize whitespace
        if len(text) > 100:
            text = text[:100] + "..."
        quotes.append(f'  [{timestamp}] "{text}"')
    return '\n'.join(quotes)


def main():
    # Find transcript
    if len(sys.argv) > 1:
        transcript_path = Path(sys.argv[1])
    else:
        transcript_path = get_latest_transcript()

    if not transcript_path or not transcript_path.exists():
        print("No transcript found.")
        print("Usage: python name_speakers.py [transcript.txt]")
        return

    print(f"Transcript: {transcript_path.name}")
    print("=" * 50)
    print()

    # Show known people for reference
    show_known_people()

    # Parse transcript
    speakers = parse_transcript(transcript_path)

    if not speakers:
        print("No speakers found in transcript.")
        return

    # Filter to only unnamed speakers (SPEAKER_XX or UNKNOWN)
    unnamed = {k: v for k, v in speakers.items()
               if k.startswith('SPEAKER_') or k == 'UNKNOWN'}

    if not unnamed:
        print("All speakers are already named!")
        print("\nCurrent speakers:")
        for name in speakers.keys():
            print(f"  • {name}")
        return

    db = SpeakerDatabase()
    print(f"Found {len(unnamed)} unnamed speaker(s):\n")

    # Store assignments for batch update
    assignments = {}

    for speaker, segments in unnamed.items():
        print(f"═══ {speaker} ({len(segments)} segments) ═══")
        print(get_speaker_summary(segments))
        print()

        name = input(f"Name for {speaker} (Enter to skip): ").strip()

        if name:
            assignments[speaker] = name
            print(f"  ✓ Will assign: {speaker} → {name}")
        else:
            print(f"  ⊘ Skipped")
        print()

    if not assignments:
        print("No names assigned.")
        return

    # Confirm
    print("=" * 50)
    print("Summary of assignments:")
    for speaker, name in assignments.items():
        print(f"  {speaker} → {name}")
    print()

    confirm = input("Save these assignments? [Y/n]: ").strip().lower()
    if confirm in ('', 'y', 'yes'):
        # Update transcript file
        with open(transcript_path, 'r') as f:
            content = f.read()

        for speaker, name in assignments.items():
            content = content.replace(f"] {speaker}:", f"] {name}:")

        with open(transcript_path, 'w') as f:
            f.write(content)

        print(f"\n✓ Updated {transcript_path.name}")
        print("\nNote: Voice fingerprints will be saved after next transcription")
        print("when these speakers are detected again.")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
