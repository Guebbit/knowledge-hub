"""The post-commit staleness hook: where it installs, and that it never clobbers
a foreign hook or hook manager. Uses real git repos — core.hooksPath, worktrees
and file-tracking state can't be faked without one.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

_REPO_PY = Path(__file__).resolve().parent.parent / "scripts" / "repo.py"


@pytest.fixture(scope="module")
def repo_cli():
    spec = importlib.util.spec_from_file_location("repo_cli_under_test_hook", _REPO_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("hello")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "first")


def _init_husky_repo(path: Path) -> None:
    """A minimal, realistic Husky v9 layout: core.hooksPath=.husky/_, with _/h present."""
    _init_repo(path)
    husky_runner = path / ".husky" / "_"
    husky_runner.mkdir(parents=True)
    (husky_runner / "h").write_text('#!/usr/bin/env sh\n[ "$HUSKY" = "2" ] && set -x\n')
    # Real `husky init` writes this too — everything under _/ is generated, so
    # nothing there should ever show up in `git status`.
    (husky_runner / ".gitignore").write_text("*\n")
    _git(path, "config", "core.hooksPath", ".husky/_")


class TestHookBodyIsPosix:
    def test_no_bashisms(self, repo_cli):
        body = repo_cli._hook_body()
        assert "[[ " not in body  # bash's conditional; POSIX `[ ` is used throughout
        assert " ]]" not in body
        assert body.startswith("#!/bin/sh\n")

    def test_syntax_is_valid_under_sh(self, repo_cli, tmp_path):
        script = tmp_path / "hook.sh"
        script.write_text(repo_cli._hook_body())
        result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_runs_cleanly_with_no_state_file(self, repo_cli, tmp_path):
        _init_repo(tmp_path)
        script = tmp_path / "hook.sh"
        script.write_text(repo_cli._hook_body())
        result = subprocess.run(["sh", str(script)], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


class TestHooksTarget:
    def test_plain_repo_targets_git_hooks_dir(self, repo_cli, tmp_path):
        _init_repo(tmp_path)
        kind, path = repo_cli._hooks_target(str(tmp_path))
        assert kind == "git"
        assert path == (tmp_path / ".git" / "hooks" / "post-commit").resolve()

    def test_worktree_targets_the_common_git_dir(self, repo_cli, tmp_path):
        main = tmp_path / "main"
        main.mkdir()
        _init_repo(main)
        worktree = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", str(worktree), "-b", "feature")

        kind, path = repo_cli._hooks_target(str(worktree))

        assert kind == "git"
        assert path == (main / ".git" / "hooks" / "post-commit").resolve()

    def test_husky_hookspath_is_detected(self, repo_cli, tmp_path):
        _init_husky_repo(tmp_path)
        kind, path = repo_cli._hooks_target(str(tmp_path))
        assert kind == "husky"
        assert path == (tmp_path / ".husky" / "post-commit").resolve()

    def test_unrecognized_hookspath_inside_tree_is_foreign(self, repo_cli, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / ".githooks").mkdir()
        _git(tmp_path, "config", "core.hooksPath", ".githooks")

        kind, path = repo_cli._hooks_target(str(tmp_path))

        assert kind == "foreign"
        assert path is None


class TestInstallHook:
    def test_installs_in_git_hooks_when_absent(self, repo_cli, tmp_path):
        _init_repo(tmp_path)
        repo_cli._install_hook(str(tmp_path))

        hook = tmp_path / ".git" / "hooks" / "post-commit"
        assert hook.is_file()
        assert repo_cli._hook_is_ours(hook)
        assert os.access(hook, os.X_OK)

    def test_foreign_git_hooks_post_commit_is_left_untouched(self, repo_cli, tmp_path, capsys):
        _init_repo(tmp_path)
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        foreign = hooks_dir / "post-commit"
        foreign.write_text("#!/bin/sh\necho lefthook\n")

        repo_cli._install_hook(str(tmp_path))

        assert foreign.read_text() == "#!/bin/sh\necho lefthook\n"
        out = capsys.readouterr().out
        assert "not ours" in out
        assert "add this to" in out

    def test_husky_no_post_commit_installs_and_excludes(self, repo_cli, tmp_path):
        _init_husky_repo(tmp_path)

        repo_cli._install_hook(str(tmp_path))

        hook = tmp_path / ".husky" / "post-commit"
        assert hook.is_file()
        assert repo_cli._hook_is_ours(hook)
        exclude = (tmp_path / ".git" / "info" / "exclude").read_text()
        assert ".husky/post-commit" in exclude.splitlines()
        status = _git(tmp_path, "status", "--porcelain")
        assert status.stdout.strip() == "", "the untracked hook must not show up as a change"

    def test_husky_install_twice_has_one_file_and_one_exclude_line(self, repo_cli, tmp_path):
        _init_husky_repo(tmp_path)

        repo_cli._install_hook(str(tmp_path))
        repo_cli._install_hook(str(tmp_path))

        exclude = (tmp_path / ".git" / "info" / "exclude").read_text()
        assert exclude.count(".husky/post-commit") == 1

    def test_husky_tracked_post_commit_is_left_untouched(self, repo_cli, tmp_path, capsys):
        _init_husky_repo(tmp_path)
        hook = tmp_path / ".husky" / "post-commit"
        hook.write_text(repo_cli._hook_body())  # ours by content, but about to become tracked
        _git(tmp_path, "add", str(hook))
        _git(tmp_path, "commit", "-q", "-m", "track the hook")

        repo_cli._install_hook(str(tmp_path))

        out = capsys.readouterr().out
        assert "tracked" in out  # ours by marker, but tracked, so still left alone
        assert "add this to" in out
        status = _git(tmp_path, "status", "--porcelain")
        assert status.stdout.strip() == ""

    def test_unrecognized_hookspath_writes_nothing(self, repo_cli, tmp_path, capsys):
        _init_repo(tmp_path)
        (tmp_path / ".githooks").mkdir()
        _git(tmp_path, "config", "core.hooksPath", ".githooks")

        repo_cli._install_hook(str(tmp_path))

        assert list((tmp_path / ".githooks").iterdir()) == []
        out = capsys.readouterr().out
        assert "unrecognized hook manager" in out


class TestOfferHook:
    def test_silent_once_our_hook_is_installed(self, repo_cli, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        repo_cli._install_hook(str(tmp_path))
        capsys.readouterr()
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: False)

        repo_cli._offer_hook(str(tmp_path))

        assert capsys.readouterr().out == ""

    def test_notes_instead_of_prompting_for_a_foreign_hook(self, repo_cli, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "post-commit").write_text("#!/bin/sh\necho lefthook\n")
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)

        repo_cli._offer_hook(str(tmp_path))

        out = capsys.readouterr().out
        assert "not ours" in out
        assert "Install the staleness hook now?" not in out

    def test_non_interactive_points_at_2brain_hook(self, repo_cli, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: False)

        repo_cli._offer_hook(str(tmp_path))

        assert "2brain hook ." in capsys.readouterr().out

    def test_prompt_env_opt_out_is_silent(self, repo_cli, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        monkeypatch.setenv(repo_cli._HOOK_PROMPT_ENV, "0")

        repo_cli._offer_hook(str(tmp_path))

        assert capsys.readouterr().out == ""

    def test_yes_installs(self, repo_cli, tmp_path, monkeypatch):
        _init_repo(tmp_path)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")

        repo_cli._offer_hook(str(tmp_path))

        assert repo_cli._hook_is_ours(tmp_path / ".git" / "hooks" / "post-commit")

    def test_empty_answer_does_not_install(self, repo_cli, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        monkeypatch.setattr(repo_cli.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "")

        repo_cli._offer_hook(str(tmp_path))

        assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()
        assert "skipped" in capsys.readouterr().out
