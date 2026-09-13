"""EXECUTION.md's container-runtime extraction: compose files and required env."""

from __future__ import annotations

from repo import execution

_COMPOSE = """\
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama-data:/root/.ollama-data:rw

  scripts:
    build:
      context: .
      dockerfile: Dockerfile.scripts
    volumes:
      - ./vault:/vault:rw
      - ./scripts:/scripts:ro
    depends_on:
      - ollama

volumes:
  ollama-data:
    driver: local
"""

_ENV_EXAMPLE = """\
# ── REQUIRED ──────────────────────────────────────────────────────────────────
LINUX_USERNAME=your-username
CONTAINER_ENGINE=podman

# ── PRESETS ───────────────────────────────────────────────────────────────────
DEFAULT_PRESET=fast
PRESET_FAST=ollama:qwen3:8b
"""


class TestReadComposeServices:
    def test_extracts_service_image_volumes_depends_on(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(_COMPOSE)

        services = execution._read_compose_services(compose)

        by_name = {s["name"]: s for s in services}
        assert by_name["ollama"]["image"] == "ollama/ollama:latest"
        assert by_name["ollama"]["volumes"] == ["ollama-data:/root/.ollama-data:rw"]
        assert by_name["scripts"]["build"] is True
        assert by_name["scripts"]["depends_on"] == ["ollama"]
        assert by_name["scripts"]["volumes"] == ["./vault:/vault:rw", "./scripts:/scripts:ro"]

    def test_stops_at_a_top_level_sibling_key(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(_COMPOSE)

        services = execution._read_compose_services(compose)

        assert {s["name"] for s in services} == {"ollama", "scripts"}


class TestReadComposeFiles:
    def test_only_known_compose_files_that_exist_are_read(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(_COMPOSE)

        files = execution._read_compose_files(tmp_path)

        assert [f["file"] for f in files] == ["docker-compose.yml"]

    def test_missing_compose_files_produce_an_empty_list(self, tmp_path):
        assert execution._read_compose_files(tmp_path) == []


class TestReadRequiredEnv:
    def test_only_the_required_section_is_returned(self, tmp_path):
        env_example = tmp_path / ".env-example"
        env_example.write_text(_ENV_EXAMPLE)

        required = execution._read_required_env(env_example)

        assert required == [
            ("LINUX_USERNAME", "your-username"),
            ("CONTAINER_ENGINE", "podman"),
        ]
        assert not any(var == "DEFAULT_PRESET" for var, _ in required)

    def test_missing_file_produces_an_empty_list(self, tmp_path):
        assert execution._read_required_env(tmp_path / ".env-example") == []


class TestGenerateIncludesContainerRuntime:
    def test_compose_services_appear_in_execution_md(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(_COMPOSE)
        (tmp_path / ".env-example").write_text(_ENV_EXAMPLE)

        execution.generate(str(tmp_path))

        content = (tmp_path / ".2brain" / "EXECUTION.md").read_text()
        assert "## Container Runtime" in content
        assert "**scripts**" in content
        assert "depends on: ollama" in content
        assert "## Required Environment" in content
        assert "LINUX_USERNAME=your-username" in content
