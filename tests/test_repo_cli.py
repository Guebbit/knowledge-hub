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
