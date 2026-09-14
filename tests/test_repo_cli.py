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


class TestHookOffer:
    """The end-of-run prompt must stay silent in every case where asking would be
    wrong: no git repo, our hook already installed, the user opted out, or a
    foreign post-commit hook that _install_hook would overwrite.
    """

    @staticmethod
    def _write_post_commit(path: Path, body: str) -> Path:
        hooks = path / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "post-commit"
        hook.write_text(body)
        return hook

    def test_detects_our_own_hook(self, repo_cli, tmp_path):
        self._write_post_commit(tmp_path, "#!/usr/bin/env bash\necho '2brain warning: ...'\n")
        assert repo_cli._hook_is_installed(str(tmp_path)) is True

    def test_foreign_hook_is_not_ours(self, repo_cli, tmp_path):
        self._write_post_commit(tmp_path, "#!/usr/bin/env bash\nmake lint\n")
        assert repo_cli._hook_is_installed(str(tmp_path)) is False

    def test_missing_hook_is_not_installed(self, repo_cli, tmp_path):
        assert repo_cli._hook_is_installed(str(tmp_path)) is False

    def test_silent_outside_a_git_repo(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: False)
        repo_cli._offer_hook(str(tmp_path))
        assert capsys.readouterr().out == ""

    def test_silent_when_already_installed(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        self._write_post_commit(tmp_path, "#!/usr/bin/env bash\n# 2brain warning\n")
        repo_cli._offer_hook(str(tmp_path))
        assert capsys.readouterr().out == ""

    def test_silent_when_opted_out(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        monkeypatch.setenv(repo_cli._HOOK_PROMPT_ENV, "0")
        repo_cli._offer_hook(str(tmp_path))
        assert capsys.readouterr().out == ""

    def test_never_overwrites_a_foreign_hook(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        monkeypatch.delenv(repo_cli._HOOK_PROMPT_ENV, raising=False)
        hook = self._write_post_commit(tmp_path, "#!/usr/bin/env bash\nmake lint\n")

        def _boom(_path):
            raise AssertionError("_install_hook must not run when a foreign hook exists")

        monkeypatch.setattr(repo_cli, "_install_hook", _boom)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)
        repo_cli._offer_hook(str(tmp_path))

        assert "left untouched" in capsys.readouterr().out
        assert hook.read_text() == "#!/usr/bin/env bash\nmake lint\n"

    def test_non_interactive_hints_instead_of_prompting(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        monkeypatch.delenv(repo_cli._HOOK_PROMPT_ENV, raising=False)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: False)
        repo_cli._offer_hook(str(tmp_path))
        assert "2brain hook ." in capsys.readouterr().out

    def test_yes_installs(self, repo_cli, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        monkeypatch.delenv(repo_cli._HOOK_PROMPT_ENV, raising=False)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")
        installed: list[str] = []
        monkeypatch.setattr(repo_cli, "_install_hook", lambda path: installed.append(path))
        repo_cli._offer_hook(str(tmp_path))
        assert installed == [str(tmp_path)]

    def test_default_is_no(self, repo_cli, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(repo_cli, "_in_git_repo", lambda _p: True)
        monkeypatch.delenv(repo_cli._HOOK_PROMPT_ENV, raising=False)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "")

        def _boom(_path):
            raise AssertionError("empty answer must not install")

        monkeypatch.setattr(repo_cli, "_install_hook", _boom)
        repo_cli._offer_hook(str(tmp_path))
        assert "skipped" in capsys.readouterr().out
