"""Corpus construction for the semantic index — which artifacts get indexed."""

from __future__ import annotations

from pathlib import Path

from repo import index


def _touch(path: Path, text: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestArtifactFiles:
    """wiki/ (the human-facing per-directory tier) must be excluded: it is
    written from llm-wiki/'s pages, so indexing both means the same facts are
    indexed twice, which depresses IDF on the terms that should discriminate.
    """

    def test_llm_wiki_and_arch_are_indexed(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "llm-wiki" / "src" / "a.py.md")
        _touch(out / "arch" / "overview.md")

        files = index._artifact_files(Path(repo))

        assert out / "llm-wiki" / "src" / "a.py.md" in files
        assert out / "arch" / "overview.md" in files

    def test_the_directory_tier_is_excluded(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "llm-wiki" / "src" / "a.py.md")
        _touch(out / "wiki" / "src_ROOT.md")

        files = index._artifact_files(Path(repo))

        assert out / "wiki" / "src_ROOT.md" not in files

    def test_top_level_reports_are_indexed_when_present(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "EXECUTION.md")
        _touch(out / "REPO_MEMORY.md")
        _touch(out / "REPO_CONTEXT.md")
        _touch(out / "graphify-out" / "GRAPH_REPORT.md")

        files = index._artifact_files(Path(repo))

        assert out / "EXECUTION.md" in files
        assert out / "REPO_MEMORY.md" in files
        assert out / "REPO_CONTEXT.md" in files
        assert out / "graphify-out" / "GRAPH_REPORT.md" in files

    def test_raw_graphify_dumps_and_caches_are_never_indexed(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "graphify-out" / "graph.json")
        _touch(out / "graphify-out" / "manifest.json")
        _touch(out / "llm-wiki" / ".llm-wiki-cache.json")
        _touch(out / "repo-index.json")
        _touch(out / ".2brain-state.json")

        files = index._artifact_files(Path(repo))

        assert files == []
