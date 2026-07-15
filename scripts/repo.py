#!/usr/bin/env python3
"""
2repo — repository intelligence pipeline for any codebase.

Usage (via 2repo.sh alias) — one subcommand per category:
  2repo .                                # full run (same as: 2repo graph .)
  2repo graph .                          # graph pipeline (extract + execution + index + AI injection)
  2repo graph . --update                 # incremental graphify update + orchestration
  2repo check .                          # staleness check vs last baseline
  2repo hook .                           # install stale-warning post-commit hook
  2repo query . "how do I run tests?" --top-k 5
  2repo remember . "Use pytest -q for unit tests" --kind runbook
  2repo reindex .                        # rebuild semantic index + selected AI injection from existing artifacts
  2repo wiki .                           # incremental LLM wiki (changed files + 2-hop graph neighbors)
  2repo wiki . src/auth.ts src/db.ts     # target specific files (+ their graph neighbors)
  2repo wiki . --force-all               # full wiki rebuild (ignore cache and baseline)
  2repo wiki . --dry-run                 # list pages that would be regenerated (no LLM calls)
  2repo wiki . --mirror-vault            # also mirror wiki pages into vault/Projects/<repo>/Generated
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from repo import index as repo_index
from repo import injection as repo_injection
from repo import memory as repo_memory
from repo import wiki as repo_wiki
from repo.execution import generate as execution_generate
from repo.injection import AI_TARGETS
from shared import config
from shared.config import GENERATED_DIR_PREFIXES, GENERATED_FILES
from shared.utils import die


_BACKEND_MAP = {
    "anthropic": "claude",
    "openai": "openai",
    # Routed to the custom "ollama-json" backend (graphify/providers.json)
    # instead of graphify's built-in "ollama" — it sets Ollama's enforced
    # format="json" so local models can't return prose instead of the
    # requested graph JSON (see graphify/providers.json for details).
    "ollama": "ollama-json",
    # Shells out to the `claude` CLI (see Dockerfile.scripts) instead of the
    # metered Anthropic API — uses the Claude Code subscription login
    # bind-mounted in docker-compose.yml. graphify's claude-cli backend
    # ignores the generic --model flag entirely; the model must be passed
    # via GRAPHIFY_CLAUDE_CLI_MODEL instead (see _run_graphify).
    "claude-code": "claude-cli",
}

_STATE_FILE_SUBPATH = Path("graphify-out/.2repo-state.json")
# git pathspecs that exclude 2repo's own generated output from staleness diffs,
# derived from the shared generated-path definitions in config.
_STALE_EXCLUDES = [
    *(f":(exclude){prefix}**" for prefix in GENERATED_DIR_PREFIXES),
    *(f":(exclude){name}" for name in GENERATED_FILES),
]
_PORCELAIN_STATUS_PREFIX_LENGTH = 3


_REQUIRED_PIPELINE_ARTIFACTS = (
    Path("graphify-out/GRAPH_REPORT.md"),
    Path("graphify-out/EXECUTION.md"),
)
_QUERY_EXCERPT_LENGTH = 320
_AI_TARGET_PROMPT = (
    ("1", "claude", "Claude Code"),
    ("2", "copilot", "GitHub Copilot"),
    ("3", "cursor", "Cursor"),
    ("4", "neutral", "Neutral (local/custom setup, no editor file generation)"),
)


def _resolve_preset(name: str | None, *, env_keys: tuple[str, ...] = ("REPO_PRESET_GRAPH",)) -> tuple[str, str]:
    """Resolve (provider, model) from --preset, then the first non-empty env var
    in env_keys, then the active default.

    The graph pipeline uses REPO_PRESET_GRAPH; wiki passes
    ("REPO_PRESET_WIKI", "REPO_PRESET_GRAPH") so it prefers a wiki-specific model
    but falls back to the graph preset.
    """
    preset_name = name or ""
    if not preset_name:
        for key in env_keys:
            preset_name = os.getenv(key, "")
            if preset_name:
                break
    preset_name = preset_name.lower()
    if not preset_name:
        return config.PROVIDER, config.MODEL
    if preset_name not in config.PRESETS:
        die(f"preset '{preset_name}' not defined — add PRESET_{preset_name.upper()}=provider:model to .env")
    return config.PRESETS[preset_name]


_HEARTBEAT_INTERVAL_SECONDS = 20


def _run_with_heartbeat(cmd: list[str], *, cwd: str, label: str, env: dict[str, str] | None = None) -> int:
    """Run cmd (inheriting stdio) while printing a periodic elapsed-time line.

    graphify's own progress output is chunky (per-100-files, per-LLM-chunk) and
    silent in between — a long local-inference run can look hung with nothing
    printed for minutes. This makes "still working" visible without touching
    graphify's stdout.
    """
    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env)
    stop = threading.Event()

    def _tick() -> None:
        while not stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
            elapsed = int(time.monotonic() - start)
            print(f"{label} : still running ({elapsed}s elapsed)...", flush=True)

    ticker = threading.Thread(target=_tick, daemon=True)
    ticker.start()
    try:
        return proc.wait()
    finally:
        stop.set()
        ticker.join()


def _run_graphify(repo_path: str, provider: str, model: str, update: bool) -> None:
    backend = _BACKEND_MAP.get(provider)
    if not backend:
        die(f"provider '{provider}' has no graphify backend — supported: {list(_BACKEND_MAP)}")

    env = None
    if provider == "claude-code":
        # graphify's claude-cli backend has no --model flag support; it only
        # reads GRAPHIFY_CLAUDE_CLI_MODEL. Without this, the preset's model
        # (e.g. "opus") is silently ignored and the CLI's own default is used.
        env = {**os.environ, "GRAPHIFY_CLAUDE_CLI_MODEL": model}

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
    returncode = _run_with_heartbeat(cmd, cwd=repo_path, label="Graphify", env=env)
    if returncode != 0:
        die(f"graphify exited with code {returncode}")

    if not update:
        # As of graphifyy 0.9.x, `extract` deliberately stops after writing
        # graph.json + the analysis sidecar — it no longer clusters, names
        # communities, or writes GRAPH_REPORT.md itself (that split shipped
        # without a matching major-version bump). `graphify update` still does
        # this inline (via _rebuild_code), so only the extract path needs the
        # follow-up call. Without this, GRAPH_REPORT.md never gets produced and
        # _require_pipeline_artifacts() below dies with a confusing "missing
        # artifact" error that looks unrelated to the dependency bump.
        cluster_cmd = ["graphify", "cluster-only", ".", "--backend", backend, "--model", model]
        if provider == "ollama":
            cluster_cmd.extend(["--max-concurrency", "1"])
        print(f"Graphify : cluster-only  backend={backend}  model={model}  (names communities, writes GRAPH_REPORT.md)")
        cluster_returncode = _run_with_heartbeat(cluster_cmd, cwd=repo_path, label="Cluster", env=env)
        if cluster_returncode != 0:
            die(f"graphify cluster-only exited with code {cluster_returncode}")


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
        print("Stale    : state not found — run '2repo graph <repo>' first")
        return None
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError:
        die(f"invalid state file: {state_file}")


def _is_generated_path(path: str) -> bool:
    return path.startswith(GENERATED_DIR_PREFIXES) or path in GENERATED_FILES


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
        die("'2repo hook' requires a git repository")

    hooks_dir = Path(repo_path) / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    threshold = _resolve_threshold()
    wiki_auto = "1" if (os.getenv("REPO_WIKI_AUTO") or "").strip() == "1" else "0"
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
  echo "Run: 2repo graph . --update   (or full run: 2repo graph .)" >&2
  echo "Wiki: 2repo wiki .            (incremental wiki refresh for changed files)" >&2
fi

# Auto-refresh the wiki when: enabled at hook-install time, something changed, and the 2repo alias exists.
if [[ "{wiki_auto}" == "1" && "${{changed}}" -gt 0 ]] && command -v 2repo >/dev/null 2>&1; then
  echo "2repo: refreshing wiki incrementally (REPO_WIKI_AUTO=1)..." >&2
  2repo wiki "${{repo_root}}" || echo "2repo: wiki refresh failed — run manually: 2repo wiki ." >&2
fi
"""
    hook_path.write_text(hook)
    hook_path.chmod(0o755)
    print(f"Hook     : installed stale-warning hook in {hook_path}")
    print(f"Hook     : threshold={threshold} (set REPO_STALE_THRESHOLD to change)")
    print(f"Hook     : wiki auto-refresh {'enabled' if wiki_auto == '1' else 'disabled'} (set REPO_WIKI_AUTO=1 before '2repo hook' to enable)")
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
        if cli_target not in AI_TARGETS:
            die(f"invalid --ai-target '{cli_target}' (expected one of: {', '.join(AI_TARGETS)})")
        return cli_target

    env_target = (os.getenv("REPO_AI_TARGET") or "").strip().lower()
    if env_target:
        if env_target not in AI_TARGETS:
            die(f"invalid REPO_AI_TARGET '{env_target}' (expected one of: {', '.join(AI_TARGETS)})")
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
        die("semantic index not found — run '2repo graph <repo>' first (or '2repo reindex <repo>')")
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


