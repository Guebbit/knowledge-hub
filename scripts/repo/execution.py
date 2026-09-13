"""
Execution-knowledge extractor for 2brain.

Builds a repo-local markdown summary of practical execution metadata:
- build/test/lint/dev scripts
- CI run commands
- migration locations and tool hints

Output:
- <repo>/<config.OUT_DIR>/EXECUTION.md
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from shared import config

_SCRIPT_KEYWORDS = ("test", "build", "lint", "start", "dev", "check", "format")
_MAX_WORKFLOW_RUN_COMMANDS = 12
_MAX_MIGRATION_PATHS = 20
_MAX_QUICK_COMMANDS = 20
_MAKEFILE_TARGET_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?![=])")
_WORKFLOW_NAME_PATTERN = re.compile(r"^\s*name:\s*(.+)\s*$")
_WORKFLOW_RUN_PATTERN = re.compile(r"^(\s*)run:\s*(.*)\s*$")
_YAML_BLOCK_SCALAR_PATTERN = re.compile(r"^[|>][0-9]?[-+]?$")
_MIGRATION_PATH_GLOBS = (
    "**/alembic/versions",
    "**/prisma/migrations",
    "**/db/migrate",
    "**/migrations",
    "**/migration",
    "**/sql/migrations",
)
_MIGRATION_HINT_FILES = (
    "alembic.ini",
    "prisma/schema.prisma",
    "liquibase.properties",
    "flyway.conf",
    "manage.py",
)
_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.windows.yml")
# Compose files in this project are hand-authored with a consistent 2-space
# indent, so a line-oriented indent scan is enough to pull out what
# EXECUTION.md needs — a full YAML parser (PyYAML) would be the only
# dependency of its kind in this stdlib-only script.
_COMPOSE_SERVICE_PATTERN = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$")
_COMPOSE_LIST_ITEM_PATTERN = re.compile(r"^\s*-\s*(.+?)\s*$")
_ENV_SECTION_HEADER_PATTERN = re.compile(r"^#\s*──+\s*([A-Z][A-Z0-9 /]*[A-Z0-9])\s*──+")
_ENV_VAR_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def generate(repo_path: str) -> None:
    """Generate <OUT_DIR>/EXECUTION.md for the target repository."""
    repo = Path(repo_path)
    output = repo / config.OUT_DIR / "EXECUTION.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    package_scripts = _read_package_scripts(repo / "package.json")
    make_targets = _read_make_targets(repo / "Makefile")
    pyproject_scripts = _read_pyproject_scripts(repo / "pyproject.toml")
    workflows = _read_workflows(repo / ".github" / "workflows")
    migration_paths, migration_hints = _read_migrations(repo)
    compose_files = _read_compose_files(repo)
    required_env = _read_required_env(repo / ".env-example")

    output.write_text(
        _render_markdown(
            package_scripts=package_scripts,
            make_targets=make_targets,
            pyproject_scripts=pyproject_scripts,
            workflows=workflows,
            migration_paths=migration_paths,
            migration_hints=migration_hints,
            compose_files=compose_files,
            required_env=required_env,
        )
    )
    print(f"Execution: {output}")


def _read_package_scripts(path: Path) -> dict[str, str]:
    """Read package.json scripts as a string->string map."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return _string_dict(scripts)


