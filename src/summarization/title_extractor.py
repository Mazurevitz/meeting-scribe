"""Extract meeting metadata (title, tags, people) from a summary file.

Parses the markdown summary to produce:
- A short title (from topics or first summary sentence)
- Topic tags (from "## Topics Discussed")
- People mentioned (from "## People Mentioned")
"""

from pathlib import Path
from typing import Dict, List, Optional

# Common filler prefixes that don't add meaning to a title
_FILLER_PREFIXES = [
    "This meeting ", "The meeting ", "This was a ",
    "The team ", "This transcript ",
    "This meeting transcript ",
]


def extract_metadata(summary_path: Path) -> Dict:
    """Parse a summary file and return title, tags, and people."""
    try:
        text = summary_path.read_text(encoding="utf-8")
    except Exception:
        return {"title": None, "tags": [], "people": []}

    lines = text.split("\n")

    return {
        "title": _title_from_topics(lines) or _title_from_summary(lines),
        "tags": _extract_tags(lines),
        "people": _extract_people(lines),
    }


def extract_title(summary_path: Path) -> Optional[str]:
    """Parse a summary file and return a short descriptive title."""
    return extract_metadata(summary_path)["title"]


def _extract_tags(lines: list) -> List[str]:
    """Extract topic tags from '## Topics Discussed'."""
    tags = []
    in_section = False
    for line in lines:
        if "## topics" in line.lower():
            in_section = True
            continue
        if in_section and line.startswith("##"):
            break
        if in_section and line.strip().startswith("- "):
            tag = line.strip().lstrip("- ").split(":")[0].strip()
            if 2 < len(tag) < 40:
                tags.append(tag)
    return tags[:5]


def _extract_people(lines: list) -> List[str]:
    """Extract people from '## People Mentioned'."""
    people = []
    in_section = False
    for line in lines:
        if "## people" in line.lower():
            in_section = True
            continue
        if in_section and line.startswith("##"):
            break
        if in_section and line.strip().startswith("- "):
            name = line.strip().lstrip("- ").split(":")[0].strip().strip("*")
            if name and len(name) < 30:
                people.append(name)
    return people[:5]


def _title_from_topics(lines: list) -> Optional[str]:
    """Extract the first topic from '## Topics Discussed'."""
    in_topics = False
    for line in lines:
        if "## topics" in line.lower():
            in_topics = True
            continue
        if in_topics and line.strip().startswith("- "):
            topic = line.strip().lstrip("- ").split(":")[0].strip()
            if len(topic) > 5:
                return topic[:60]
        if in_topics and line.startswith("##"):
            break
    return None


def _title_from_summary(lines: list) -> Optional[str]:
    """Extract and clean the first sentence from '## Summary'."""
    in_summary = False
    for line in lines:
        if line.strip().lower().startswith("## summary"):
            in_summary = True
            continue
        if in_summary and line.strip():
            sentence = line.strip()

            for prefix in _FILLER_PREFIXES:
                if sentence.startswith(prefix):
                    sentence = sentence[len(prefix):]
                    sentence = sentence[0].upper() + sentence[1:]
                    break

            for end_char in [".", "!", "?"]:
                idx = sentence.find(end_char)
                if 0 < idx < 60:
                    sentence = sentence[:idx]
                    break

            if len(sentence) > 60:
                sentence = sentence[:57] + "..."
            return sentence
    return None
