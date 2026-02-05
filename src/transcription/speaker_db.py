"""Speaker database for voice fingerprint storage and matching."""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class SpeakerDatabase:
    """
    Stores speaker voice embeddings and names for auto-identification.

    Voice embeddings are averaged over multiple samples to improve matching.
    """

    DEFAULT_DB_PATH = Path.home() / ".meeting-recorder" / "speakers.json"
    SIMILARITY_THRESHOLD = 0.75  # Cosine similarity threshold for matching

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.speakers: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load speaker database from disk."""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.speakers = data.get('speakers', {})
            except (json.JSONDecodeError, IOError):
                self.speakers = {}

    def _save(self):
        """Save speaker database to disk."""
        data = {
            'version': 1,
            'updated': datetime.now().isoformat(),
            'speakers': self.speakers
        }
        with open(self.db_path, 'w') as f:
            json.dump(data, f, indent=2)

    def add_speaker(
        self,
        name: str,
        embedding: List[float],
        merge: bool = True
    ) -> None:
        """
        Add or update a speaker's voice embedding.

        Args:
            name: Speaker's name
            embedding: Voice embedding vector
            merge: If True, average with existing embedding
        """
        name_lower = name.lower().strip()

        if merge and name_lower in self.speakers:
            # Average embeddings for better matching
            existing = np.array(self.speakers[name_lower]['embedding'])
            new = np.array(embedding)
            count = self.speakers[name_lower].get('sample_count', 1)

            # Weighted average
            averaged = (existing * count + new) / (count + 1)
            self.speakers[name_lower]['embedding'] = averaged.tolist()
            self.speakers[name_lower]['sample_count'] = count + 1
            self.speakers[name_lower]['updated'] = datetime.now().isoformat()
        else:
            self.speakers[name_lower] = {
                'name': name,  # Preserve original casing
                'embedding': embedding if isinstance(embedding, list) else embedding.tolist(),
                'sample_count': 1,
                'created': datetime.now().isoformat(),
                'updated': datetime.now().isoformat()
            }

        self._save()

    def find_speaker(
        self,
        embedding: List[float],
        threshold: Optional[float] = None
    ) -> Tuple[Optional[str], float]:
        """
        Find the closest matching speaker for an embedding.

        Args:
            embedding: Voice embedding to match
            threshold: Minimum similarity (default: SIMILARITY_THRESHOLD)

        Returns:
            Tuple of (speaker_name or None, similarity_score)
        """
        if not self.speakers:
            return None, 0.0

        threshold = threshold or self.SIMILARITY_THRESHOLD
        query = np.array(embedding)
        query_norm = query / (np.linalg.norm(query) + 1e-8)

        best_match = None
        best_score = 0.0

        for name_lower, data in self.speakers.items():
            stored = np.array(data['embedding'])
            stored_norm = stored / (np.linalg.norm(stored) + 1e-8)

            # Cosine similarity
            similarity = float(np.dot(query_norm, stored_norm))

            if similarity > best_score:
                best_score = similarity
                best_match = data['name']

        if best_score >= threshold:
            return best_match, best_score
        return None, best_score

    def list_speakers(self) -> List[dict]:
        """List all known speakers."""
        return [
            {
                'name': data['name'],
                'sample_count': data.get('sample_count', 1),
                'updated': data.get('updated', 'unknown')
            }
            for data in self.speakers.values()
        ]

    def remove_speaker(self, name: str) -> bool:
        """Remove a speaker from the database."""
        name_lower = name.lower().strip()
        if name_lower in self.speakers:
            del self.speakers[name_lower]
            self._save()
            return True
        return False

    def rename_speaker(self, old_name: str, new_name: str) -> bool:
        """Rename a speaker while keeping their embedding."""
        old_lower = old_name.lower().strip()
        new_lower = new_name.lower().strip()

        if old_lower not in self.speakers:
            return False

        data = self.speakers.pop(old_lower)
        data['name'] = new_name
        data['updated'] = datetime.now().isoformat()
        self.speakers[new_lower] = data
        self._save()
        return True

    def get_embedding_dim(self) -> Optional[int]:
        """Get the dimension of stored embeddings."""
        if self.speakers:
            first = next(iter(self.speakers.values()))
            return len(first['embedding'])
        return None