def _read_make_targets(path: Path) -> list[str]:
    """Parse user-invokable Makefile targets, excluding internals/pattern rules."""
    if not path.exists():
        return []
    targets: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip() or line.startswith("\t") or line.lstrip().startswith("#"):
                continue
            match = _MAKEFILE_TARGET_PATTERN.match(line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith(".") or "%" in target or target in seen:
                continue
            seen.add(target)
            targets.append(target)
    return targets


def _read_pyproject_scripts(path: Path) -> dict[str, str]:
    """Collect runnable script/task definitions from common pyproject sections."""
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}

    scripts: dict[str, str] = {}
    project_scripts = data.get("project", {}).get("scripts", {})
    if isinstance(project_scripts, dict):
        scripts.update(_string_dict(project_scripts))

    poetry_scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
    if isinstance(poetry_scripts, dict):
        for k, v in poetry_scripts.items():
            if isinstance(k, str):
                if isinstance(v, str):
                    scripts[k] = v
                elif isinstance(v, dict) and isinstance(v.get("callable"), str):
                    scripts[k] = f"callable:{v['callable']}"

    poe_tasks = data.get("tool", {}).get("poe", {}).get("tasks", {})
    if isinstance(poe_tasks, dict):
        for k, v in poe_tasks.items():
            if isinstance(k, str):
                normalized = _normalize_poe_task(v)
                if normalized:
                    scripts[f"poe:{k}"] = normalized
    return scripts


def _normalize_poe_task(value: object) -> str | None:
    """Normalize Poe task definitions (string/list/dict) into one shell command."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [item for item in value if isinstance(item, str)]
        return " && ".join(parts) if parts else None
    if isinstance(value, dict):
        cmd = value.get("cmd")
        if isinstance(cmd, str):
            return cmd
        sequence = value.get("sequence")
        if isinstance(sequence, list):
            parts = [item for item in sequence if isinstance(item, str)]
            return " && ".join(parts) if parts else None
    return None


def _string_dict(raw: dict[object, object]) -> dict[str, str]:
    """Filter a mixed dict to only string keys and string values."""
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _matches_script_keyword(name: str) -> bool:
    """Return True when a script name hints at build/test/lint/dev style usage."""
    tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token]
    return any(token in _SCRIPT_KEYWORDS for token in tokens)


def _read_workflows(dir_path: Path) -> list[dict[str, object]]:
    """Extract workflow names and run commands from GitHub Actions YAML files."""
    if not dir_path.exists():
        return []

    workflows: list[dict[str, object]] = []
    for wf in sorted(list(dir_path.glob("*.yml")) + list(dir_path.glob("*.yaml"))):
        lines = wf.read_text(encoding="utf-8", errors="replace").splitlines()
        name = None
        run_commands: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if name is None:
                name_match = _WORKFLOW_NAME_PATTERN.match(line)
                if name_match:
                    name = name_match.group(1).strip().strip("\"'")

            run_match = _WORKFLOW_RUN_PATTERN.match(line)
            if run_match:
                run_indent = len(run_match.group(1))
                run_value = run_match.group(2).strip()
                cmd: str | None
                consumed_block = False
                if _YAML_BLOCK_SCALAR_PATTERN.match(run_value):
                    block_lines: list[str] = []
                    i += 1
                    consumed_block = True
                    while i < len(lines):
                        next_line = lines[i]
                        if not next_line.strip():
                            block_lines.append("")
                            i += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip(" "))
                        if next_indent <= run_indent:
                            break
                        block_lines.append(next_line.strip())
                        i += 1
                    cmd = "\n".join(part for part in block_lines if part)
                else:
                    cmd = run_value or None

                if cmd and cmd not in run_commands:
                    run_commands.append(cmd)
                if not consumed_block:
                    i += 1
                continue

            i += 1

        workflows.append(
            {
                "file": str(wf.relative_to(dir_path.parent.parent)),
                "name": name,
                "run_commands": run_commands[:_MAX_WORKFLOW_RUN_COMMANDS],
            }
        )
    return workflows


def _read_migrations(repo: Path) -> tuple[list[str], list[str]]:
    """Find likely migration directories and migration-tool hint files."""
    migration_paths: list[str] = []
    seen_paths: set[str] = set()
    for pattern in _MIGRATION_PATH_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if not path.is_dir():
                continue
            rel = str(path.relative_to(repo))
            if rel not in seen_paths:
                seen_paths.add(rel)
                migration_paths.append(rel)
            if len(migration_paths) >= _MAX_MIGRATION_PATHS:
                break
        if len(migration_paths) >= _MAX_MIGRATION_PATHS:
            break

    hints: list[str] = []
    for rel in _MIGRATION_HINT_FILES:
        hint_path = repo / rel
        if hint_path.exists():
            hints.append(rel)
    return migration_paths, hints


def _read_compose_services(path: Path) -> list[dict[str, object]]:
    """Extract service name, image/build, volumes, and depends_on from one compose file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    services: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_key: str | None = None
    in_services = False

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if line.rstrip() == "services:":
            in_services = True
            continue
        if not in_services:
            continue
        if indent == 0:
            # Back out to a top-level sibling key (volumes:, networks:, ...) — done.
            break

        service_match = _COMPOSE_SERVICE_PATTERN.match(line) if indent == 2 else None
        if service_match:
            current = {"name": service_match.group(1), "image": None, "build": False, "volumes": [], "depends_on": []}
            services.append(current)
            current_key = None
            continue
        if current is None:
            continue

        if indent == 4:
            stripped = line.strip()
            if stripped == "volumes:":
                current_key = "volumes"
            elif stripped == "depends_on:":
                current_key = "depends_on"
            elif stripped.startswith("image:"):
                current["image"] = stripped.removeprefix("image:").strip()
                current_key = None
            elif stripped.startswith("build:"):
                current["build"] = True
                current_key = None
            else:
                current_key = None
            continue

        if indent >= 6 and current_key in ("volumes", "depends_on"):
            item_match = _COMPOSE_LIST_ITEM_PATTERN.match(line)
            if item_match:
                current[current_key].append(item_match.group(1))

    return services


