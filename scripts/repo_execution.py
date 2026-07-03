"""
Execution-knowledge extractor for 2repo.

Builds a repo-local markdown summary of practical execution metadata:
- build/test/lint/dev scripts
- CI run commands
- migration locations and tool hints

Output:
- <repo>/graphify-out/EXECUTION.md
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


_SCRIPT_KEYWORDS = ("test", "build", "lint", "start", "dev", "check", "format")
_MAX_WORKFLOW_RUN_COMMANDS = 12
_MAX_MIGRATION_PATHS = 20
_MAX_QUICK_COMMANDS = 20
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


def generate(repo_path: str) -> None:
    """Generate graphify-out/EXECUTION.md for the target repository."""
    repo = Path(repo_path)
    output = repo / "graphify-out" / "EXECUTION.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    package_scripts = _read_package_scripts(repo / "package.json")
    make_targets = _read_make_targets(repo / "Makefile")
    pyproject_scripts = _read_pyproject_scripts(repo / "pyproject.toml")
    workflows = _read_workflows(repo / ".github" / "workflows")
    migration_paths, migration_hints = _read_migrations(repo)

    output.write_text(
        _render_markdown(
            package_scripts=package_scripts,
            make_targets=make_targets,
            pyproject_scripts=pyproject_scripts,
            workflows=workflows,
            migration_paths=migration_paths,
            migration_hints=migration_hints,
        )
    )
    print(f"Execution: {output}")


def _read_package_scripts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return _string_dict(scripts)


def _read_make_targets(path: Path) -> list[str]:
    if not path.exists():
        return []
    targets: list[str] = []
    seen: set[str] = set()
    with path.open(errors="replace") as handle:
        for line in handle:
            if not line or line.startswith("\t") or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith(".") or "%" in target or target in seen:
                continue
            seen.add(target)
            targets.append(target)
    return targets


def _read_pyproject_scripts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text())
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
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _read_workflows(dir_path: Path) -> list[dict[str, object]]:
    if not dir_path.exists():
        return []

    workflows: list[dict[str, object]] = []
    for wf in sorted(list(dir_path.glob("*.yml")) + list(dir_path.glob("*.yaml"))):
        name = None
        run_commands: list[str] = []
        with wf.open(errors="replace") as handle:
            for line in handle:
                if name is None:
                    name_match = re.match(r"^\s*name:\s*(.+)\s*$", line)
                    if name_match:
                        name = name_match.group(1).strip().strip("\"'")
                run_match = re.match(r"^\s*run:\s*(.+)\s*$", line)
                if run_match:
                    cmd = run_match.group(1).strip()
                    if cmd and cmd not in run_commands:
                        run_commands.append(cmd)

        workflows.append(
            {
                "file": str(wf.relative_to(dir_path.parent.parent)),
                "name": name,
                "run_commands": run_commands[:_MAX_WORKFLOW_RUN_COMMANDS],
            }
        )
    return workflows


def _read_migrations(repo: Path) -> tuple[list[str], list[str]]:
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


def _quick_commands(
    package_scripts: dict[str, str],
    make_targets: list[str],
    pyproject_scripts: dict[str, str],
) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()

    for name in package_scripts:
        if any(k in name.lower() for k in _SCRIPT_KEYWORDS):
            cmd = f"npm run {name}"
            if cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)

    for target in make_targets:
        if any(k in target.lower() for k in _SCRIPT_KEYWORDS):
            cmd = f"make {target}"
            if cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)

    for name in pyproject_scripts:
        if name.startswith("poe:"):
            cmd = f"poe {name.removeprefix('poe:')}"
        else:
            cmd = name
        if any(k in name.lower() for k in _SCRIPT_KEYWORDS) and cmd not in seen:
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
) -> str:
    lines: list[str] = []
    lines.append("# Execution Knowledge")
    lines.append("")
    lines.append("_Generated by 2repo from repository metadata (scripts, CI, migrations)._")
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
                    lines.append(f"  - `run: {cmd}`")
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