def _baseline_changed_files(repo_path: str) -> set[str] | None:
    """Return files changed since the .2repo-state.json baseline, or None if unusable."""
    if not _in_git_repo(repo_path):
        return None
    state = _read_state(repo_path)
    if not state:
        return None
    base_commit = str(state.get("head", "")).strip()
    if not base_commit:
        return None
    if _git_capture(repo_path, ["cat-file", "-e", f"{base_commit}^{{commit}}"]).returncode != 0:
        return None
    return _changed_files_since(repo_path, base_commit)


def _normalize_target_files(repo_path: str, files: list[str]) -> set[str]:
    """Resolve explicitly targeted wiki files to repo-relative paths, failing fast on bad input."""
    repo = Path(repo_path).resolve()
    normalized: set[str] = set()
    for raw in files:
        candidate = Path(raw)
        resolved = (candidate if candidate.is_absolute() else repo / candidate).resolve()
        try:
            rel = resolved.relative_to(repo)
        except ValueError:
            die(f"targeted file is outside the repository: {raw}")
        if not resolved.is_file():
            die(f"targeted file not found: {raw}")
        normalized.add(rel.as_posix())
    return normalized


def _wiki(
    repo_path: str,
    *,
    provider: str,
    model: str,
    ai_target: str,
    target_files: list[str] | None = None,
    force_all: bool,
    dry_run: bool,
    mirror_vault: bool,
) -> int:
    """Generate/update the living wiki, then refresh index + context so pages are retrievable."""
    if target_files:
        changed = _normalize_target_files(repo_path, target_files)
        print(f"Wiki     : targeting {len(changed)} explicit file(s) + graph neighbors")
    else:
        changed = None if force_all else _baseline_changed_files(repo_path)
        if changed is None and not force_all:
            print("Wiki     : no usable baseline — considering all graph files (hash cache still applies)")

    # providers.call_llm reads config.PROVIDER/config.MODEL at call time.
    config.PROVIDER = provider
    config.MODEL = model

    try:
        summary = repo_wiki.generate(
            repo_path,
            changed_files=changed,
            force_all=force_all,
            dry_run=dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        die(str(exc))

    if dry_run:
        return 0

    # Fold wiki pages into the semantic index and canonical context.
    # State is intentionally NOT rewritten: the graph baseline must only move
    # when graphify itself runs, otherwise --check would report a stale graph as fresh.
    _build_layers(repo_path, provider=provider, model=model, mode="wiki", ai_target=ai_target)

    if mirror_vault:
        try:
            destination = repo_wiki.mirror_to_vault(repo_path, config.VAULT_PATH)
        except FileNotFoundError as exc:
            die(str(exc))
        print(f"Wiki     : mirrored to {destination}")

    written = summary.get("written") or []
    removed = summary.get("removed") or []
    print(f"Wiki     : done ({len(written)} written, {len(removed)} pruned, {summary.get('page_count')} pages total)")
    return 0


_COMMANDS = ("graph", "check", "hook", "reindex", "query", "remember", "wiki")


def _with_default_command(argv: list[str]) -> list[str]:
    """Default to the 'graph' subcommand when none is given: '2repo .' → '2repo graph .'."""
    for arg in argv:
        if arg in ("-h", "--help"):
            return argv                       # let argparse print help
        if arg.startswith("-"):
            continue                          # skip leading options
        return argv if arg in _COMMANDS else ["graph", *argv]
    return ["graph", *argv]                   # empty / all-flags → still default to 'graph'


def _add_repo_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default="/target-repo", help="Path to the target repository (default: /target-repo)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="2repo",
        description="Generate and query repository intelligence artifacts with 2repo",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    graph_parser = subparsers.add_parser("graph", help="Build the full pipeline: graph + execution + memory + index + AI injection")
    _add_repo_argument(graph_parser)
    graph_parser.add_argument("--update", action="store_true", help="Incremental graph update (re-extract changed files only)")
    graph_parser.add_argument("--preset", metavar="NAME", help="Override REPO_PRESET_GRAPH (e.g. fast, deep)")
    graph_parser.add_argument("--ai-target", choices=AI_TARGETS, help="Generate integration files only for one target: claude, copilot, cursor, or neutral")

    check_parser = subparsers.add_parser("check", help="Check if the graph is stale based on changes since the last generation")
    _add_repo_argument(check_parser)

    hook_parser = subparsers.add_parser("hook", help="Install a post-commit hook that warns when the graph may be stale")
    _add_repo_argument(hook_parser)

    reindex_parser = subparsers.add_parser("reindex", help="Rebuild semantic index, context, and selected AI injection from existing artifacts")
    _add_repo_argument(reindex_parser)
    reindex_parser.add_argument("--preset", metavar="NAME", help="Override REPO_PRESET_GRAPH (e.g. fast, deep)")
    reindex_parser.add_argument("--ai-target", choices=AI_TARGETS, help="Generate integration files only for one target: claude, copilot, cursor, or neutral")

    query_parser = subparsers.add_parser("query", help="Run semantic retrieval over repo artifacts + repo memory")
    _add_repo_argument(query_parser)
    query_parser.add_argument("text", metavar="TEXT", help="Question to run against the semantic index")
    query_parser.add_argument("--top-k", type=int, default=5, metavar="N", help="Number of semantic query matches to return (default: 5)")

    remember_parser = subparsers.add_parser("remember", help="Persist a durable repository memory entry")
    _add_repo_argument(remember_parser)
    remember_parser.add_argument("text", metavar="TEXT", help="Memory entry to persist")
    remember_parser.add_argument("--kind", choices=["fact", "decision", "runbook"], default="fact", help="Memory type (default: fact)")
    remember_parser.add_argument("--source", default="manual", metavar="SOURCE", help="Memory source label (default: manual)")
    remember_parser.add_argument("--preset", metavar="NAME", help="Override REPO_PRESET_GRAPH (e.g. fast, deep)")
    remember_parser.add_argument("--ai-target", choices=AI_TARGETS, help="Generate integration files only for one target: claude, copilot, cursor, or neutral")

    wiki_parser = subparsers.add_parser("wiki", help="Generate/update the living wiki (graphify-out/wiki/) incrementally via LLM")
    _add_repo_argument(wiki_parser)
    wiki_parser.add_argument("files", nargs="*", metavar="FILE", help="Optional explicit files to regenerate (plus their graph neighbors)")
    wiki_parser.add_argument("--force-all", action="store_true", help="Full rebuild, ignoring cache and baseline")
    wiki_parser.add_argument("--dry-run", action="store_true", help="List pages that would regenerate, without calling the LLM")
    wiki_parser.add_argument("--mirror-vault", action="store_true", help="Mirror wiki pages into the Obsidian vault (Projects/<repo-name>/Generated)")
    wiki_parser.add_argument("--preset", metavar="NAME", help="Override REPO_PRESET_WIKI (e.g. fast, deep)")
    wiki_parser.add_argument("--ai-target", choices=AI_TARGETS, help="Generate integration files only for one target: claude, copilot, cursor, or neutral")

    args = parser.parse_args(_with_default_command(sys.argv[1:]))

    if not Path(args.repo).is_dir():
        die(f"not a directory: {args.repo}")

    if args.command == "check":
        sys.exit(_check(args.repo))
    if args.command == "hook":
        sys.exit(_install_hook(args.repo))
    if args.command == "query":
        sys.exit(_query(args.repo, args.text, max(1, args.top_k)))

    if args.command == "wiki":
        if args.files and args.force_all:
            die("cannot combine explicit FILE targets with --force-all")
        provider, model = _resolve_preset(args.preset, env_keys=("REPO_PRESET_WIKI", "REPO_PRESET_GRAPH"))
        ai_target = "neutral" if args.dry_run else _resolve_ai_target(args.ai_target)
        print(f"Provider : {provider}  |  Model: {model}")
        if not args.dry_run:
            print(f"AI target: {ai_target}")
        sys.exit(
            _wiki(
                args.repo,
                provider=provider,
                model=model,
                ai_target=ai_target,
                target_files=args.files,
                force_all=args.force_all,
                dry_run=args.dry_run,
                mirror_vault=args.mirror_vault,
            )
        )

    provider, model = _resolve_preset(args.preset)
    ai_target = _resolve_ai_target(args.ai_target)
    print(f"Provider : {provider}  |  Model: {model}")
    print(f"AI target: {ai_target}")

    if args.command == "remember":
        _require_pipeline_artifacts(args.repo)
        try:
            existing_revision = str(repo_index.load_index(args.repo).get("revision") or "")
        except (FileNotFoundError, ValueError):
            existing_revision = ""
        entry = repo_memory.add_entry(
            args.repo,
            text=args.text,
            kind=args.kind,
            source=args.source,
            head=_resolve_head(args.repo),
            index_revision=existing_revision,
        )
        print(f"Memory   : stored [{entry['kind']}] {entry['text']}")
        layers = _build_layers(args.repo, provider=provider, model=model, mode="memory-update", ai_target=ai_target)
        _write_state(args.repo, pipeline=layers)
        return

    if args.command == "reindex":
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
