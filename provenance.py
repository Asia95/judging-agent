"""
provenance.py — tracks where the worker could have learned each Drive ID.

The question the Guardian asks is not "is this file on a list?" but
"how did the worker find out about this file?":

  task     — the ID appears in the user's task text            (trusted)
  listing  — the ID was returned by an approved folder listing (trusted)
  content  — the ID only appeared inside a document's content  (untrusted:
             this is exactly how a prompt injection points the worker
             somewhere it shouldn't go)

An ID with no sighting at all was made up by the worker and is always blocked.
An ID seen through several sources keeps its most trusted one.
"""

import re
from dataclasses import dataclass

# Drive IDs are long runs of [A-Za-z0-9_-]. This also matches the ID part of
# Drive URLs (.../d/<id>/..., .../folders/<id>, ?id=<id>).
_DRIVE_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{25,}(?![A-Za-z0-9_-])")

TRUSTED_SOURCES = {"task", "listing"}


def extract_ids(text: str) -> set[str]:
    return set(_DRIVE_ID_RE.findall(text or ""))


@dataclass(frozen=True)
class Sighting:
    source: str             # "task" | "listing" | "content"
    via: str | None = None  # folder ID for listings, file ID for content

    @property
    def trusted(self) -> bool:
        return self.source in TRUSTED_SOURCES

    def describe(self) -> str:
        return self.source if self.via is None else f"{self.source} of {self.via}"


class ProvenanceTracker:
    def __init__(self, task: str):
        self._sightings: dict[str, list[Sighting]] = {}
        for resource_id in extract_ids(task):
            self.add(resource_id, Sighting("task"))

    def add(self, resource_id: str, sighting: Sighting):
        seen = self._sightings.setdefault(resource_id, [])
        if sighting not in seen:
            seen.append(sighting)

    def best(self, resource_id: str) -> Sighting | None:
        """Most trusted sighting of an ID, or None if the ID was never seen."""
        seen = self._sightings.get(resource_id, [])
        trusted = [s for s in seen if s.trusted]
        return (trusted or seen or [None])[0]

    def ingest(self, action: str, args: dict, result: dict):
        """Record IDs revealed by an executed tool call."""
        if action == "list":
            for f in result.get("files", []):
                self.add(f["id"], Sighting("listing", via=args["folder_id"]))
        elif action == "read":
            for resource_id in extract_ids(result.get("content", "")) - {args["file_id"]}:
                self.add(resource_id, Sighting("content", via=args["file_id"]))
