from __future__ import annotations

"""
Durable repository memory storage for 2repo.

Entries are stored in graphify-out/repo-memory.json and mirrored into
graphify-out/REPO_MEMORY.md for human-readable inspection.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_MEMORY_SUBPATH = Path("graphify-out/repo-memory.json")
_MEMORY_REPORT_SUBPATH = Path("graphify-out/REPO_MEMORY.md")


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _memory_file(repo: Path) -> Path:
    """Return path to the JSON memory store for a repository."""
    return repo / _MEMORY_SUBPATH


def _memory_report_file(repo: Path) -> Path:
    """Return path to the markdown memory report for a repository."""
    return repo / _MEMORY_REPORT_SUBPATH


def _normalize_text(text: str) -> str:
    """Collapse whitespace and reject empty memory text."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        raise ValueError("repository memory entry text cannot be empty or contain only whitespace")
    return normalized


def load_entries(repo_path: str) -> list[dict[str, str]]:
    """Load and validate memory entries from disk, returning normalized records."""
    repo = Path(repo_path)
    path = _memory_file(repo)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid memory file: {path}") from exc
    entries = data.get("entries", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        raise ValueError(f"invalid memory entries in {path}")

    normalized: list[dict[str, str]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text")
        kind = raw.get("kind")
        source = raw.get("source")
        entry_id = raw.get("id")
        created_at = raw.get("created_at")
        if not all(isinstance(value, str) for value in [text, kind, source, entry_id, created_at]):
            continue
        normalized.append(
            {
                "id": entry_id,
                "text": _normalize_text(text),
                "kind": kind,
                "source": source,
                "created_at": created_at,
                "head": str(raw.get("head") or ""),
                "index_revision": str(raw.get("index_revision") or ""),
            }
        )
    return normalized


def _write_entries(repo: Path, entries: list[dict[str, str]]) -> None:
    """Persist memory entries to graphify-out/repo-memory.json."""
    path = _memory_file(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": _now_iso(),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def add_entry(
    repo_path: str,
    *,
    text: str,
    kind: str,
    source: str,
    head: str,
    index_revision: str,
) -> dict[str, str]:
    """Insert/update one memory entry, deduplicating by (kind, case-insensitive text)."""
    repo = Path(repo_path)
    normalized_text = _normalize_text(text)
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"fact", "decision", "runbook"}:
        raise ValueError(
            f"memory kind must be one of: fact, decision, runbook (got '{normalized_kind}')"
        )

    entries = load_entries(repo_path)
    lookup = {(entry["kind"], entry["text"].casefold()): entry for entry in entries}
    duplicate = lookup.get((normalized_kind, normalized_text.casefold()))
    if duplicate:
        duplicate["source"] = source.strip() or "manual"
        duplicate["head"] = head
        duplicate["index_revision"] = index_revision
        _write_entries(repo, entries)
        return duplicate

    digest = hashlib.sha256(f"{normalized_kind}:{normalized_text}".encode("utf-8")).hexdigest()
    entry = {
        "id": digest[:16],
        "text": normalized_text,
        "kind": normalized_kind,
        "source": source.strip() or "manual",
        "created_at": _now_iso(),
        "head": head,
        "index_revision": index_revision,
    }
    entries.append(entry)
    _write_entries(repo, entries)
    return entry


def sync_entries(repo_path: str, *, head: str, index_revision: str) -> int:
    """Update entry metadata to the latest git/index pointers; return updated count."""
    repo = Path(repo_path)
    entries = load_entries(repo_path)
    updated = 0
    for entry in entries:
        if entry.get("head") != head or entry.get("index_revision") != index_revision:
            entry["head"] = head
            entry["index_revision"] = index_revision
            updated += 1
    if updated:
        _write_entries(repo, entries)
    return updated


def write_memory_report(repo_path: str) -> Path:
    """Render a markdown report of all durable repository memory entries."""
    repo = Path(repo_path)
    report_path = _memory_report_file(repo)
    entries = load_entries(repo_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Repo Memory")
    lines.append("")
    lines.append("_Durable memory entries scoped to this repository._")
    lines.append("")

    if not entries:
        lines.append("- No memory entries recorded yet.")
    else:
        for entry in entries:
            lines.append(f"- **[{entry['kind']}]** {entry['text']}")
            lines.append(f"  - id: `{entry['id']}`")
            lines.append(f"  - source: `{entry['source']}`")
            lines.append(f"  - created_at: `{entry['created_at']}`")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def memory_digest(repo_path: str) -> str:
    """Compute a stable digest of current memory entries for index revisioning."""
    entries = load_entries(repo_path)
    payload = "\n".join(f"{e['id']}|{e['kind']}|{e['text']}" for e in entries)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
