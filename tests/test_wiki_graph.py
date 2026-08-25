"""Tests for parsing graphify's graph.json and expanding the changed set.

`load_graph` is written defensively because graphify's node and edge key names
have changed across releases; these pin the shapes it is expected to survive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo import wiki
from shared import config


def _write_graph(repo: str, payload: dict) -> None:
    graph = Path(repo) / config.GRAPHIFY_OUT / "graph.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text(json.dumps(payload), encoding="utf-8")


class TestLoadGraph:
    def test_missing_graph_returns_empty(self, repo):
        assert wiki.load_graph(repo) == (set(), {})

    def test_corrupt_graph_returns_empty_instead_of_raising(self, repo):
        graph = Path(repo) / config.GRAPHIFY_OUT / "graph.json"
        graph.parent.mkdir(parents=True, exist_ok=True)
        graph.write_text("{not json", encoding="utf-8")
        assert wiki.load_graph(repo) == (set(), {})

    def test_symbol_level_nodes_resolve_to_source_files(self, repo):
        """graphify 0.9.x ids are mangled slugs; source_file is the real path."""
        _write_graph(repo, {
            "nodes": [
                {"id": "auth_login", "source_file": "src/auth/login.ts"},
                {"id": "db_query", "source_file": "src/db.ts"},
            ],
            "edges": [{"source": "auth_login", "target": "db_query"}],
        })
        files, adjacency = wiki.load_graph(repo)
        assert files == {"src/auth/login.ts", "src/db.ts"}
        assert adjacency["src/auth/login.ts"] == {"src/db.ts"}

    @pytest.mark.parametrize("keys", [("source", "target"), ("from", "to"), ("src", "dst")])
    def test_edge_key_variants(self, repo, keys):
        src_key, dst_key = keys
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            "edges": [{src_key: "a", dst_key: "b"}],
        })
        _, adjacency = wiki.load_graph(repo)
        assert adjacency["a.ts"] == {"b.ts"}

    @pytest.mark.parametrize("container", ["edges", "links", "relations"])
    def test_edge_container_variants(self, repo, container):
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            container: [{"source": "a", "target": "b"}],
        })
        _, adjacency = wiki.load_graph(repo)
        assert adjacency["a.ts"] == {"b.ts"}

    def test_self_edges_are_dropped(self, repo):
        """Symbol-level graphs produce many intra-file edges; they add nothing."""
        _write_graph(repo, {
            "nodes": [{"id": "a1", "source_file": "a.ts"}, {"id": "a2", "source_file": "a.ts"}],
            "edges": [{"source": "a1", "target": "a2"}],
        })
        _, adjacency = wiki.load_graph(repo)
        assert adjacency.get("a.ts", set()) == set()

    def test_leading_dot_slash_is_normalised(self, repo):
        _write_graph(repo, {"nodes": [{"id": "a", "source_file": "./src/a.ts"}]})
        files, _ = wiki.load_graph(repo)
        assert files == {"src/a.ts"}

    def test_adjacency_is_undirected(self, repo):
        _write_graph(repo, {
            "nodes": [{"id": "a", "source_file": "a.ts"}, {"id": "b", "source_file": "b.ts"}],
            "edges": [{"source": "a", "target": "b"}],
        })
        _, adjacency = wiki.load_graph(repo)
        assert adjacency["b.ts"] == {"a.ts"}


class TestExpandNeighbors:
    ADJACENCY = {"a": {"b"}, "b": {"a", "c"}, "c": {"b", "d"}, "d": {"c"}}

    def test_zero_hops_returns_the_seeds(self):
        assert wiki.expand_neighbors({"a"}, self.ADJACENCY, hops=0) == {"a"}

    def test_one_hop(self):
        assert wiki.expand_neighbors({"a"}, self.ADJACENCY, hops=1) == {"a", "b"}

    def test_two_hops_is_the_default_reach(self):
        assert wiki.expand_neighbors({"a"}, self.ADJACENCY) == {"a", "b", "c"}

    def test_stops_early_when_the_component_is_exhausted(self):
        assert wiki.expand_neighbors({"a"}, {"a": set()}, hops=5) == {"a"}

    def test_unknown_seed_survives(self):
        assert wiki.expand_neighbors({"ghost"}, self.ADJACENCY) == {"ghost"}
