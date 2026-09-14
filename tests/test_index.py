"""Corpus construction for the semantic index — which artifacts get indexed."""

from __future__ import annotations

import json
from pathlib import Path

from repo import index


def _touch(path: Path, text: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestArtifactFiles:
    """modules/ (the human-facing per-directory tier) must be excluded: it is
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
        _touch(out / "modules" / "src_ROOT.md")

        files = index._artifact_files(Path(repo))

        assert out / "modules" / "src_ROOT.md" not in files

    def test_top_level_reports_are_indexed_when_present(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "EXECUTION.md")
        _touch(out / "REPO_MEMORY.md")
        _touch(out / "REPO_CONTEXT.md")

        files = index._artifact_files(Path(repo))

        assert out / "EXECUTION.md" in files
        assert out / "REPO_MEMORY.md" in files
        assert out / "REPO_CONTEXT.md" in files

    def test_the_graph_report_is_not_in_the_corpus(self, repo):
        """It matches every query and answers none: each chunk is a list of
        community labels and truncated docstrings, not an explanation. It stays
        generated, committed and linked from REPO_CONTEXT.md — just not indexed.
        """
        out = Path(repo) / ".2brain"
        _touch(out / "graphify-out" / "GRAPH_REPORT.md")
        _touch(out / "EXECUTION.md")

        files = index._artifact_files(Path(repo))

        assert out / "EXECUTION.md" in files
        assert out / "graphify-out" / "GRAPH_REPORT.md" not in files

    def test_raw_graphify_dumps_and_caches_are_never_indexed(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "graphify-out" / "graph.json")
        _touch(out / "graphify-out" / "manifest.json")
        _touch(out / "modules" / ".modules-cache.json")
        _touch(out / "repo-index.json")
        _touch(out / ".2brain-state.json")

        files = index._artifact_files(Path(repo))

        assert files == []


class TestPerSourceCap:
    """One long artifact chunks into dozens of records. Uncapped, a single
    document can hold most of the result set and most of the query-expansion
    seed, which then re-injects its vocabulary into the query — GRAPH_REPORT.md
    (an index of every identifier in the repo) took both top slots this way.
    """

    def test_one_result_per_source(self):
        items = [{"source": "a.md", "n": i} for i in range(5)]

        kept = index._cap_per_source(items, limit=3)

        assert len(kept) == 1
        assert kept[0]["n"] == 0, "the best chunk must be the one kept"

    def test_distinct_sources_fill_the_limit(self):
        items = [{"source": f"{name}.md"} for name in ("a", "a", "b", "b", "c")]

        kept = index._cap_per_source(items, limit=3)

        assert [item["source"] for item in kept] == ["a.md", "b.md", "c.md"]

    def test_returns_fewer_than_limit_rather_than_padding(self):
        items = [{"source": "a.md"}, {"source": "b.md"}, {"source": "a.md"}]

        kept = index._cap_per_source(items, limit=10)

        assert [item["source"] for item in kept] == ["a.md", "b.md"]

    def test_source_of_reads_nested_records(self):
        """The expansion seed holds {chunk, base_score}, not bare chunks."""
        items = [{"chunk": {"source": s}} for s in ("a.md", "a.md", "b.md")]

        kept = index._cap_per_source(
            items,
            limit=5,
            source_of=lambda item: str(item["chunk"].get("source") or ""),
        )

        assert len(kept) == 2


def _write_graph(repo: Path, files: list[str]) -> None:
    graph = repo / ".2brain" / "graphify-out" / "graph.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text(json.dumps({"nodes": [{"id": f, "source_file": f} for f in files], "links": []}))


class TestProseSourcesAreIndexedDirectly:
    """Prose files get no generated page, so they reach the corpus as themselves:
    cheaper, more faithful than a paraphrase, and `2brain query` returns a path
    the caller can open instead of one they must translate back.
    """

    def test_in_scope_prose_is_collected(self, repo):
        root = Path(repo)
        _touch(root / "README.md", "# Title")
        _touch(root / "docs" / "guide.md", "# Guide")
        _touch(root / "src" / "app.py", "x = 1")
        _write_graph(root, ["README.md", "docs/guide.md", "src/app.py"])

        prose = index._source_prose_files(root)

        assert prose == [root / "README.md", root / "docs" / "guide.md"], "code is excluded"

    def test_the_scope_file_still_governs(self, repo):
        root = Path(repo)
        _touch(root / "README.md", "# Title")
        _touch(root / "docs" / "plans" / "roadmap.md", "# Roadmap")
        _touch(root / ".2brainignore", "[include]\n\n[exclude]\ndocs/plans/**\n")
        _write_graph(root, ["README.md", "docs/plans/roadmap.md"])

        prose = index._source_prose_files(root)

        assert prose == [root / "README.md"]

    def test_missing_graph_yields_no_prose_instead_of_failing(self, repo):
        """`2brain reindex` before any graph run must still index artifacts."""
        assert index._source_prose_files(Path(repo)) == []

    def test_prose_chunks_carry_the_real_source_path(self, repo):
        root = Path(repo)
        _touch(root / "README.md", "# Title\n\nthe author's own words\n")

        chunks = index._build_chunk_records(
            root,
            artifact_files=[],
            prose_files=[root / "README.md"],
            runtime_metadata={},
        )

        assert [c["source"] for c in chunks] == ["README.md"]
        assert {c["kind"] for c in chunks} == {"source"}
        assert "the author's own words" in chunks[0]["text"]


class TestStaleProsePagesAreNotDoubleIndexed:
    """The graph layer rebuilds the index before the wiki layer prunes pages, so
    a leftover summary of a prose file would otherwise be indexed alongside the
    document itself — the duplication the allowlist exists to prevent.
    """

    def test_leftover_prose_page_is_excluded(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "llm-wiki" / "docs" / "guide.md.md")
        _touch(out / "llm-wiki" / "src" / "a.py.md")

        files = index._artifact_files(Path(repo))

        assert out / "llm-wiki" / "src" / "a.py.md" in files
        assert out / "llm-wiki" / "docs" / "guide.md.md" not in files

    def test_the_overview_is_not_mistaken_for_a_prose_page(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "llm-wiki" / "OVERVIEW.md")

        assert out / "llm-wiki" / "OVERVIEW.md" in index._artifact_files(Path(repo))


class TestChunkingDoesNotStrandHeadings:
    """Markdown puts a blank line after every heading, so splitting on blank
    lines alone made each heading its own chunk. A four-token chunk matching two
    query terms then outscores a paragraph matching eight, because cosine
    similarity normalizes away the difference in substance: "how does the wiki
    cache decide to skip a page" was answered with "## What 2brain does".
    """

    def test_a_heading_joins_the_section_it_introduces(self):
        text = "## What 2brain does\n\n" + "It builds a searchable index of the repository. " * 4

        chunks = index._chunk_plain_text(text)

        assert len(chunks) == 1
        assert chunks[0].startswith("## What 2brain does")

    def test_a_trailing_scrap_joins_the_previous_chunk(self):
        text = "Body text that is comfortably long enough to stand on its own. " * 3 + "\n\n## Footer"

        chunks = index._chunk_plain_text(text)

        assert len(chunks) == 1
        assert chunks[0].endswith("## Footer")

    def test_substantial_paragraphs_still_split(self):
        para = "This paragraph is long enough to be a retrievable answer on its own. " * 3
        chunks = index._chunk_plain_text(f"{para}\n\n{para}")

        assert len(chunks) == 2

    def test_a_short_document_still_produces_one_chunk(self):
        """A file below the floor is not dropped — it has nowhere to merge into."""
        assert index._chunk_plain_text("# Tiny\n") == ["# Tiny"]


class TestWikiPageChunks:
    """An llm-wiki page names the file it documents in its frontmatter. The index
    returns that path, and never indexes the header itself.
    """

    def test_source_path_replaces_the_page_path(self, repo):
        out = Path(repo) / ".2brain"
        _touch(
            out / "llm-wiki" / "scripts" / "a.py.md",
            "---\nsource: scripts/a.py\nsha256: "
            + "f" * 64
            + "\nmodel: ollama:qwen3:8b\n---\n\nThis module parses the configuration file at startup.\n",
        )

        chunks = index._build_chunk_records(
            Path(repo),
            artifact_files=[out / "llm-wiki" / "scripts" / "a.py.md"],
            prose_files=[],
            runtime_metadata={},
        )

        assert [c["source"] for c in chunks] == ["scripts/a.py"]
        assert [c["kind"] for c in chunks] == ["wiki"]

    def test_frontmatter_never_reaches_the_corpus(self, repo):
        """"model" and "source" are words worth querying; in every page's header
        they would be present everywhere and discriminate nothing. The digest is
        a unique token per page and pure vocabulary growth."""
        out = Path(repo) / ".2brain"
        digest = "f" * 64
        _touch(
            out / "llm-wiki" / "scripts" / "a.py.md",
            f"---\nsource: scripts/a.py\nsha256: {digest}\nmodel: ollama:qwen3:8b\n---\n\nReal prose only.\n",
        )

        chunks = index._build_chunk_records(
            Path(repo),
            artifact_files=[out / "llm-wiki" / "scripts" / "a.py.md"],
            prose_files=[],
            runtime_metadata={},
        )
        text = "\n".join(c["text"] for c in chunks)

        assert digest not in text
        assert "sha256" not in text
        assert "generated_at" not in text
        assert "Real prose only." in text

    def test_headerless_artifacts_still_name_themselves(self, repo):
        """EXECUTION.md and arch/ pages carry no frontmatter and are their own source."""
        out = Path(repo) / ".2brain"
        _touch(out / "EXECUTION.md", "Run the suite with `make test`.\n")

        chunks = index._build_chunk_records(
            Path(repo), artifact_files=[out / "EXECUTION.md"], prose_files=[], runtime_metadata={}
        )

        assert [c["source"] for c in chunks] == [".2brain/EXECUTION.md"]
        assert [c["kind"] for c in chunks] == ["artifact"]
