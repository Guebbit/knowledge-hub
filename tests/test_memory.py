"""Repo memory: repo-memory.json must exist even with zero entries (S1)."""

from __future__ import annotations

import json
from pathlib import Path

from repo import memory


class TestWriteMemoryReportEnsuresTheJsonFile:
    def test_empty_memory_still_creates_repo_memory_json(self, repo):
        memory.write_memory_report(repo)

        store = Path(repo) / ".2brain" / "repo-memory.json"
        assert store.exists()
        assert json.loads(store.read_text())["entries"] == []

    def test_existing_entries_are_left_untouched(self, repo):
        memory.add_entry(
            repo, text="use pytest -q", kind="runbook", source="manual", head="abc123", index_revision="rev1"
        )
        store = Path(repo) / ".2brain" / "repo-memory.json"
        before = store.read_text()

        memory.write_memory_report(repo)

        assert store.read_text() == before
