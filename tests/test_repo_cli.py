"""scripts/repo.py: graph-size gating for the optional cluster-only/GRAPH_REPORT.md pass.

Loaded via importlib rather than `import repo` because the top-level CLI
script shares its name with the `repo/` package (scripts/repo.py vs
scripts/repo/__init__.py) — plain `import repo` resolves to the package.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_PY = Path(__file__).resolve().parent.parent / "scripts" / "repo.py"


@pytest.fixture(scope="module")
def repo_cli():
    spec = importlib.util.spec_from_file_location("repo_cli_under_test", _REPO_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_graph(path: Path, node_count: int) -> None:
    graphify_out = path / ".2brain" / "graphify-out"
    graphify_out.mkdir(parents=True, exist_ok=True)
    (graphify_out / "graph.json").write_text(json.dumps({"nodes": [{}] * node_count, "links": []}))


class TestGraphNodeCount:
    def test_reads_node_count_from_graph_json(self, repo_cli, tmp_path):
        _write_graph(tmp_path, 724)
        assert repo_cli._graph_node_count(str(tmp_path)) == 724

    def test_missing_graph_json_is_zero(self, repo_cli, tmp_path):
        assert repo_cli._graph_node_count(str(tmp_path)) == 0

    def test_invalid_json_is_zero(self, repo_cli, tmp_path):
        graphify_out = tmp_path / ".2brain" / "graphify-out"
        graphify_out.mkdir(parents=True)
        (graphify_out / "graph.json").write_text("not json")
        assert repo_cli._graph_node_count(str(tmp_path)) == 0


class TestGraphReportIsOptional:
    def test_graph_report_is_not_a_required_pipeline_artifact(self, repo_cli):
        assert all("GRAPH_REPORT" not in str(p) for p in repo_cli._REQUIRED_PIPELINE_ARTIFACTS)

    def test_execution_md_is_still_required(self, repo_cli):
        assert any(str(p).endswith("EXECUTION.md") for p in repo_cli._REQUIRED_PIPELINE_ARTIFACTS)


class TestStateLayerRefresh:
    """The graph baseline may only advance when graphify runs, or --check reports
    a stale graph as fresh. But the wiki and arch layers rebuild the *index*, and
    leaving the graph layer's record in place made .2brain-state.json describe an
    index that no longer existed (72 chunks recorded against 585 on disk).
    """

    @pytest.fixture
    def state_repo(self, repo_cli, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _: True)
        state = tmp_path / ".2brain" / ".2brain-state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({
            "generated_at": "2026-09-13T14:11:42+00:00",
            "head": "0bafcf31",
            "threshold": 5,
            "layers": {"index": {"chunk_count": 72}},
        }))
        return state

    def test_head_stays_pinned_while_layers_refresh(self, repo_cli, tmp_path, state_repo):
        repo_cli._refresh_state_layers(str(tmp_path), pipeline={"index": {"chunk_count": 585}})

        written = json.loads(state_repo.read_text())
        assert written["head"] == "0bafcf31", "the graph baseline must not move"
        assert written["layers"]["index"]["chunk_count"] == 585

    def test_missing_state_is_not_invented(self, repo_cli, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _: True)

        repo_cli._refresh_state_layers(str(tmp_path), pipeline={"index": {}})

        assert not (tmp_path / ".2brain" / ".2brain-state.json").exists(), (
            "writing a baseline here would silently move it to HEAD"
        )

    def test_corrupt_state_is_left_alone(self, repo_cli, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _: True)
        state = tmp_path / ".2brain" / ".2brain-state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("{not json")

        repo_cli._refresh_state_layers(str(tmp_path), pipeline={"index": {}})

        assert state.read_text() == "{not json"
