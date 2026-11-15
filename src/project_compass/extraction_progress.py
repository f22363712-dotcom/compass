"""Acknowledged source ranges, separate from semantic facts and acceptance."""
from hashlib import sha256
import json
from pathlib import Path
import re

from .evidence_filters import atomic_write_text, path_lock


def source_key(event) -> str:
    identity = [event.id, event.kind, event.session_id, event.author, event.observed_at.isoformat(),
                event.metadata.get('source_ref'), event.metadata.get('role'), event.metadata.get('member_id'), event.content]
    return sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


class ExtractionProgress:
    def __init__(self, cache_dir, namespace='extractive-v2:gpt-6.1-sol:medium'):
        self.path = Path(cache_dir) / 'coverage-v1.json'
        self.namespace = namespace

    def load(self) -> dict[str, int]:
        with path_lock(self.path):
            if not self.path.exists():
                return {}
            value = json.loads(self.path.read_text(encoding='utf8'))
            if not isinstance(value, dict) or value.get('version') != 1 or value.get('namespace') != self.namespace or not isinstance(value.get('cursors'), dict):
                raise ValueError('invalid extraction coverage; preserve it and select a separate cache directory')
            cursors = value['cursors']
            if any(not re.fullmatch('[0-9a-f]{64}', key) or type(end) is not int or end < 0 for key, end in cursors.items()):
                raise ValueError('invalid extraction coverage cursor')
            return cursors

    def acknowledge(self, updates: dict[str, int]) -> dict[str, int]:
        with path_lock(self.path):
            current = self.load()
            merged = {**current}
            for key, end in updates.items():
                merged[key] = max(end, merged.get(key, 0))
            if merged != current:
                atomic_write_text(
                    self.path,
                    json.dumps({'version': 1, 'namespace': self.namespace, 'cursors': merged}, sort_keys=True),
                )
            return merged
