"""Tests for the architecture layer's incremental-baseline detection.

CodeBoarding overwrites analysis.json at intermediate checkpoints during its
abstraction pipeline, so a run killed mid-way leaves a partial analysis.json
behind with no fingerprint.json. `_has_baseline` must not mistake that for a
usable baseline — see the comment above `_FINGERPRINT_FILENAME` in arch.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo import arch


def _codeboarding_dir(repo: str) -> Path:
    d = Path(repo) / ".codeboarding"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestHasBaseline:
    def test_no_codeboarding_dir(self, repo):
        assert arch._has_baseline(repo) is False

    def test_analysis_json_without_fingerprint_is_not_a_baseline(self, repo):
        """A run killed mid-pipeline: analysis.json exists, fingerprint.json doesn't."""
        (_codeboarding_dir(repo) / "analysis.json").write_text("{}", encoding="utf-8")
        assert arch._has_baseline(repo) is False

    def test_fingerprint_without_analysis_json_is_not_a_baseline(self, repo):
        (_codeboarding_dir(repo) / "fingerprint.json").write_text("{}", encoding="utf-8")
        assert arch._has_baseline(repo) is False

    def test_both_files_present_is_a_valid_baseline(self, repo):
        cb_dir = _codeboarding_dir(repo)
        (cb_dir / "analysis.json").write_text("{}", encoding="utf-8")
        (cb_dir / "fingerprint.json").write_text("{}", encoding="utf-8")
        assert arch._has_baseline(repo) is True


class TestContextWindow:
    """`_provider_env` must tell CodeBoarding the window the server really runs.

    CodeBoarding asks Ollama for the model's context length and gets the
    architectural maximum, not the server-side OLLAMA_NUM_CTX, and never budgets
    against it — so 2repo has to pass the real window down (see
    patches/codeboarding/context_budget.py).
    """

    def test_ollama_preset_uses_ollama_num_ctx(self, monkeypatch):
        monkeypatch.delenv("REPO_ARCH_CONTEXT_TOKENS", raising=False)
        monkeypatch.setattr(arch.config, "OLLAMA_NUM_CTX", 32000)
        env = arch._provider_env("ollama", "qwen3:8b")
        assert env["CODEBOARDING_CONTEXT_WINDOW"] == "32000"
        assert env["CODEBOARDING_READ_FILE_LINES"] == "118"

    def test_override_wins_for_any_provider(self, monkeypatch):
        monkeypatch.setenv("REPO_ARCH_CONTEXT_TOKENS", "8000")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        env = arch._provider_env("openai", "gpt-4o")
        assert env["CODEBOARDING_CONTEXT_WINDOW"] == "8000"
        assert env["CODEBOARDING_READ_FILE_LINES"] == "60"  # floor, not 8000 // 270 = 29

    def test_cloud_preset_without_override_gets_no_budget(self, monkeypatch):
        monkeypatch.delenv("REPO_ARCH_CONTEXT_TOKENS", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        env = arch._provider_env("openai", "gpt-4o")
        assert "CODEBOARDING_CONTEXT_WINDOW" not in env
        assert "CODEBOARDING_READ_FILE_LINES" not in env

    def test_zero_disables_the_budget(self, monkeypatch):
        monkeypatch.setenv("REPO_ARCH_CONTEXT_TOKENS", "0")
        env = arch._provider_env("ollama", "qwen3:8b")
        assert "CODEBOARDING_CONTEXT_WINDOW" not in env

    def test_non_numeric_override_is_rejected(self, monkeypatch):
        monkeypatch.setenv("REPO_ARCH_CONTEXT_TOKENS", "lots")
        with pytest.raises(ValueError, match="REPO_ARCH_CONTEXT_TOKENS"):
            arch._provider_env("ollama", "qwen3:8b")

    def test_read_chunk_scales_with_window(self):
        assert arch._read_chunk_lines(32768) == 121
        assert arch._read_chunk_lines(65536) == 242
        assert arch._read_chunk_lines(128000) == 300  # stock size from ~80k up
        assert arch._read_chunk_lines(4096) == 60  # never below a function's worth


class TestRequiresFullAnalysis:
    """CodeBoarding can abort an incremental run (e.g. an engine-version-incompatible
    static-analysis cache) and still exit 0, signalling failure only via this
    pretty-printed JSON payload interleaved with unrelated progress output.
    """

    def test_detects_pretty_printed_payload(self):
        output = (
            "Modules  : [30/30] tests/unit/  (17 files)\n"
            "Traceback (most recent call last):\n"
            "  ...\n"
            "static_analyzer.StaticAnalysisFatalError: ...\n"
            "{\n"
            '  "error": "...",\n'
            '  "mode": "incremental",\n'
            '  "requiresFullAnalysis": true\n'
            "}\n"
        )
        assert arch._requires_full_analysis(output) is True

    def test_false_when_absent(self):
        assert arch._requires_full_analysis("Arch     : wrote overview.md\n") is False

    def test_false_when_flag_is_false(self):
        output = '{\n  "mode": "incremental",\n  "requiresFullAnalysis": false\n}\n'
        assert arch._requires_full_analysis(output) is False
