"""
guardian/provenance.py — what the worker has seen in this session.

1. Where the worker could have learned each Drive ID.

The question the Guardian asks is not "is this file on a list?" but
"how did the worker find out about this file?":

  task     — the ID appears in the user's task text            (trusted)
  listing  — the ID was returned by an approved folder listing (trusted)
  created  — the worker created this file with an approved write (trusted)
  content  — the ID only appeared inside a document's content  (untrusted:
             this is exactly how a prompt injection points the worker
             somewhere it shouldn't go)

Trust is inherited: files listed inside a folder that was itself only found in
document content stay untrusted, so a human approving one listing doesn't turn
the whole folder's contents into trusted IDs.

An ID with no sighting at all was made up by the worker and is always blocked.
An ID seen through several sources keeps its most trusted one.

2. Which files the worker has read (an overwrite needs a prior read).

3. Taint: whether the session has been exposed to untrusted or sensitive
   content. Once it has, every later write is HIGH risk (the "Rule of Two":
   untrusted content + private data + a way to change things must not all be
   available without a human). Taint is never cleared within a session.
   Session.record() decides when to taint; this module only stores it.
"""

import re
from dataclasses import dataclass

# An ID inside a Drive / Docs URL: .../d/<id>/..., .../folders/<id>, ?id=<id>.
_DRIVE_URL_ID_RE = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{10,})")
# A bare token that looks like a Drive ID: 25+ characters of [A-Za-z0-9_-].
_BARE_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{25,}(?![A-Za-z0-9_-])")

TRUSTED_SOURCES = {"task", "listing", "created"}


def extract_ids(text: str) -> set[str]:
    """Drive IDs mentioned in text.

    IDs in Drive URLs always count. A bare token must also contain a digit and a
    letter: real Drive IDs do, while ordinary URL slugs and long hyphenated words
    ("getting-started-with-invoices") don't, and would otherwise taint the session.
    """
    text = text or ""
    ids = set(_DRIVE_URL_ID_RE.findall(text))
    ids |= {t for t in _BARE_ID_RE.findall(text)
            if any(c.isdigit() for c in t) and any(c.isalpha() for c in t)}
    return ids


@dataclass(frozen=True)
class Sighting:
    source: str                     # "task" | "listing" | "created" | "content"
    via: str | None = None          # folder ID for listings/created, file ID for content
    inherited_untrusted: bool = False   # inside a folder that was only found in content

    @property
    def trusted(self) -> bool:
        return self.source in TRUSTED_SOURCES and not self.inherited_untrusted

    def describe(self) -> str:
        text = self.source if self.via is None else f"{self.source} of {self.via}"
        return text + (" (a folder only found in document content)" if self.inherited_untrusted else "")


class ProvenanceTracker:
    def __init__(self, task: str):
        self._sightings: dict[str, list[Sighting]] = {}
        self.read_ids: set[str] = set()
        self.taint: list[str] = []      # why the session is tainted; empty = clean
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

    def mark_tainted(self, reason: str):
        if reason not in self.taint:
            self.taint.append(reason)

    def ingest(self, resource_id: str, result: dict) -> set[str]:
        """Record what an executed tool call on resource_id revealed, from the result's shape:

          {"files": [...]}   a listing: each child is now known
          {"content": "..."} a read: the file counts as read; IDs inside it are untrusted
          {"created": True}  a new file the worker made

        Returns the IDs found inside content (empty if none), so the caller can taint.
        """
        parent = self.best(resource_id)
        inherited = parent is not None and not parent.trusted
        for child in result.get("files", []):
            self.add(child["id"], Sighting("listing", via=resource_id, inherited_untrusted=inherited))
        linked: set[str] = set()
        if "content" in result:
            self.read_ids.add(resource_id)
            linked = extract_ids(result["content"]) - {resource_id}
            for found in linked:
                self.add(found, Sighting("content", via=resource_id))
        if result.get("created"):
            self.add(result["id"], Sighting("created", via=resource_id, inherited_untrusted=inherited))
        return linked
