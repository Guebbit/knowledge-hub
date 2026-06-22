#!/usr/bin/env python3
"""
2repo — generate a knowledge graph for any codebase using graphify.

Usage (via 2repo.sh alias):
  2repo .                      # graph for the current directory
  2repo /path/to/repo          # graph for a specific repo
  2repo . --update             # incremental update (re-extract changed files, no LLM)
  2repo . --wiki               # also generate wiki pages in the vault (see repo_wiki.py)
  2repo . --check              # check if graph may be stale
  2repo . --install-hook       # install a stale-warning post-commit hook
  2repo . --preset smart       # override AI preset

Outputs written to the target repo:
  graphify-out/GRAPH_REPORT.md  — knowledge graph (tool-agnostic)
  graphify-out/graph.json        — full graph data for downstream use
  .claude/KNOWLEDGE.md           — @../graphify-out/GRAPH_REPORT.md
  CLAUDE.md                      — injected @graphify-out/GRAPH_REPORT.md block

Wiki output (--wiki):
  graphify-out/wiki/             — graphify native wiki export
  graphify-out/obsidian/         — graphify native obsidian export
  <repo>/wiki/                   — plain markdown clone (from graphify-out/wiki)
  vault/Projects/<repo-name>/    — Obsidian clone (from graphify-out/obsidian)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from utils import die


# Our provider names → graphify --backend values
_BACKEND_MAP = {
    "anthropic": "claude",
    "openai":    "openai",
    "ollama":    "ollama",
}

_MARKER_START = "<!-- 2repo:start — regenerate with: 2repo . -->"
_MARKER_END   = "<!-- 2repo:end -->"
_INJECTION    = f"{_MARKER_START}\n@graphify-out/GRAPH_REPORT.md\n{_MARKER_END}"
_STATE_FILE_SUBPATH = Path("graphify-out/.2repo-state.json")
_STALE_EXCLUDES = [
    ":(exclude)graphify-out/**",
    ":(exclude).claude/**",
    ":(exclude)CLAUDE.md",
    ":(exclude)wiki/**",
]
_PORCELAIN_STATUS_AND_SPACE_LENGTH = 3


def _resolve_preset(name: str | None) -> tuple[str, str]:
    """Return (provider, model) from --preset flag or REPO_PRESET_GRAPH env var."""
    preset_name = (name or os.getenv("REPO_PRESET_GRAPH", "")).lower()
    if not preset_name:
        return config.PROVIDER, config.MODEL
    if preset_name not in config.PRESETS:
        die(f"preset '{preset_name}' not defined — add PRESET_{preset_name.upper()}=provider:model to .env")
    return config.PRESETS[preset_name]


def _run_graphify(repo_path: str, provider: str, model: str, update: bool) -> None:
    """Call graphify as a subprocess with the resolved backend.

    Uses `graphify update` for incremental runs (no LLM, AST only) and
    `graphify extract` for full extraction (AST + semantic LLM).
    """
    backend = _BACKEND_MAP.get(provider)
    if not backend:
        die(f"provider '{provider}' has no graphify backend — supported: {list(_BACKEND_MAP)}")

    if update:
        # Re-extract only changed files; no LLM call needed
        cmd = ["graphify", "update", "."]
    else:
        cmd = ["graphify", "extract", ".", "--backend", backend, "--model", model]
        # Local LLMs cannot process chunks in parallel
        if provider == "ollama":
            cmd.extend(["--max-concurrency", "1"])

    print(
        "Scan     : graphify honors .gitignore/.graphifyignore and skips common heavy dirs "
        "(node_modules, dist, build, .next, ...)."
    )
    print(f"Graphify : {'update' if update else 'extract'}  backend={backend}  model={model}")
    result = subprocess.run(cmd, cwd=repo_path)
    if result.returncode != 0:
        die(f"graphify exited with code {result.returncode}")


def _inject_claude(repo_path: str) -> None:
    """
    Write .claude/KNOWLEDGE.md (one-line @-pointer) and inject a reference block
    into CLAUDE.md so Claude Code auto-loads the knowledge graph.
    """
    repo = Path(repo_path)
    report = repo / "graphify-out" / "GRAPH_REPORT.md"
    if not report.exists():
        print(f"Warning  : {report} not found — skipping .claude/ injection")
        return

    # .claude/KNOWLEDGE.md — Claude Code auto-loads files in .claude/
    claude_dir = repo / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "KNOWLEDGE.md").write_text("@../graphify-out/GRAPH_REPORT.md\n")
    print(f"Pointer  : {claude_dir / 'KNOWLEDGE.md'}")

    # CLAUDE.md — inject or update the @-reference block
    claude_md = repo / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        if _MARKER_START in content:
            pattern = re.compile(
                re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END),
                re.DOTALL,
            )
            claude_md.write_text(pattern.sub(_INJECTION, content))
            print(f"CLAUDE.md: updated 2repo block in {claude_md}")
            return
        claude_md.write_text(content.rstrip() + "\n\n" + _INJECTION + "\n")
    else:
        claude_md.write_text(_INJECTION + "\n")
    print(f"CLAUDE.md: {claude_md}")


def _repo_state_file(repo_path: str) -> Path:
    return Path(repo_path) / _STATE_FILE_SUBPATH


def _hook_excludes_block() -> str:
    """Return shell lines for git pathspec excludes used in post-commit hook."""
    return "\n".join(f"  '{exclude}' \\" for exclude in _STALE_EXCLUDES)


def _git_capture(repo_path: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )


def _git_output(repo_path: str, args: list[str]) -> str | None:
    result = _git_capture(repo_path, args)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _in_git_repo(repo_path: str) -> bool:
    out = _git_output(repo_path, ["rev-parse", "--is-inside-work-tree"])
    return out == "true"


def _resolve_threshold() -> int:
    try:
        return max(0, int(os.getenv("REPO_STALE_THRESHOLD", "5")))
    except ValueError:
        return 5


def _write_state(repo_path: str) -> None:
    if not _in_git_repo(repo_path):
        print("Stale    : skipped state write (not a git repository)")
        return

    head = _git_output(repo_path, ["rev-parse", "HEAD"])
    if not head:
        print("Stale    : skipped state write (cannot resolve HEAD)")
        return

    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head": head,
        "threshold": _resolve_threshold(),
    }
    state_file = _repo_state_file(repo_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Stale    : state updated in {state_file}")


def _read_state(repo_path: str) -> dict[str, str | int] | None:
    state_file = _repo_state_file(repo_path)
    if not state_file.exists():
        print("Stale    : state not found — run 2repo first")
        return None
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError:
        die(f"invalid state file: {state_file}")


def _is_generated_path(path: str) -> bool:
    return (
        path.startswith("graphify-out/")
        or path.startswith(".claude/")
        or path.startswith("wiki/")
        or path == "CLAUDE.md"
    )


def _changed_files_since(repo_path: str, base_commit: str) -> set[str]:
    changed: set[str] = set()
    diff_out = _git_output(repo_path, ["diff", "--name-only", f"{base_commit}..HEAD", "--", *_STALE_EXCLUDES])
    if diff_out:
        changed.update(p for p in diff_out.splitlines() if p and not _is_generated_path(p))

    status = _git_capture(
        repo_path,
        ["status", "--porcelain", "-z", "--untracked-files=normal", "--", *_STALE_EXCLUDES],
    )
    if status.returncode == 0 and status.stdout:
        entries = status.stdout.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue
            code = entry[:2]
            path = entry[_PORCELAIN_STATUS_AND_SPACE_LENGTH:] if len(entry) >= _PORCELAIN_STATUS_AND_SPACE_LENGTH else ""
            i += 1
            # In -z mode, rename/copy stores old path in this entry and new path in the next one.
            if (code[0] in {"R", "C"} or code[1] in {"R", "C"}) and i < len(entries):
                path = entries[i]
                i += 1
            if path and not _is_generated_path(path):
                changed.add(path)
    return changed


def _check(repo_path: str) -> int:
    if not _in_git_repo(repo_path):
        die("--check requires a git repository")

    state = _read_state(repo_path)
    if not state:
        return 1

    base_commit = str(state.get("head", "")).strip()
    if not base_commit:
        die("state file missing 'head' commit")
    if _git_capture(repo_path, ["cat-file", "-e", f"{base_commit}^{{commit}}"]).returncode != 0:
        die(f"baseline commit not found: {base_commit}")

    threshold = _resolve_threshold()
    changed = _changed_files_since(repo_path, base_commit)
    changed_count = len(changed)
    stale = threshold > 0 and changed_count >= threshold
    status = "STALE" if stale else "fresh"
    print(f"Stale    : {status} ({changed_count} changed files, threshold={threshold})")
    if changed_count > 0:
        preview = ", ".join(sorted(changed)[:10])
        if changed_count > 10:
            preview += ", ..."
        print(f"Changed  : {preview}")
    return 2 if stale else 0


def _install_hook(repo_path: str) -> int:
    if not _in_git_repo(repo_path):
        die("--install-hook requires a git repository")

    hooks_dir = Path(repo_path) / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    threshold = _resolve_threshold()
    hook = f"""#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -z "${{repo_root}}" ]] && exit 0
