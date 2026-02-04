"""File management for recordings, transcripts, and summaries."""

import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union


@dataclass
class MeetingRecord:
    """Represents a meeting with its associated files."""
    name: str
    audio_path: Optional[Path] = None
    transcript_path: Optional[Path] = None
    summary_path: Optional[Path] = None
    created: Optional[datetime] = None

    @property
    def has_audio(self) -> bool:
        return self.audio_path is not None and self.audio_path.exists()

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path is not None and self.transcript_path.exists()

    @property
    def has_summary(self) -> bool:
        return self.summary_path is not None and self.summary_path.exists()


class FileManager:
    """Manages storage of recordings, transcripts, and summaries."""

    AUDIO_EXTENSIONS: Set[str] = {".wav", ".mp3", ".m4a"}
    TRANSCRIPT_SUFFIX = ".txt"
    SUMMARY_SUFFIX = ".summary.md"

    def __init__(self, base_dir: Optional[Union[Path, str]] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path.home() / "Documents" / "MeetingRecordings"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_recordings_dir(self) -> Path:
        """Get the recordings directory."""
        return self.base_dir

    def list_meetings(self) -> List[MeetingRecord]:
        """List all meetings with their associated files."""
        meetings: Dict[str, MeetingRecord] = {}

        for file in self.base_dir.iterdir():
            if not file.is_file():
                continue

            base_name = file.stem
            if base_name.endswith(".summary"):
                base_name = base_name[:-8]

            if base_name not in meetings:
                meetings[base_name] = MeetingRecord(
                    name=base_name,
                    created=datetime.fromtimestamp(file.stat().st_ctime)
                )

            record = meetings[base_name]

            if file.suffix in self.AUDIO_EXTENSIONS:
                record.audio_path = file
            elif file.suffix == self.TRANSCRIPT_SUFFIX:
                record.transcript_path = file
            elif file.name.endswith(self.SUMMARY_SUFFIX):
                record.summary_path = file

        sorted_meetings = sorted(
            meetings.values(),
            key=lambda m: m.created or datetime.min,
            reverse=True
        )
        return sorted_meetings

    def get_meeting(self, name: str) -> Optional[MeetingRecord]:
        """Get a specific meeting by name."""
        for meeting in self.list_meetings():
            if meeting.name == name:
                return meeting
        return None

    def get_latest_meeting(self) -> Optional[MeetingRecord]:
        """Get the most recent meeting."""
        meetings = self.list_meetings()
        return meetings[0] if meetings else None

    def get_latest_recording(self) -> Optional[Path]:
        """Get the path to the most recent audio recording."""
        latest = self.get_latest_meeting()
        return latest.audio_path if latest else None

    def get_latest_transcript(self) -> Optional[Path]:
        """Get the path to the most recent transcript."""
        for meeting in self.list_meetings():
            if meeting.has_transcript:
                return meeting.transcript_path
        return None

    def open_recordings_folder(self) -> None:
        """Open the recordings folder in Finder."""
        subprocess.run(["open", str(self.base_dir)])

    def open_file(self, path: Path) -> None:
        """Open a file with the default application."""
        subprocess.run(["open", str(path)])

    def get_transcript_path_for_audio(self, audio_path: Path) -> Path:
        """Get the expected transcript path for an audio file."""
        return audio_path.with_suffix(self.TRANSCRIPT_SUFFIX)

    def get_summary_path_for_transcript(self, transcript_path: Path) -> Path:
        """Get the expected summary path for a transcript file."""
        return transcript_path.with_suffix(self.SUMMARY_SUFFIX)

    def delete_meeting(self, name: str) -> bool:
        """Delete all files associated with a meeting."""
        meeting = self.get_meeting(name)
        if not meeting:
            return False

        deleted = False
        for path in [meeting.audio_path, meeting.transcript_path, meeting.summary_path]:
            if path and path.exists():
                path.unlink()
                deleted = True

        return deleted

    def get_disk_usage(self) -> Dict[str, int]:
        """Get disk usage statistics for the recordings folder."""
        audio_size = 0
        transcript_size = 0
        summary_size = 0

        for file in self.base_dir.iterdir():
            if not file.is_file():
                continue

            size = file.stat().st_size

            if file.suffix in self.AUDIO_EXTENSIONS:
                audio_size += size
            elif file.suffix == self.TRANSCRIPT_SUFFIX:
                transcript_size += size
            elif file.name.endswith(self.SUMMARY_SUFFIX):
                summary_size += size

        return {
            "audio": audio_size,
            "transcripts": transcript_size,
            "summaries": summary_size,
            "total": audio_size + transcript_size + summary_size
        }

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """Format size in bytes to human readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
