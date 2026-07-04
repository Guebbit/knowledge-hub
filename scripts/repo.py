#!/usr/bin/env python3
"""
2repo — repository intelligence pipeline for any codebase.

Usage (via 2repo.sh alias):
  2repo .                       # full run (extract + execution + index + selected AI injection)
  2repo /path/to/repo           # full run for a specific repo
  2repo . --update              # incremental graphify update + orchestration
  2repo . --check               # staleness check vs last baseline
  2repo . --install-hook        # install stale-warning post-commit hook
  2repo . --query "how do I run tests?" --top-k 5
  2repo . --remember "Use pytest -q for unit tests" --memory-kind runbook
  2repo . --reindex             # rebuild semantic index + selected AI injection from existing artifacts
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
import repo_index
import repo_injection
import repo_memory
from repo_execution import generate as execution_generate
from utils import die


_BACKEND_MAP = {
    "anthropic": "claude",
    "openai": "openai",
    "ollama": "ollama",
}

_STATE_FILE_SUBPATH = Path("graphify-out/.2repo-state.json")
_STALE_EXCLUDES = [
    ":(exclude)graphify-out/**",
    ":(exclude).claude/**",
    ":(exclude).cursor/**",
    ":(exclude).github/copilot-instructions.md",
    ":(exclude)CLAUDE.md",
]
_PORCELAIN_STATUS_PREFIX_LENGTH = 3


_REQUIRED_PIPELINE_ARTIFACTS = (
    Path("graphify-out/GRAPH_REPORT.md"),
    Path("graphify-out/EXECUTION.md"),
)
_QUERY_EXCERPT_LENGTH = 320
_AI_TARGETS = ("claude", "copilot", "cursor", "neutral")
_AI_TARGET_PROMPT = (
    ("1", "claude", "Claude Code"),
    ("2", "copilot", "GitHub Copilot"),
    ("3", "cursor", "Cursor"),
    ("4", "neutral", "Neutral (local/custom setup, no editor file generation)"),
)


def _resolve_preset(name: str | None) -> tuple[str, str]:
    preset_name = (name or os.getenv("REPO_PRESET_GRAPH", "")).lower()
    if not preset_name:
        return config.PROVIDER, config.MODEL
    if preset_name not in config.PRESETS:
        die(f"preset '{preset_name}' not defined — add PRESET_{preset_name.upper()}=provider:model to .env")
    return config.PRESETS[preset_name]


def _run_graphify(repo_path: str, provider: str, model: str, update: bool) -> None:
    backend = _BACKEND_MAP.get(provider)
    if not backend:
        die(f"provider '{provider}' has no graphify backend — supported: {list(_BACKEND_MAP)}")

    if update:
        cmd = ["graphify", "update", "."]
    else:
        cmd = ["graphify", "extract", ".", "--backend", backend, "--model", model]
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


def _repo_state_file(repo_path: str) -> Path:
    return Path(repo_path) / _STATE_FILE_SUBPATH


def _hook_excludes_block() -> str:
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


def _resolve_head(repo_path: str) -> str:
    if not _in_git_repo(repo_path):
        return ""
    return _git_output(repo_path, ["rev-parse", "HEAD"]) or ""


def _resolve_threshold() -> int:
    try:
        return max(0, int(os.getenv("REPO_STALE_THRESHOLD", "5")))
    except ValueError:
        return 5


def _write_state(repo_path: str, *, pipeline: dict[str, object]) -> None:
    if not _in_git_repo(repo_path):
        print("Stale    : skipped state write (not a git repository)")
        return

    head = _resolve_head(repo_path)
    if not head:
        print("Stale    : skipped state write (cannot resolve HEAD)")
        return

    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head": head,
        "threshold": _resolve_threshold(),
        "layers": pipeline,
    }
    state_file = _repo_state_file(repo_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Stale    : state updated in {state_file}")


def _read_state(repo_path: str) -> dict[str, object] | None:
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
        or path.startswith(".cursor/")
        or path == "CLAUDE.md"
        or path == ".github/copilot-instructions.md"
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
            path = entry[_PORCELAIN_STATUS_PREFIX_LENGTH:] if len(entry) >= _PORCELAIN_STATUS_PREFIX_LENGTH else ""
            i += 1
            if code[0] in {"R", "C"} and i < len(entries):
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


def _require_pipeline_artifacts(repo_path: str) -> None:
    repo = Path(repo_path)
    for rel in _REQUIRED_PIPELINE_ARTIFACTS:
        path = repo / rel
        if not path.exists():
            die(f"required artifact missing: {path}")


def _build_layers(repo_path: str, *, provider: str, model: str, mode: str, ai_target: str) -> dict[str, object]:
    _require_pipeline_artifacts(repo_path)

    head = _resolve_head(repo_path)
    memory_report = repo_memory.write_memory_report(repo_path)
    runtime_metadata = {
        "provider": provider,
        "model": model,
        "mode": mode,
        "head": head,
    }

    index_meta = repo_index.build_index(repo_path, runtime_metadata=runtime_metadata)
    synced_entries = repo_memory.sync_entries(
        repo_path,
        head=head,
        index_revision=str(index_meta["revision"]),
    )

    context_path = repo_injection.write_repo_context(
        repo_path,
        provider=provider,
        model=model,
        index_revision=str(index_meta["revision"]),
        index_chunks=int(index_meta["chunk_count"]),
        memory_count=int(index_meta["memory_count"]),
    )
    injected_paths = repo_injection.inject_for_target(repo_path, ai_target=ai_target)

    print(f"Memory   : {memory_report}")
    print(f"Index    : {index_meta['index_path']}  (chunks={index_meta['chunk_count']})")
    print(f"Context  : {context_path}")
    for injected in injected_paths:
        print(f"Inject   : {injected}")
    if not injected_paths:
        print("Inject   : skipped (neutral target selected)")

    return {
        "execution": {
            "artifact": "graphify-out/EXECUTION.md",
        },
        "memory": {
            "artifact": "graphify-out/repo-memory.json",
            "report": "graphify-out/REPO_MEMORY.md",
            "synced_entries": synced_entries,
            "count": index_meta["memory_count"],
            "digest": index_meta["memory_digest"],
        },
        "index": {
            "artifact": "graphify-out/repo-index.json",
            "revision": index_meta["revision"],
            "chunk_count": index_meta["chunk_count"],
            "artifact_count": index_meta["artifact_count"],
            "artifact_digest": index_meta["artifact_digest"],
        },
        "context": {
            "artifact": "graphify-out/REPO_CONTEXT.md",
            "injected": injected_paths,
            "ai_target": ai_target,
            "provider": provider,
            "model": model,
            "mode": mode,
        },
    }


def _resolve_ai_target(cli_target: str | None = None) -> str:
    if cli_target:
        if cli_target not in _AI_TARGETS:
            die(f"invalid --ai-target '{cli_target}' (expected one of: {', '.join(_AI_TARGETS)})")
        return cli_target

    env_target = (os.getenv("REPO_AI_TARGET") or "").strip().lower()
    if env_target:
        if env_target not in _AI_TARGETS:
            die(f"invalid REPO_AI_TARGET '{env_target}' (expected one of: {', '.join(_AI_TARGETS)})")
        print(f"AI target: using REPO_AI_TARGET={env_target}")
        return env_target

    if not sys.stdin.isatty():
        print("AI target: non-interactive session detected, defaulting to neutral (set --ai-target or REPO_AI_TARGET to override)")
        return "neutral"

    print("AI target: select which integration files to generate")
    for key, value, label in _AI_TARGET_PROMPT:
        print(f"  {key}) {label} ({value})")
    max_option = len(_AI_TARGET_PROMPT)
    prompt = f"Select AI target (1-{max_option} or name): "

    while True:
        choice = input(prompt).strip().lower()
        for key, value, _ in _AI_TARGET_PROMPT:
            if choice == key or choice == value:
                return value
        print(f"Invalid selection. Choose 1-{max_option} or a target name.")


def _query(repo_path: str, query_text: str, top_k: int) -> int:
    try:
        results = repo_index.semantic_query(repo_path, text=query_text, top_k=top_k)
    except FileNotFoundError:
        die("semantic index not found — run 2repo first (or 2repo <repo> --reindex)")
    except ValueError as exc:
        die(str(exc))

    if not results:
        print("Query    : no matching context found")
        return 0

    print(f"Query    : {query_text}")
    for idx, item in enumerate(results, start=1):
        source = item.get("source")
        kind = item.get("kind")
        score = item.get("score")
        text = str(item.get("text") or "").replace("\n", " ").strip()
        excerpt = text[:_QUERY_EXCERPT_LENGTH] + ("..." if len(text) > _QUERY_EXCERPT_LENGTH else "")
        print(f"{idx}. [{kind}] {source} (score={score})")
        print(f"   {excerpt}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and query repository intelligence artifacts with 2repo"
    )
    parser.add_argument("repo", nargs="?", default="/target-repo", help="Path to the target repository (default: /target-repo)")
    parser.add_argument("--update", action="store_true", help="Incremental graph update (re-extract changed files only)")
    parser.add_argument("--check", action="store_true", help="Check if graph is stale based on changed files since last generation")
    parser.add_argument("--install-hook", action="store_true", help="Install a post-commit hook that warns when graph may be stale")
    parser.add_argument("--preset", metavar="NAME", help="Override REPO_PRESET_GRAPH (e.g. smart, local, big)")
    parser.add_argument("--query", metavar="TEXT", help="Run semantic retrieval over repo artifacts + repo memory")
    parser.add_argument("--top-k", type=int, default=5, metavar="N", help="Number of semantic query matches to return (default: 5)")
    parser.add_argument("--remember", metavar="TEXT", help="Persist a durable repository memory entry")
    parser.add_argument("--memory-kind", choices=["fact", "decision", "runbook"], default="fact", help="Memory type for --remember (default: fact)")
    parser.add_argument("--memory-source", default="manual", metavar="SOURCE", help="Memory source label for --remember (default: manual)")
    parser.add_argument("--reindex", action="store_true", help="Rebuild semantic index, context, and selected AI injection from existing artifacts")
    parser.add_argument("--ai-target", choices=_AI_TARGETS, help="Generate integration files only for one target: claude, copilot, cursor, or neutral")
    args = parser.parse_args()

    if not Path(args.repo).is_dir():
        die(f"not a directory: {args.repo}")

    mode_flags = {
        "--check": args.check,
        "--install-hook": args.install_hook,
        "--query": bool(args.query),
        "--remember": bool(args.remember),
        "--reindex": args.reindex,
    }
    if sum(bool(flag) for flag in mode_flags.values()) > 1:
        selected = ", ".join(name for name, enabled in mode_flags.items() if enabled)
        die(f"cannot combine exclusive mode flags: {selected}")

    if args.check:
        sys.exit(_check(args.repo))
    if args.install_hook:
        sys.exit(_install_hook(args.repo))
    if args.query:
        sys.exit(_query(args.repo, args.query, max(1, args.top_k)))

    provider, model = _resolve_preset(args.preset)
    ai_target = _resolve_ai_target(args.ai_target)
    print(f"Provider : {provider}  |  Model: {model}")
    print(f"AI target: {ai_target}")

    if args.remember:
        _require_pipeline_artifacts(args.repo)
        try:
            existing_revision = str(repo_index.load_index(args.repo).get("revision") or "")
        except (FileNotFoundError, ValueError):
            existing_revision = ""
        entry = repo_memory.add_entry(
            args.repo,
            text=args.remember,
            kind=args.memory_kind,
            source=args.memory_source,
            head=_resolve_head(args.repo),
            index_revision=existing_revision,
        )
        print(f"Memory   : stored [{entry['kind']}] {entry['text']}")
        layers = _build_layers(args.repo, provider=provider, model=model, mode="memory-update", ai_target=ai_target)
        _write_state(args.repo, pipeline=layers)
        return

    if args.reindex:
        _require_pipeline_artifacts(args.repo)
        layers = _build_layers(args.repo, provider=provider, model=model, mode="reindex", ai_target=ai_target)
        _write_state(args.repo, pipeline=layers)
        return

    _run_graphify(args.repo, provider, model, update=args.update)
    execution_generate(args.repo)
    layers = _build_layers(
        args.repo,
        provider=provider,
        model=model,
        mode="update" if args.update else "extract",
        ai_target=ai_target,
    )
    _write_state(args.repo, pipeline=layers)


if __name__ == "__main__":
    main()
