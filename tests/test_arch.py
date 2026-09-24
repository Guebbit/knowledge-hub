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
    against it — so 2brain has to pass the real window down (see
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


class TestEstimatedDuration:
    """A1: no up-front estimate meant a local-model run could eat the whole
    server window with no warning. The estimate is file_count * seconds/file,
    falling back to a conservative default on a first run.
    """

    def test_prior_rate_drives_the_estimate(self):
        assert arch._estimated_seconds(100, 2.0) == 200.0

    def test_no_prior_rate_uses_the_conservative_default(self):
        assert arch._estimated_seconds(100, None) == 100 * arch._DEFAULT_SECONDS_PER_FILE

    def test_zero_files_is_zero_seconds(self):
        assert arch._estimated_seconds(0, 5.0) == 0.0

    def test_print_estimate_names_its_source(self, capsys):
        arch._print_estimate(10, 3.0)
        assert "last recorded rate" in capsys.readouterr().out

        arch._print_estimate(10, None)
        assert "conservative default" in capsys.readouterr().out


# A real "Token Usage" line from a boilerplate arch run's log
# (.codeboarding/logs/*.log), to keep the parser honest against the actual format.
_REAL_STEP_LOG_LINE = (
    "2026-09-23 20:44:57 INFO     [monitoring:62] Token Usage: step=_step_llm_analysis "
    'model=qwen3.8:27b usage={"input_tokens": 2610, "output_tokens": 1957, "total_tokens": 4567}\n'
)


class TestParseStep:
    """6.4: a terse progress line needs a step marker to count — CodeBoarding's
    own log is the only source, so the parser is pinned to a real line from it.
    """

    def test_extracts_the_step_name_from_a_real_log_line(self):
        assert arch._parse_step(_REAL_STEP_LOG_LINE) == "_step_llm_analysis"

    def test_other_named_steps_are_extracted_too(self):
        line = "... Token Usage: step=_step_api_surfaces model=x usage={}\n"
        assert arch._parse_step(line) == "_step_api_surfaces"

    def test_unrelated_lines_yield_none(self):
        assert arch._parse_step("Modules  : [3/30] tests/unit/  (17 files)\n") is None
        assert arch._parse_step("") is None


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
