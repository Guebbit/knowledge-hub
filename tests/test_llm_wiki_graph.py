"""Tests for parsing graphify's graph.json and expanding the changed set.

`load_graph` is written defensively because graphify's node and edge key names
have changed across releases; these pin the shapes it is expected to survive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo import llm_wiki
from shared import config


def _write_graph(repo: str, payload: dict) -> None:
    graph = Path(repo) / config.GRAPHIFY_OUT / "graph.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text(json.dumps(payload), encoding="utf-8")


class TestLoadGraph:
    def test_missing_graph_returns_empty(self, repo):
        assert llm_wiki.load_graph(repo) == (set(), {})

    def test_corrupt_graph_returns_empty_instead_of_raising(self, repo):
        graph = Path(repo) / config.GRAPHIFY_OUT / "graph.json"
        graph.parent.mkdir(parents=True, exist_ok=True)
        graph.write_text("{not json", encoding="utf-8")
        assert llm_wiki.load_graph(repo) == (set(), {})

    def test_symbol_level_nodes_resolve_to_source_files(self, repo):
        """graphify 0.9.x ids are mangled slugs; source_file is the real path."""
        _write_graph(repo, {
            "nodes": [
                {"id": "auth_login", "source_file": "src/auth/login.ts"},
                {"id": "db_query", "source_file": "src/db.ts"},
            ],
            "edges": [{"source": "auth_login", "target": "db_query"}],
        })
        files, adjacency = llm_wiki.load_graph(repo)
        assert files == {"src/auth/login.ts", "src/db.ts"}
        assert adjacency["src/auth/login.ts"] == {"src/db.ts"}

    @pytest.mark.parametrize("keys", [("source", "target"), ("from", "to"), ("src", "dst")])
    def test_edge_key_variants(self, repo, keys):
        src_key, dst_key = keys
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            "edges": [{src_key: "a", dst_key: "b"}],
        })
        _, adjacency = llm_wiki.load_graph(repo)
        assert adjacency["a.ts"] == {"b.ts"}

    @pytest.mark.parametrize("container", ["edges", "links", "relations"])
    def test_edge_container_variants(self, repo, container):
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            container: [{"source": "a", "target": "b"}],
        })
        _, adjacency = llm_wiki.load_graph(repo)
        assert adjacency["a.ts"] == {"b.ts"}

    def test_self_edges_are_dropped(self, repo):
        """Symbol-level graphs produce many intra-file edges; they add nothing."""
        _write_graph(repo, {
            "nodes": [{"id": "a1", "source_file": "a.ts"}, {"id": "a2", "source_file": "a.ts"}],
            "edges": [{"source": "a1", "target": "a2"}],
        })
        _, adjacency = llm_wiki.load_graph(repo)
        assert adjacency.get("a.ts", set()) == set()

    def test_leading_dot_slash_is_normalised(self, repo):
        _write_graph(repo, {"nodes": [{"id": "a", "source_file": "./src/a.ts"}]})
        files, _ = llm_wiki.load_graph(repo)
        assert files == {"src/a.ts"}

    def test_adjacency_is_undirected(self, repo):
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            "edges": [{"source": "a", "target": "b"}],
        })
        _, adjacency = llm_wiki.load_graph(repo)
        assert adjacency["b.ts"] == {"a.ts"}


class TestExpandNeighbors:
    ADJACENCY = {"a": {"b"}, "b": {"a", "c"}, "c": {"b", "d"}, "d": {"c"}}

    def test_zero_hops_returns_the_seeds(self):
        assert llm_wiki.expand_neighbors({"a"}, self.ADJACENCY, hops=0) == {"a"}

    def test_one_hop(self):
        assert llm_wiki.expand_neighbors({"a"}, self.ADJACENCY, hops=1) == {"a", "b"}

    def test_two_hops_is_the_default_reach(self):
        assert llm_wiki.expand_neighbors({"a"}, self.ADJACENCY) == {"a", "b", "c"}

    def test_stops_early_when_the_component_is_exhausted(self):
        assert llm_wiki.expand_neighbors({"a"}, {"a": set()}, hops=5) == {"a"}

    def test_unknown_seed_survives(self):
        assert llm_wiki.expand_neighbors({"ghost"}, self.ADJACENCY) == {"ghost"}


class TestPagePathMapping:
    """The per-file tier mirrors the source tree instead of flattening it."""

    def test_page_path_is_the_source_path_plus_md(self):
        assert llm_wiki.page_path_for("scripts/repo/wiki.py") == "scripts/repo/wiki.py.md"

    def test_mapping_is_invertible(self):
        for rel in ("a.ts", "src/a.ts", "src/deep/nest/a.ts", "a/b.c.d.py"):
            assert llm_wiki.page_path_for(rel).removesuffix(".md") == rel

    def test_paths_that_collided_under_the_flat_scheme_stay_distinct(self):
        """`_`-flattening mapped all three of these onto scripts_repo_wiki_py.md."""
        collided = ("scripts/repo/wiki.py", "scripts/repo_wiki.py", "scripts/repo/wiki_py")
        assert len({llm_wiki.page_path_for(p) for p in collided}) == len(collided)


class TestEmptyFilesAreNotDocumented:
    """An empty file has nothing to describe, but the model will describe it
    anyway: the 2026-09-13 run spent an LLM call producing 877 bytes about a
    zero-byte __init__.py, and the resulting page — matching on boilerplate
    words like page/file/wiki/repo — then outranked the module that held the
    actual answer.
    """

    def test_zero_byte_file_is_skipped(self, tmp_path):
        (tmp_path / "__init__.py").write_bytes(b"")

        assert not llm_wiki.is_documentable(tmp_path, "__init__.py")

    def test_whitespace_only_file_is_skipped(self, tmp_path):
        (tmp_path / "blank.py").write_text("\n\n   \n\t\n")

        assert not llm_wiki.is_documentable(tmp_path, "blank.py")

    def test_a_single_line_of_content_is_enough(self, tmp_path):
        """Deliberately not a size floor: small files can still be load-bearing."""
        (tmp_path / "constants.py").write_text("TIMEOUT = 30\n")

        assert llm_wiki.is_documentable(tmp_path, "constants.py")

    def test_long_file_starting_with_blank_lines_is_kept(self, tmp_path):
        """The emptiness check reads a 4 KB head; content after it still counts."""
        (tmp_path / "padded.py").write_text("\n" * 5000 + "VALUE = 1\n")

        assert llm_wiki.is_documentable(tmp_path, "padded.py")

    def test_binary_files_are_still_rejected(self, tmp_path):
        (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02")

        assert not llm_wiki.is_documentable(tmp_path, "blob.bin")


class TestProseIsNotSummarized:
    """This tier turns code into prose. Pointed at prose it produced a paraphrase
    longer than its input (docs/ollama.md: 2,208 -> 2,365 bytes) that then
    displaced the original from retrieval, because generated pages were the only
    route into the semantic index. Prose files stay documented — index.py indexes
    them directly — so they must remain candidates while getting no page.
    """

    def test_markdown_and_friends_are_prose(self):
        assert llm_wiki.is_prose("README.md")
        assert llm_wiki.is_prose("docs/GUIDE.MD"), "suffix match is case-insensitive"
        assert llm_wiki.is_prose("notes.txt")
        assert llm_wiki.is_prose("docs/api.rst")

    def test_code_is_not_prose(self):
        assert not llm_wiki.is_prose("scripts/repo.py")
        assert not llm_wiki.is_prose("docker-compose.yml")
        assert not llm_wiki.is_prose("src/markdown.ts"), "'markdown' in the name is not a suffix"

    def test_prose_stays_documentable(self, repo):
        """It must stay in candidates: the module tier counts it and index.py indexes it."""
        (Path(repo) / "README.md").write_text("# Title\n\nreal content\n")

        assert llm_wiki.is_documentable(Path(repo), "README.md")

    def test_read_pages_returns_the_source_for_prose(self, repo):
        (Path(repo) / "README.md").write_text("# Title\n\nthe author's own words\n")

        pages = llm_wiki.read_pages(repo, ["README.md"])

        assert "the author's own words" in pages["README.md"]

    def test_read_pages_still_reads_generated_pages_for_code(self, repo):
        page = llm_wiki.llm_wiki_dir(repo) / "src" / "a.py.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# src/a.py\n\ngenerated summary\n")

        pages = llm_wiki.read_pages(repo, ["src/a.py"])

        assert "generated summary" in pages["src/a.py"]
