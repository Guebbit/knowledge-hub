"""
Inject 2brain context into editor-specific instruction files.

This module writes/updates small "bridge" files (Claude, Copilot, Cursor) that
point to <OUT_DIR>/REPO_CONTEXT.md so assistants can ground responses in the
latest generated repository artifacts.

It also writes the repo-hygiene files that make the generated tree behave:
.gitattributes (so the committed artifacts read as generated in diffs), .gitignore
(so regeneration-only caches stay out of history) and — only when git's own ignore
rules do not already cover the generated directories — .graphifyignore, so graphify
never re-ingests our own Markdown as source.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from repo import memory as repo_memory
from repo.vault import repo_display_name
from shared import config

_MARKER_START = "<!-- 2brain:start — regenerate with: 2brain <repo-path> -->"
_MARKER_END = "<!-- 2brain:end -->"
_MARKER_PATTERN = re.compile(re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END), re.DOTALL)

# .graphifyignore and .gitattributes are line-oriented and treat <!-- --> as
# content, so the managed block there is delimited by # comments instead.
_HASH_MARKER_START = "# 2brain:start — regenerate with: 2brain <repo-path>"
_HASH_MARKER_END = "# 2brain:end"
_HASH_MARKER_PATTERN = re.compile(
    re.escape(_HASH_MARKER_START) + r".*?" + re.escape(_HASH_MARKER_END), re.DOTALL
)

_OUT = config.OUT_DIR
_PRIMARY_CONTEXT_PATH = f"{_OUT}/REPO_CONTEXT.md"

# Public: the canonical set of AI integration targets. repo.py imports this so
# the CLI choices and this module's validation share one definition.
AI_TARGETS = ("claude", "copilot", "cursor", "neutral")


def _probe_artifacts(repo: Path) -> list[tuple[str, str]]:
    """Return (path, description) for artifacts that exist AND carry real content.

    This is the single source both the editor-bridge instruction (_routing_rules)
    and REPO_CONTEXT.md's own listing (write_repo_context) read from, so the
    instruction that reaches an assistant can never name a different set than
    what write_repo_context actually describes — that drift (the richest
    artifacts appearing in the listing but never in the instruction) is what let
    llm-wiki go unadvertised. repo-index.json is deliberately never listed here:
    it is a query backend, not a document meant to be opened.
    """
    found: list[tuple[str, str]] = []

    graph_report = repo / config.GRAPHIFY_OUT / "GRAPH_REPORT.md"
    if graph_report.exists():
        found.append((str(graph_report.relative_to(repo)), "structural and semantic code graph report"))

    execution = repo / _OUT / "EXECUTION.md"
    if execution.exists():
        found.append((f"{_OUT}/EXECUTION.md", "runnable build/test/CI/migration knowledge"))

    # An empty "No memory entries recorded yet." report is worse than not
    # listing it: it sends a reader to open a file that tells them nothing.
    if repo_memory.load_entries(str(repo)):
        found.append((f"{_OUT}/REPO_MEMORY.md", "durable repository memory entries"))

    llm_wiki_dir = repo / _OUT / "llm-wiki"
    if llm_wiki_dir.is_dir() and any(llm_wiki_dir.rglob("*.md")):
        found.append((
            f"{_OUT}/llm-wiki/",
            "per-file machine-oriented pages, one per source file (page path = source path + `.md`)",
        ))

    modules_dir = repo / _OUT / "modules"
    if modules_dir.is_dir() and any(modules_dir.glob("*.md")):
        found.append((f"{_OUT}/modules/", "human-oriented module notes, mirrored into Obsidian"))

    arch_dir = repo / _OUT / "arch"
    if arch_dir.is_dir() and any(arch_dir.glob("*.md")):
        found.append((f"{_OUT}/arch/", "component/topic pages with Mermaid diagrams"))

    return found


def _freshness_note(head: str) -> str:
    """Per-file freshness rule, not a HEAD comparison.

    Committing the artifacts moves HEAD, so a HEAD-vs-stamp comparison would
    fire on every session after the first commit — always false, never useful.
    A diff of one file against the pinned baseline is exact regardless of how
    many artifact-only commits happened since, because it ignores them.
    """
    if not head:
        return ""
    return (
        f"Artifacts describe commit `{head}`. Before relying on a wiki page, check its "
        f"source: `git diff --quiet {head} -- <file>` (and `git status` for uncommitted "
        "edits). Changed → prefer the source for that file and say so. Unchanged → trust "
        "the page."
    )


def _routing_rules(repo: Path, *, head: str) -> str:
    """Trigger conditions, not a manifest — what a listing lacks is a reason to open it.

    Built from the same _probe_artifacts() probe REPO_CONTEXT.md uses, so a
    trigger is only emitted for an artifact that actually exists and has
    content: an unconditional list gives equal weight to a populated wiki and
    an empty memory report, which is what made the artifacts easy to ignore.
    """
    present = {path for path, _ in _probe_artifacts(repo)}
    rules: list[str] = []
    overview_path = f"{_OUT}/llm-wiki/OVERVIEW.md"
    module_index_path = f"{_OUT}/modules/{repo_display_name(str(repo))}_INDEX.md"
    if (repo / overview_path).exists() and (repo / module_index_path).exists():
        rules.append(
            "- **First contact with an unfamiliar codebase** → "
            f"`{overview_path}` for orientation, then `{module_index_path}` for the module map."
        )
    if any(path.startswith(f"{_OUT}/llm-wiki/") for path in present):
        rules.append(
            "- **Editing or reading a source file** → read "
            f"`{_OUT}/llm-wiki/<path>.md` first (page path = source path + `.md`). "
            "It carries the file's purpose, key elements, graph neighbours, and gotchas "
            "not in the source."
        )
    if any(path.startswith(f"{_OUT}/arch/") for path in present):
        rules.append(
            f'- **"How is this structured?" / "where does X live?"** → `{_OUT}/arch/overview.md`, '
            "then the component page it points to."
        )
    if f"{_OUT}/EXECUTION.md" in present:
        rules.append(f'- **"How do I run / build / test / deploy this?"** → `{_OUT}/EXECUTION.md`.')
    rules.append(
        '- **Anything else, or you don\'t know which file** → `2brain query <repo-path> "question"`.'
    )
    freshness = _freshness_note(head)
    if freshness:
        rules.append("")
        rules.append(freshness)
    return "\n".join(rules)


_MAX_INLINED_GOD_NODES = 10
_GOD_NODE_PATTERN = re.compile(r"^\d+\.\s+`([^`]+)`\s*-\s*(\d+)\s*edges?", re.MULTILINE)
_HYPEREDGE_TITLE_PATTERN = re.compile(r"^-\s+\*\*(.+?)\*\*\s+—", re.MULTILINE)


def _report_section(report_text: str, heading_prefix: str) -> str | None:
    """Body lines of the first '## <heading_prefix>...' section in report_text, or None."""
    lines = report_text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith(f"## {heading_prefix}")), None)
    if start is None:
        return None
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def _graph_report_highlights(repo: Path) -> str:
    """Inline GRAPH_REPORT.md's two durable-value sections into REPO_CONTEXT.md.

    GRAPH_REPORT is dropped from routing (its communities/questions are noise
    below graphify's own clustering threshold — see repo.py's
    _GRAPH_CLUSTER_MIN_NODES), but god nodes and hyperedges are worth a reader's
    attention regardless of graph size, so they are parsed out and inlined
    here. A missing report, or a missing section within it, silently omits
    that block rather than erroring — the report itself still exists and is
    still indexed by `query`.
    """
    report_path = repo / config.GRAPHIFY_OUT / "GRAPH_REPORT.md"
    if not report_path.exists():
        return ""
    text = report_path.read_text(encoding="utf-8", errors="replace")

    blocks: list[str] = []
    god_nodes = _report_section(text, "God Nodes")
    if god_nodes:
        matches = _GOD_NODE_PATTERN.findall(god_nodes)[:_MAX_INLINED_GOD_NODES]
        if matches:
            blocks.append("## Most-used code")
            blocks.append("Change these with care — widely depended on:")
            blocks.extend(f"- `{name}` ({edges} edges)" for name, edges in matches)

    hyperedges = _report_section(text, "Hyperedges")
    if hyperedges:
        titles = _HYPEREDGE_TITLE_PATTERN.findall(hyperedges)
        if titles:
            if blocks:
                blocks.append("")
            blocks.append("## Cross-cutting flows")
            blocks.extend(f"- {title}" for title in titles)

    return "\n".join(blocks)


def _claude_inline(repo: Path, *, head: str) -> str:
    """Managed CLAUDE.md block: an @-import only.

    Claude Code auto-loads CLAUDE.md and resolves @-imports, so the import
    alone puts REPO_CONTEXT.md — including its own "## Where to look" section —
    in context. Repeating the routing rules here would just be the same text
    read twice. Copilot and Cursor cannot import, so _copilot_inline and
    _cursor_rule keep them inline.
    """
    del repo, head  # unused: no inline routing rules to build here, unlike the other targets
    return (
        f"{_MARKER_START}\n"
        "Use the repository context generated by 2brain before proposing changes.\n"
        f"@{_PRIMARY_CONTEXT_PATH}\n"
        f"{_MARKER_END}"
    )


def _copilot_inline(repo: Path, *, head: str) -> str:
    return (
        f"{_MARKER_START}\n"
        "Use the repository context generated by 2brain before proposing changes.\n"
        f"Primary context: `{_PRIMARY_CONTEXT_PATH}`\n\n"
        "## Where to look\n\n"
        f"{_routing_rules(repo, head=head)}\n"
        f"{_MARKER_END}"
    )


def _cursor_rule(repo: Path, *, head: str) -> str:
    lines = [
        "---",
        "description: 2brain repository context",
        'globs: ["**/*"]',
        "alwaysApply: true",
        "---",
        "",
        "# Intentional: repository context must be applied globally for consistent sessions.",
        f"Use `{_PRIMARY_CONTEXT_PATH}` as the primary repository context.",
        "",
        "## Where to look",
        "",
        _routing_rules(repo, head=head),
        "",
    ]
    return "\n".join(lines)


def _write_if_changed(path: Path, *, content: str) -> bool:
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return False
        path.write_text(content, encoding="utf-8")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _replace_or_append(
    path: Path,
    *,
    block: str,
    marker_start: str = _MARKER_START,
    pattern: re.Pattern[str] = _MARKER_PATTERN,
) -> bool:
    """Replace the managed marker block in a file, or append/create it if missing."""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if marker_start in content:
            updated = pattern.sub(block, content)
            return _write_if_changed(path, content=updated)
        updated = content.rstrip() + "\n\n" + block + "\n"
        return _write_if_changed(path, content=updated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(block + "\n", encoding="utf-8")
    return True


def _git_ignores(repo: Path, relative_path: str) -> bool:
    """True when git's exclude rules already cover `relative_path`.

    `--no-index` asks purely about the ignore rules, ignoring whether the path
    happens to be tracked — which is the same question graphify asks when it
    reads .gitignore. Anything git cannot answer (no git, no repository) counts
    as "not ignored", so the exclusion is written explicitly rather than assumed.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _graphifyignore_dirs(repo: Path) -> tuple[str, ...]:
    """The generated dirs that actually need a .graphifyignore entry, if any.

    graphify prunes exactly one directory on its own: the one it writes to,
    matched by basename(GRAPHIFY_OUT). Everything generated outside it —
    2brain's wiki/, arch/ and EXECUTION.md, CodeBoarding's working dir — is
    ordinary Markdown as far as graphify is concerned, and would be extracted
    back into the graph on the next run, feeding generated prose into the next
    generation of generated prose.

    But graphify's scan honours .gitignore too, so a directory git already
    excludes needs no second listing: .codeboarding/ sits in our own managed
    .gitignore block, and a repo that chooses not to commit OUT_DIR gitignores
    that as well. Whatever survives this filter is the only reason
    .graphifyignore exists — when nothing survives, the file is not written.
    """
    return tuple(
        name for name in config.GRAPHIFY_IGNORE_DIRS if not _git_ignores(repo, f"{name}/")
    )