def _read_compose_files(repo: Path) -> list[dict[str, object]]:
    """Read every known compose file present, so multi-platform setups are all documented."""
    files: list[dict[str, object]] = []
    for name in _COMPOSE_FILES:
        path = repo / name
        if not path.exists():
            continue
        files.append({"file": name, "services": _read_compose_services(path)})
    return files


def _read_required_env(path: Path) -> list[tuple[str, str]]:
    """Return (var, default-or-example) pairs from .env-example's REQUIRED section.

    Deliberately narrow: .env-example documents every optional preset/API key
    too, which would drown the one thing an assistant actually needs before it
    can run anything. The REQUIRED section header is the same convention the
    file already uses to mark them.
    """
    if not path.exists():
        return []
    in_required = False
    required: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        header_match = _ENV_SECTION_HEADER_PATTERN.match(line)
        if header_match:
            in_required = header_match.group(1).strip() == "REQUIRED"
            continue
        if not in_required:
            continue
        var_match = _ENV_VAR_PATTERN.match(line.strip())
        if var_match:
            required.append((var_match.group(1), var_match.group(2)))
    return required


def _quick_commands(
    package_scripts: dict[str, str],
    make_targets: list[str],
    pyproject_scripts: dict[str, str],
) -> list[str]:
    """Build a short, deduplicated list of likely day-to-day project commands."""
    commands: list[str] = []
    seen: set[str] = set()

    for name in package_scripts:
        if _matches_script_keyword(name):
            cmd = f"npm run {name}"
            if cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)

    for target in make_targets:
        if _matches_script_keyword(target):
            cmd = f"make {target}"
            if cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)

    for name in pyproject_scripts:
        if name.startswith("poe:"):
            cmd = f"poe {name.removeprefix('poe:')}"
        else:
            cmd = name
        if _matches_script_keyword(name) and cmd not in seen:
            seen.add(cmd)
            commands.append(cmd)
    return commands[:_MAX_QUICK_COMMANDS]


