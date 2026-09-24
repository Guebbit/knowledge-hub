"""scripts/repo.py: graph-size gating for the optional cluster-only/GRAPH_REPORT.md pass.

Loaded via importlib rather than `import repo` because the top-level CLI
script shares its name with the `repo/` package (scripts/repo.py vs
scripts/repo/__init__.py) — plain `import repo` resolves to the package.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def _git_commit(path: Path) -> str:
    """Init a git repo at `path` with one commit, returning its HEAD sha."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()

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
        repo_cli._refresh_state_layers(str(tmp_path), pipeline={"index": {"chunk_count": 585}}, head="0bafcf31")

        written = json.loads(state_repo.read_text())
        assert written["head"] == "0bafcf31", "the graph baseline must not move"
        assert written["layers"]["index"]["chunk_count"] == 585

    def test_empty_head_writes_nothing(self, repo_cli, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _: True)

        repo_cli._refresh_state_layers(str(tmp_path), pipeline={"index": {}}, head="")

        assert not (tmp_path / ".2brain" / ".2brain-state.json").exists(), (
            "writing a baseline here would silently move it to HEAD"
        )


class TestBaselineHead:
    """_baseline_head reads the pinned graph commit without _read_state()'s chatter.

    Callers (_wiki, _arch, _all) read it once and pass the same value to both
    _build_layers (stamping) and _refresh_state_layers (pinning) — see C1.
    """

    def test_missing_state_is_empty(self, repo_cli, tmp_path):
        assert repo_cli._baseline_head(str(tmp_path)) == ""

    def test_corrupt_state_is_empty(self, repo_cli, tmp_path):
        state = tmp_path / ".2brain" / ".2brain-state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("{not json")

        assert repo_cli._baseline_head(str(tmp_path)) == ""

    def test_reads_the_recorded_head(self, repo_cli, tmp_path):
        state = tmp_path / ".2brain" / ".2brain-state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"head": "ad8d8602"}))

        assert repo_cli._baseline_head(str(tmp_path)) == "ad8d8602"


class TestBuildLayersHeadIsExplicit:
    """C1: _build_layers no longer resolves HEAD itself — every artifact it
    writes must stamp exactly the head the caller passes, even when the real
    git HEAD has since moved on (e.g. an unrelated commit mid-run).
    """

    def test_stamps_the_explicit_head_not_live_git_head(self, repo_cli, tmp_path):
        live_head = _git_commit(tmp_path)
        fake_head = "deadbeef"
        assert fake_head != live_head

        out = tmp_path / ".2brain"
        out.mkdir()
        (out / "EXECUTION.md").write_text("# Execution Knowledge\n")

        repo_cli._build_layers(
            str(tmp_path), provider="ollama", model="qwen3:8b", mode="extract", ai_target="neutral", head=fake_head
        )

        context = (out / "REPO_CONTEXT.md").read_text()
        assert f"commit `{fake_head}`" in context
        assert live_head not in context


_FRESHNESS_FIXTURE = """\
## Graph Freshness

- Built from commit: `ad8d8602`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Knowledge Gaps

- **12 isolated node(s)** — run `graphify query` to explore isolated nodes.
"""


class TestGraphFreshnessAdviceRewrite:
    """C4: graphify's own report tells the reader to bypass 2brain (and,
    without GRAPHIFY_OUT, to write a second graphify-out/ at the repo root).
    graphify is pinned and ships breaking changes often, so this is a text
    rewrite on our side rather than a patch to graphify itself.
    """

    def test_rewrites_freshness_and_query_advice(self, repo_cli):
        rewritten = repo_cli._rewrite_graph_freshness_advice(_FRESHNESS_FIXTURE, "/repo")

        assert "git rev-parse HEAD" not in rewritten
        assert "graphify update ." not in rewritten
        assert "graphify query" not in rewritten
        assert "2brain check /repo" in rewritten
        assert "2brain /repo" in rewritten
        assert "2brain query /repo" in rewritten

    def test_report_without_the_heading_is_unchanged(self, repo_cli):
        text = "# Graph Report\n\n## Summary\n\n- 5 nodes\n"
        assert repo_cli._rewrite_graph_freshness_advice(text, "/repo") == text


class TestReindexRegeneratesExecution:
    """EXECUTION.md is deterministic and free, so `2brain reindex` should not
    need a full `2brain graph` run to pick up an EXECUTION.md fix.
    """

    def test_reindex_rewrites_execution_md_from_current_repo_metadata(self, repo_cli, tmp_path):
        _git_commit(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))

        out = tmp_path / ".2brain"
        out.mkdir()
        (out / "EXECUTION.md").write_text("stale placeholder\n")

        repo_cli._reindex(str(tmp_path), provider="ollama", model="qwen3:8b", ai_target="neutral")

        content = (out / "EXECUTION.md").read_text()
        assert "npm run test" in content
        assert "stale placeholder" not in content

