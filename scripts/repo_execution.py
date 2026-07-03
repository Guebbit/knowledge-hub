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
    return {k: str(v) for k, v in scripts.items() if isinstance(k, str)}


def _read_make_targets(path: Path) -> list[str]:
    if not path.exists():
        return []
    targets: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(errors="replace").splitlines():
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
        scripts.update({k: str(v) for k, v in project_scripts.items() if isinstance(k, str)})

    poetry_scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
    if isinstance(poetry_scripts, dict):
        for k, v in poetry_scripts.items():
            if isinstance(k, str):
                scripts[k] = str(v)

    poe_tasks = data.get("tool", {}).get("poe", {}).get("tasks", {})
    if isinstance(poe_tasks, dict):
        for k, v in poe_tasks.items():
            if isinstance(k, str):
                scripts[f"poe:{k}"] = str(v)
    return scripts


def _read_workflows(dir_path: Path) -> list[dict[str, object]]:
    if not dir_path.exists():
        return []

    workflows: list[dict[str, object]] = []
    for wf in sorted(list(dir_path.glob("*.yml")) + list(dir_path.glob("*.yaml"))):
        lines = wf.read_text(errors="replace").splitlines()
        name = None
        run_commands: list[str] = []
        for line in lines:
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
                "run_commands": run_commands[:12],
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
            if len(migration_paths) >= 20:
                break
        if len(migration_paths) >= 20:
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
    return commands[:20]


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
            label = wf.get("name") or wf["file"]
            lines.append(f"- `{wf['file']}` — {label}")
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
