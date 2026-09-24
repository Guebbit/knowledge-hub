"""EXECUTION.md's container-runtime extraction: compose files and required env."""

from __future__ import annotations

import json
import subprocess

from repo import execution


def _git_repo(path, files: dict[str, str]):
    """Init a real git repo at `path`, write `files` (any .gitignore among them takes effect), then `git add -A`."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    for rel, content in files.items():
        file_path = path / rel
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)

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

    def test_no_knowledge_hub_prose_leaks_into_a_target_repo(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text(_COMPOSE)
        (tmp_path / "docker-compose.production.yml").write_text(_COMPOSE)

        execution.generate(str(tmp_path))

        content = (tmp_path / ".2brain" / "EXECUTION.md").read_text().lower()
        assert "pip install" not in content
        assert "cli wrapper" not in content
        assert "platform variant" not in content
        assert "container_engine" not in content


_PACKAGE_JSON_MANY_LINT_SCRIPTS = {
    "scripts": {**{f"lint:{i}": "eslint ." for i in range(25)}, "test": "jest"},
}


class TestQuickCommandsPriority:
    def test_test_script_survives_the_cap_and_sorts_first(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps(_PACKAGE_JSON_MANY_LINT_SCRIPTS))

        execution.generate(str(tmp_path))

        content = (tmp_path / ".2brain" / "EXECUTION.md").read_text()
        quick_section = content.split("## Quick Commands", 1)[1].split("## Project Scripts", 1)[0]
        commands = [line for line in quick_section.splitlines() if line.startswith("- `")]
        assert commands[0] == "- `npm run test`"

    def test_canonical_names_checked_across_all_three_sources(self):
        commands = execution._quick_commands(
            package_scripts={"test": "jest"},
            make_targets=["build"],
            pyproject_scripts={"dev": "uvicorn app:app --reload"},
        )
        assert commands[:3] == ["npm run test", "make build", "dev"]


class TestDiscoverComposeFiles:
    def test_base_first_then_variants_alphabetically(self, tmp_path):
        for name in ("docker-compose.yml", "docker-compose.production.yml", "docker-compose.test.yml"):
            (tmp_path / name).write_text("services:\n")

        files = execution._discover_compose_files(tmp_path)

        assert files == ["docker-compose.yml", "docker-compose.production.yml", "docker-compose.test.yml"]

    def test_modern_compose_naming_is_found_too(self, tmp_path):
        (tmp_path / "compose.yaml").write_text("services:\n")

        assert execution._discover_compose_files(tmp_path) == ["compose.yaml"]


_COMPOSE_4_SPACE = """\
services:
    app:
        build:
            context: .
        volumes:
            - .:/app:Z
        depends_on:
            - database
    database:
        image: mongo:8
"""


class TestReadComposeServicesIndentAgnostic:
    def test_2_space_and_4_space_indent_give_identical_output(self, tmp_path):
        two_space = tmp_path / "two.yml"
        two_space.write_text(_COMPOSE)
        four_space = tmp_path / "four.yml"
        four_space.write_text(_COMPOSE_4_SPACE)

        four_space_services = execution._read_compose_services(four_space)

        by_name = {s["name"]: s for s in four_space_services}
        assert by_name["app"]["build"] is True
        assert by_name["app"]["volumes"] == [".:/app:Z"]
        assert by_name["app"]["depends_on"] == ["database"]
        assert by_name["database"]["image"] == "mongo:8"


class TestReadMigrations:
    def test_only_tracked_migrations_are_reported(self, tmp_path):
        _git_repo(
            tmp_path,
            files={
                ".gitignore": "node_modules/\n",
                "db/migrations/001_init.sql": "-- init",
                "node_modules/x/migrations/001.js": "// vendored",
            },
        )

        paths, _hints = execution._read_migrations(tmp_path)

        assert paths == ["db/migrations"]

    def test_non_git_repo_falls_back_to_a_pruned_walk(self, tmp_path):
        (tmp_path / "db" / "migrations").mkdir(parents=True)
        (tmp_path / "db" / "migrations" / "001_init.sql").write_text("-- init")
        (tmp_path / "node_modules" / "x" / "migrations").mkdir(parents=True)
        (tmp_path / "node_modules" / "x" / "migrations" / "001.js").write_text("// vendored")

        paths, _hints = execution._read_migrations(tmp_path)

        assert paths == ["db/migrations"]


class TestReadEnvVarCount:
    def test_no_required_header_gives_a_pointer_line(self, tmp_path):
        env_example = tmp_path / ".env-example"
        env_example.write_text("FOO=bar\nBAZ=qux\nQUUX=1\n")

        execution.generate(str(tmp_path))

        content = (tmp_path / ".2brain" / "EXECUTION.md").read_text()
        assert "## Required Environment" in content
        assert "`.env-example` defines 3 variables — copy it to `.env`." in content

    def test_missing_file_has_no_required_environment_section(self, tmp_path):
        execution.generate(str(tmp_path))

        content = (tmp_path / ".2brain" / "EXECUTION.md").read_text()
        assert "## Required Environment" not in content