def _graphifyignore_block(dirs: tuple[str, ...]) -> str:
    """Managed .graphifyignore block keeping generated docs out of the graph.

    The header explains the file to whoever opens it next: .graphifyignore is
    graphify's own, and a target repo has no other record of where it came from
    or why deleting it would quietly poison the next graph.
    """
    lines = [
        _HASH_MARKER_START,
        "# .graphifyignore — graphify's scan-exclusion list: gitignore syntax, one",
        "# pattern per line, read alongside .gitignore to decide which files get",
        "# extracted into the code graph.",
        "#",
        "# The directories below hold 2brain's own generated documentation. They are",
        "# not gitignored (they are committed on purpose), so without this file",
        "# graphify would extract generated prose back into the next graph.",
        *(f"{name}/" for name in dirs),
        _HASH_MARKER_END,
    ]
    return "\n".join(lines)


def _gitattributes_block() -> str:
    """Managed .gitattributes block marking the generated tree as generated.

    The artifacts are meant to be committed (regenerating them costs real LLM
    tokens, and the incremental caches that keep re-runs cheap live in the same
    tree), so they show up in every diff. linguist-generated collapses them in
    GitHub reviews. Deliberately NOT '-diff': that suppresses the textual diff
    everywhere, including local `git diff` when you actually want to look.
    """
    return "\n".join([
        _HASH_MARKER_START,
        f"{_OUT}/** linguist-generated=true",
        _HASH_MARKER_END,
    ])


