#!/usr/bin/env python3
"""
2repo — generate a knowledge graph for any codebase using graphify.

Usage (via 2repo.sh alias):
  2repo .                      # graph for the current directory
  2repo /path/to/repo          # graph for a specific repo
  2repo . --update             # incremental update (re-extract changed files, no LLM)
  2repo . --wiki               # also generate wiki pages in the vault (see repo_wiki.py)
  2repo . --hook               # install graphify git post-commit hook
  2repo . --preset smart       # override AI preset

Outputs written to the target repo:
  graphify-out/GRAPH_REPORT.md  — knowledge graph (tool-agnostic)
  graphify-out/graph.json        — full graph data for downstream use
  .claude/KNOWLEDGE.md           — @../graphify-out/GRAPH_REPORT.md
  CLAUDE.md                      — injected @graphify-out/GRAPH_REPORT.md block

Wiki output (--wiki):
  vault/Projects/<repo-name>/   — Obsidian atomic pages (see repo_wiki.py)
  <repo>/wiki/                  — plain markdown clone (see repo_wiki.py)
"""
import argparse
import os
import re
import subprocess
import sys
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
    parser.add_argument("--hook", action="store_true",
                        help="Install graphify git post-commit hook in the target repo")
    parser.add_argument("--preset", metavar="NAME",
                        help="Override REPO_PRESET_GRAPH (e.g. smart, local, big)")
    parser.add_argument("-f", "--folder", default="Projects",
                        help="Vault folder for wiki output (default: Projects)")
    args = parser.parse_args()

    if not Path(args.repo).is_dir():
        die(f"not a directory: {args.repo}")

    if args.hook:
        result = subprocess.run(["graphify", "hook", "install"], cwd=args.repo)
        sys.exit(result.returncode)

    provider, model = _resolve_preset(args.preset)
    print(f"Provider : {provider}  |  Model: {model}")

    _run_graphify(args.repo, provider, model, update=args.update)
    _inject_claude(args.repo)

    if args.wiki:
        from repo_wiki import generate as wiki_generate
        wiki_generate(args.repo, folder=args.folder)


if __name__ == "__main__":
    main()