def _render_markdown(
    *,
    package_scripts: dict[str, str],
    make_targets: list[str],
    pyproject_scripts: dict[str, str],
    workflows: list[dict[str, object]],
    migration_paths: list[str],
    migration_hints: list[str],
    compose_files: list[dict[str, object]],
    required_env: list[tuple[str, str]],
) -> str:
    """Render extracted execution metadata into EXECUTION.md markdown."""
    lines: list[str] = []
    lines.append("# Execution Knowledge")
    lines.append("")
    lines.append("_Generated by 2brain from repository metadata (scripts, CI, migrations)._")
    lines.append("")

    if compose_files:
        lines.append("## Container Runtime")
        lines.append(
            "Everything here runs through `docker compose` / `podman compose` — there is no "
            "bare-metal `pip install` path for the pipeline itself."
        )
        for entry in compose_files:
            file_name = str(entry["file"])
            services = entry["services"]
            lines.append("")
            lines.append(f"### `{file_name}`")
            for service in services:
                name = service["name"]
                base = f"image `{service['image']}`" if service["image"] else "built from `build:`"
                lines.append(f"- **{name}** — {base}")
                if service["depends_on"]:
                    lines.append(f"  - depends on: {', '.join(service['depends_on'])}")
                if service["volumes"]:
                    lines.append("  - mounts:")
                    for volume in service["volumes"]:
                        lines.append(f"    - `{volume}`")
            lines.append("")
            lines.append(
                f"Run pattern: `docker compose -f {file_name} run --rm <service> <command>` "
                "(or `podman compose`, per `CONTAINER_ENGINE` in `.env`) — this is the actual "
                "entry point, not a direct interpreter invocation."
            )
        if len(compose_files) > 1:
            lines.append("")
            lines.append(
                f"Platform variants: `{_COMPOSE_FILES[1]}` is standalone (does not merge with "
                f"`{_COMPOSE_FILES[0]}`) — it is the CPU/Windows definition, used directly via `-f`, "
                "not as a compose override."
            )
        lines.append("")
        lines.append(
            "Exception: the `2brain` CLI wrapper runs `query` and `check` directly on the host "
            "(pure stdlib, no container) unless `--host`/`--container` or `REPO_MODE` forces "
            "otherwise — every other subcommand still goes through the pattern above."
        )
        lines.append("")

    if required_env:
        lines.append("## Required Environment (.env-example)")
        for var, default in required_env:
            lines.append(f"- `{var}={default}`" if default else f"- `{var}`")
        lines.append("")

    quick = _quick_commands(package_scripts, make_targets, pyproject_scripts)
    lines.append("## Quick Commands")
    if quick:
        lines.extend(f"- `{cmd}`" for cmd in quick)
    else:
        lines.append("- No obvious build/test/lint/dev commands detected.")
    lines.append("")

    lines.append("## Project Scripts")
    if package_scripts:
        lines.append("### package.json")
        for name, command in package_scripts.items():
            lines.append(f"- `{name}` → `{command}`")
    if make_targets:
        lines.append("### Makefile")
        lines.extend(f"- `{target}`" for target in make_targets)
    if pyproject_scripts:
        lines.append("### pyproject.toml")
        for name, command in pyproject_scripts.items():
            lines.append(f"- `{name}` → `{command}`")
    if not package_scripts and not make_targets and not pyproject_scripts:
        lines.append("- No script metadata detected.")
    lines.append("")

    lines.append("## CI Workflows")
    if workflows:
        for wf in workflows:
            file_name = str(wf.get("file") or "unknown-workflow")
            label = wf.get("name") or file_name
            lines.append(f"- `{file_name}` — {label}")
            run_commands = wf.get("run_commands", [])
            if run_commands:
                for cmd in run_commands:
                    display_cmd = cmd.replace("\n", " ⏎ ")
                    lines.append(f"  - `run: {display_cmd}`")
    else:
        lines.append("- No GitHub Actions workflows detected.")
    lines.append("")

    lines.append("## Migrations")
    if migration_paths:
        lines.append("### Migration directories")
        lines.extend(f"- `{path}`" for path in migration_paths)
    if migration_hints:
        lines.append("### Tool hint files")
        lines.extend(f"- `{path}`" for path in migration_hints)
    if not migration_paths and not migration_hints:
        lines.append("- No migration directories or common migration tool files detected.")
    lines.append("")

    return "\n".join(lines)