def _gitignore_block() -> str:
    """Managed .gitignore block excluding regeneration-only caches and duplicates.

    Deliberately narrow: llm-wiki/, modules/, arch/, EXECUTION.md, REPO_MEMORY.md
    and REPO_CONTEXT.md are committed on purpose (regenerating them costs real
    LLM time/tokens, or needs 2brain/graphify installed — a teammate without
    that tooling or a capable machine should still be able to read them).
    Everything listed here either only speeds up a *future* regeneration and has
    zero value to a reader, or is cheap enough to rebuild that committing it
    costs more than it saves:
      - graphify's raw graph.json/manifest.json/.graphify_* dumps — structural
        data, not prose (see index.py's _artifact_files for why these are also
        excluded from the semantic index, not just git)
      - graphify's own incremental AST/semantic cache
      - graphify's dated snapshot directories, which duplicate its live output
      - graphify's interactive graph.html viewer: ~750 KB of vis-network markup
        that no assistant can read and a browser can only render with network
        access (it loads the library from a CDN). A human who wants to browse
        the structure visually already has the module tier in Obsidian, whose
        graph view works offline and at a granularity worth looking at.
      - the module tier's incremental content-hash cache (the llm-wiki tier
        keeps its hashes in each page's own frontmatter, so it has no sidecar)
      - CodeBoarding's native working dir (.codeboarding/): its committed,
        canonical copy already lives in <OUT_DIR>/arch/
      - repo-index.json — the one artifact that is derived rather than written.
        It is rewritten whole on every run (IDF is global, so one new file
        shifts every weight and it never delta-compresses) and it grows with the
        corpus: ~1 MB here, but ~60 MB at 3 000 files and ~200 MB at 10 000, a
        fresh blob per run, permanently. The usual argument for committing —
        that rebuilding costs LLM time — does not apply: `2brain reindex` makes
        no model calls at all, just stdlib over the artifacts that *are*
        committed, so a teammate rebuilds it in seconds with no GPU or API key.
        `2brain query` already says so when it is missing (repo.py:620).
    """
    graphify_out = config.GRAPHIFY_OUT
    return "\n".join([
        _HASH_MARKER_START,
        f"{graphify_out}/cache/",
        f"{graphify_out}/graph.json",
        f"{graphify_out}/manifest.json",
        f"{graphify_out}/.graphify_analysis.json",
        f"{graphify_out}/.graphify_labels.json*",
        f"{graphify_out}/graph.html",
        f"{graphify_out}/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/",
        f"{_OUT}/modules/.modules-cache.json",
        f"{_OUT}/repo-index.json",
        ".codeboarding/",
        _HASH_MARKER_END,
    ])