state_file="${{repo_root}}/graphify-out/.2repo-state.json"
[[ ! -f "${{state_file}}" ]] && exit 0

base_commit="$(grep -Eo '"head"\\s*:\\s*"[^"]+"' "${{state_file}}" | head -n1 | sed -E 's/.*"([^"]+)"/\\1/')"
[[ -z "${{base_commit}}" ]] && exit 0
if ! git cat-file -e "${{base_commit}}^{{commit}}" 2>/dev/null; then
  exit 0
fi

changed="$(git diff --name-only "${{base_commit}}"..HEAD -- \\
{_hook_excludes_block()}
  | sed '/^$/d' | wc -l)"
threshold="{threshold}"

if [[ "${{threshold}}" -gt 0 && "${{changed}}" -ge "${{threshold}}" ]]; then
  echo "2repo warning: graph may be stale (${{changed}} files changed since last generation, threshold=${{threshold}})." >&2
  echo "Run: 2repo . --update   (or full run: 2repo .)" >&2
fi
"""
    hook_path.write_text(hook)
    hook_path.chmod(0o755)
    print(f"Hook     : installed stale-warning hook in {hook_path}")
    print(f"Hook     : threshold={threshold} (set REPO_STALE_THRESHOLD to change)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a knowledge graph for any codebase using graphify"
    )
    parser.add_argument("repo", nargs="?", default="/target-repo",
                        help="Path to the target repository (default: /target-repo)")
    parser.add_argument("--wiki", action="store_true",
                        help="Generate LLM wiki pages in the vault (see repo_wiki.py)")
    parser.add_argument("--update", action="store_true",
                        help="Incremental update — re-extract only changed files")
    parser.add_argument("--check", action="store_true",
                        help="Check if graph is stale based on changed files since last generation")
    parser.add_argument("--install-hook", action="store_true",
                        help="Install a post-commit hook that warns when graph may be stale")
    parser.add_argument("--preset", metavar="NAME",
                        help="Override REPO_PRESET_GRAPH (e.g. smart, local, big)")
    parser.add_argument("-f", "--folder", default="Projects",
                        help="Vault folder for wiki output (default: Projects)")
    args = parser.parse_args()

    if not Path(args.repo).is_dir():
        die(f"not a directory: {args.repo}")

    if args.check:
        sys.exit(_check(args.repo))
    if args.install_hook:
        sys.exit(_install_hook(args.repo))

    provider, model = _resolve_preset(args.preset)
    print(f"Provider : {provider}  |  Model: {model}")

    _run_graphify(args.repo, provider, model, update=args.update)
    _inject_claude(args.repo)

    if args.wiki:
        from repo_wiki import generate as wiki_generate
        wiki_generate(args.repo, folder=args.folder)

    _write_state(args.repo)


if __name__ == "__main__":
    main()
