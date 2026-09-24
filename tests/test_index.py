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


class TestTokenizeStopWordsAndStemming:
    """Q1: question-shaped queries missed the obvious answer. No stop-word list
    meant "how"/"do"/"i"/"does" scored; no real stemmer meant "run" never
    matched "runs"/"running".
    """

    def test_stop_words_are_dropped(self):
        tokens = index._tokenize("How do I run the tests?")
        assert "how" not in tokens
        assert "do" not in tokens
        assert "the" not in tokens
        assert "run" in tokens
        assert "test" in tokens

    def test_run_runs_running_share_a_stem(self):
        assert index._tokenize("run") == index._tokenize("runs") == index._tokenize("running")

    def test_test_and_testing_share_a_stem(self):
        assert index._tokenize("test") == index._tokenize("testing")

    def test_short_words_are_not_over_stemmed(self):
        assert index._tokenize("gas") == ["gas"]
        assert index._tokenize("css") == ["css"]

    def test_plural_of_a_regular_noun_still_stems(self):
        assert index._tokenize("modules") == index._tokenize("module")


class TestTitleTokensSource:
    """Q1: a document *named* after its topic must outrank pages that merely
    cite it — strategic-ddd.md should win "strategic DDD" over five pages
    that mention the filename once.
    """

    def test_path_words_and_first_heading_are_combined(self):
        title = index._title_tokens_source(
            "docs/theory/strategic-ddd.md", "# Strategic DDD\n\nBoundaries between contexts.\n"
        )
        assert "strategic" in title
        assert "ddd" in title.lower()

    def test_no_heading_still_yields_path_words(self):
        title = index._title_tokens_source("src/app.ts", "just some code comments")
        assert "app" in title

    def test_title_weight_repeats_the_title_tokens(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "EXECUTION.md", "Run the suite with `make test`.\n")

        chunks = index._build_chunk_records(
            Path(repo), artifact_files=[out / "EXECUTION.md"], prose_files=[], runtime_metadata={}
        )

        assert chunks[0]["title"]  # path words present, even with no heading


def _build_and_query(repo_path: str, query: str, top_k: int = 5) -> list[dict[str, object]]:
    out = Path(repo_path) / ".2brain"
    out.mkdir(exist_ok=True)
    if not (out / "EXECUTION.md").exists():
        _touch(out / "EXECUTION.md", "placeholder")
    _touch(out / "REPO_MEMORY.md", "no entries")
    index.build_index(repo_path, runtime_metadata={})
    return index.semantic_query(repo_path, text=query, top_k=top_k)


class TestQueryFindsTheObviousAnswer:
    """Regression fixtures mirroring ANALYSIS.md's Q1 cases: a small synthetic
    corpus where a question-shaped query must surface the right source in the
    top 3, not be crowded out by pages that merely mention the topic.
    """

    def test_execution_page_beats_individual_test_file_pages(self, repo):
        out = Path(repo) / ".2brain"
        _touch(
            out / "EXECUTION.md",
            "## Quick Commands\n\nRun the whole suite with `npm run test`. "
            "This is the command to run tests locally before pushing.\n",
        )
        for i in range(5):
            _touch(
                out / "llm-wiki" / f"tests/case{i}.test.ts.md",
                f"---\nsource: tests/case{i}.test.ts\nsha256: {'a' * 64}\nmodel: x\n---\n\n"
                f"## Purpose\nChecks behavior number {i} of the widget subsystem in isolation.\n",
            )

        results = _build_and_query(repo, "how do I run tests?", top_k=3)

        sources = [r["source"] for r in results]
        assert ".2brain/EXECUTION.md" in sources

    def test_named_doc_beats_pages_that_only_cite_it(self, repo):
        root = Path(repo)
        _touch(
            root / "docs" / "theory" / "strategic-ddd.md",
            "# Strategic DDD\n\nStrategic domain-driven design defines the module boundaries "
            "between bounded contexts in this codebase.\n",
        )
        graph_files = ["docs/theory/strategic-ddd.md"]
        out = root / ".2brain"
        for i in range(5):
            page = f"src/modules/m{i}/index.ts"
            graph_files.append(page)
            _touch(
                out / "llm-wiki" / f"{page}.md",
                f"---\nsource: {page}\nsha256: {'a' * 64}\nmodel: x\n---\n\n"
                "## Purpose\nImplements this module, following the strategic-ddd.md approach.\n",
            )
        _write_graph(root, graph_files)

        results = _build_and_query(repo, "strategic DDD module boundaries", top_k=3)

        sources = [r["source"] for r in results]
        assert "docs/theory/strategic-ddd.md" in sources


class TestExpansionRequiresAConfidentSeed:
    """Q1: query expansion seeded from a wrong #1 reinforces the mistake. A #1
    barely ahead of #2 must not seed expansion at all.
    """

    def test_close_scores_are_not_confident(self):
        scored = [{"base_score": 0.50}, {"base_score": 0.49}]
        assert index._confident_seed(scored) is False

    def test_a_clear_leader_is_confident(self):
        scored = [{"base_score": 0.60}, {"base_score": 0.40}]
        assert index._confident_seed(scored) is True

    def test_exactly_at_the_ratio_is_confident(self):
        scored = [{"base_score": 0.48}, {"base_score": 0.40}]  # 0.48 == 0.40 * 1.2
        assert index._confident_seed(scored) is True

    def test_a_single_result_is_always_confident(self):
        assert index._confident_seed([{"base_score": 0.1}]) is True

    def test_no_results_is_confident_by_default(self):
        assert index._confident_seed([]) is True

    def test_no_expansion_means_the_final_score_equals_the_base_score(self, repo):
        out = Path(repo) / ".2brain"
        _touch(out / "EXECUTION.md", "alpha beta gamma delta epsilon zeta eta theta\n")
        _touch(
            out / "llm-wiki" / "src" / "a.py.md",
            f"---\nsource: src/a.py\nsha256: {'a' * 64}\nmodel: x\n---\n\n"
            "alpha beta gamma delta epsilon zeta eta theta\n",
        )

        results = _build_and_query(repo, "alpha beta gamma delta", top_k=5)

        assert len(results) == 2
        for item in results:
            assert item["score"] == item["base_score"], "identical documents must tie, not seed expansion"