def _remove_managed_block(path: Path) -> bool:
    """Drop our managed block from `path`; delete the file if nothing else remains."""
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if _HASH_MARKER_START not in content:
        return False
    remainder = _HASH_MARKER_PATTERN.sub("", content).strip()
    if remainder:
        path.write_text(remainder + "\n", encoding="utf-8")
    else:
        path.unlink()
    return True


def _write_repo_hygiene(repo: Path) -> list[str]:
    """Write the ignore/attribute files the generated tree needs, in any AI target."""
    outputs: list[str] = []
    # .gitignore goes first: _graphifyignore_dirs() asks git what it already
    # excludes, and the answer must include the block we are writing this run.
    for filename, block in (
        (".gitattributes", _gitattributes_block()),
        (".gitignore", _gitignore_block()),
    ):
        path = repo / filename
        if _replace_or_append(
            path,
            block=block,
            marker_start=_HASH_MARKER_START,
            pattern=_HASH_MARKER_PATTERN,
        ):
            outputs.append(str(path))

    graphifyignore = repo / ".graphifyignore"
    dirs = _graphifyignore_dirs(repo)
    if dirs:
        if _replace_or_append(
            graphifyignore,
            block=_graphifyignore_block(dirs),
            marker_start=_HASH_MARKER_START,
            pattern=_HASH_MARKER_PATTERN,
        ):
            outputs.append(str(graphifyignore))
    # Nothing left to exclude: a file we wrote on an earlier run is now noise,
    # and leaving a stale block behind would outlive the reason for it.
    elif _remove_managed_block(graphifyignore):
        outputs.append(str(graphifyignore))
    return outputs


def _inject_claude(repo: Path, *, head: str) -> list[str]:
    claude_md = repo / "CLAUDE.md"
    return [str(claude_md)] if _replace_or_append(claude_md, block=_claude_inline(repo, head=head)) else []


def _inject_copilot(repo: Path, *, head: str) -> list[str]:
    copilot = repo / ".github" / "copilot-instructions.md"
    return [str(copilot)] if _replace_or_append(copilot, block=_copilot_inline(repo, head=head)) else []


def _inject_cursor(repo: Path, *, head: str) -> list[str]:
    cursor_rule = repo / ".cursor" / "rules" / "2brain.mdc"
    return [str(cursor_rule)] if _write_if_changed(cursor_rule, content=_cursor_rule(repo, head=head)) else []


def _inject_neutral(_repo: Path, *, head: str) -> list[str]:
    return []


_TARGET_WRITERS: dict[str, Callable[..., list[str]]] = {
    "claude": _inject_claude,
    "copilot": _inject_copilot,
    "cursor": _inject_cursor,
    "neutral": _inject_neutral,
}


def inject_for_target(repo_path: str, *, ai_target: str, head: str = "") -> list[str]:
    """Write integration files for one AI target and return created/updated paths."""
    repo = Path(repo_path)
    context = repo / _OUT / "REPO_CONTEXT.md"
    if not context.exists():
        raise FileNotFoundError(f"required context artifact missing: {context}")
    if ai_target not in AI_TARGETS:
        raise ValueError(f"invalid ai target '{ai_target}' (expected one of: {', '.join(AI_TARGETS)})")

    # Hygiene files are about the generated tree itself, not the assistant, so
    # they are written even for the neutral target.
    return _write_repo_hygiene(repo) + _TARGET_WRITERS[ai_target](repo, head=head)


def write_repo_context(
    repo_path: str,
    *,
    provider: str,
    model: str,
    index_revision: str,
    index_chunks: int,
    memory_count: int,
    head: str = "",
) -> Path:
    """Build <OUT_DIR>/REPO_CONTEXT.md summarizing canonical 2brain artifacts."""
    repo = Path(repo_path)
    out = repo / _OUT / "REPO_CONTEXT.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Repo Context")
    lines.append("")
    lines.append("_Canonical 2brain context source for AI editors._")
    lines.append("")
    lines.append("## Core Artifacts")
    for artifact_path, description in _probe_artifacts(repo):
        lines.append(f"- `{artifact_path}` — {description}")
    lines.append(
        f"- `{_OUT}/repo-index.json` — semantic retrieval index backing "
        '`2brain query` (a query backend, not a document to open directly)'
    )
    lines.append("")
    lines.append("## Where to look")
    lines.append("")
    lines.append(_routing_rules(repo, head=head))
    lines.append("")
    highlights = _graph_report_highlights(repo)
    if highlights:
        lines.append(highlights)
        lines.append("")
    lines.append("## Index Metadata")
    lines.append(f"- Provider: `{provider}`")
    lines.append(f"- Model: `{model}`")
    lines.append(f"- Index revision: `{index_revision}`")
    lines.append(f"- Indexed chunks: `{index_chunks}`")
    lines.append(f"- Memory entries: `{memory_count}`")
    lines.append("")
    lines.append("## Query")
    lines.append("- Semantic query: `2brain query <repo-path> \"your question\" --top-k 5`")
    lines.append("- Add durable memory: `2brain remember <repo-path> \"fact/decision/runbook\" --kind fact`")
    lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
