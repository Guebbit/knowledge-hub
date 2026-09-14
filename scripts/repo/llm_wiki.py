"""
Living wiki generator for 2brain (Karpathy / DeepWiki-style llm-wiki concept).

Turns the graphify dependency graph into readable per-file wiki pages plus a
top-level overview, written to <repo>/<OUT_DIR>/llm-wiki/.

Incrementality is the core design:
- only changed files (git diff vs the .2brain-state.json baseline) are candidates
- the changed set is expanded to graph neighbors up to 2 hops
- a per-file content-hash cache skips pages whose source did not change

Pages mirror the source tree with `.md` appended (src/auth/login.ts →
llm-wiki/src/auth/login.ts.md), so the page path for a file is derivable
without knowing any naming rule and can never collide.

AUDIENCE: this tier is written for machines. One page per source file is the
right granularity for the semantic index and REPO_CONTEXT.md — an AI resolves a
question without opening the file — and the wrong granularity for a human, who
would face hundreds of near-identical notes. So per-file pages stay in the repo
and are never mirrored into the vault; repo/wiki.py builds the human-facing
tier on top of them. See docs/2brain-internals.md §8.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from repo.scope import Scope
from repo.vault import repo_display_name
from shared import config
from shared.config import GENERATED_DIR_PREFIXES
from shared.progress import Progress
from shared.providers import call_llm
from shared.utils import now_iso

_LLM_WIKI_SUBPATH = Path(config.OUT_DIR) / "llm-wiki"
_CACHE_FILENAME = ".llm-wiki-cache.json"
_OVERVIEW_FILENAME = "OVERVIEW.md"
# graph.json is graphify's own output, so it lives in the nested graphify dir.
_GRAPH_JSON_SUBPATH = Path(config.GRAPHIFY_OUT) / "graph.json"

_NEIGHBOR_HOPS = 2
_MAX_FILE_CHARS = 12000
_MAX_NEIGHBORS_IN_PROMPT = 15
_MAX_OVERVIEW_FILES = 60
# Files already written in the format a page would be written in. This tier
# exists to turn code into prose; run against prose it produces a paraphrase
# that is longer and less accurate than its input — on the 2026-09-13 run every
# such page came out *larger* than the file it described (docs/ollama.md:
# 2,208 -> 2,365 bytes). Worse, generated pages were the only route into the
# semantic index, so the paraphrase was searchable and the document was not.
# These files stay documented; index.py indexes them as themselves.
_PROSE_SUFFIXES = (".md", ".markdown", ".rst", ".txt")

_PAGE_PROMPT = """You are writing one page of a living wiki that documents a codebase for both humans and AI assistants.

Write a concise Markdown wiki page for the file `{rel_path}`.

Structure:
# {rel_path}
## Purpose — one short paragraph: what this file does and why it exists.
## Key elements — bullet list of the important functions/classes/exports and what each does.
## Relationships — how it interacts with its graph neighbors (listed below). Only mention real interactions.
## Notes — gotchas, conventions, or anything non-obvious. Omit this section if there is nothing meaningful.

Graph neighbors (files related via the dependency graph):
{neighbors}

File content:
```
{content}
```

Rules:
- Output ONLY the Markdown page, no preamble, no code fences around the whole page.
- Be factual: describe only what is visible in the content. Never invent behavior.
- Keep it short — this page is read to AVOID reading the file itself."""

_OVERVIEW_PROMPT = """You are writing the top-level overview page of a living wiki for a codebase.

Write a concise Markdown page titled "# Repository Overview" that orients a first-time reader (human or AI):
- What the repository appears to do (infer only from the evidence below).
- The main areas/modules and how they relate.
- Where to start reading.

Documented files (from the dependency graph):
{files}

Graph summary:
{graph_summary}

Rules:
- Output ONLY the Markdown page, no preamble.
- Be factual and short. Never invent features that are not evidenced."""


def llm_wiki_dir(repo_path: str) -> Path:
    """Return the llm-wiki output directory for a repository."""
    return Path(repo_path) / _LLM_WIKI_SUBPATH


def _cache_file(repo_path: str) -> Path:
    return llm_wiki_dir(repo_path) / _CACHE_FILENAME


def _load_cache(repo_path: str) -> dict[str, dict[str, str]]:
    """Load the per-file hash cache; tolerate a missing or corrupt file."""
    path = _cache_file(repo_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    pages = data.get("pages") if isinstance(data, dict) else None
    return pages if isinstance(pages, dict) else {}


def _save_cache(repo_path: str, pages: dict[str, dict[str, str]]) -> None:
    path = _cache_file(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "updated_at": now_iso(), "pages": pages}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def page_path_for(rel_path: str) -> str:
    """Return the page path for a source file, relative to the llm-wiki dir.

    The source tree is mirrored and `.md` appended (src/a.ts → src/a.ts.md).
    The previous scheme flattened separators (src/a.ts → src_a_ts.md), which
    was both lossy and ambiguous: `scripts/repo/wiki.py`, `scripts/repo_wiki.py`
    and `scripts/repo/wiki_py` all mapped onto the same file, so one silently
    overwrote the others. Mirroring borrows the filesystem's own uniqueness
    guarantee, and makes the mapping invertible (strip the `.md`) — an
    assistant that knows the source path knows the page path with no rule to
    look up, which is what gets this tier actually used.
    """
    return rel_path + ".md"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _node_path(node: object) -> str | None:
    """Extract a repo-relative file path from a graph node of unknown shape.

    `source_file` comes first: graphify 0.9.x emits symbol-level nodes whose
    `id` is a mangled slug ("husky_applypatch_msg"), not a path — trusting `id`
    there yields a file set that matches nothing on disk. `id`/`name` stay last
    for older graphs whose nodes carried the path in one of those keys.
    """
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    for key in ("source_file", "path", "file", "file_path", "filepath", "id", "name"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _node_id(node: object) -> str | None:
    """Extract the identifier that graph edges use to reference this node."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    for key in ("id", "name", "path", "file"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _edge_endpoints(edge: object) -> tuple[str, str] | None:
    """Extract (source, target) file identifiers from a graph edge of unknown shape."""
    if not isinstance(edge, dict):
        return None
    for src_key, dst_key in (("source", "target"), ("from", "to"), ("src", "dst")):
        src = edge.get(src_key)
        dst = edge.get(dst_key)
        if isinstance(src, str) and isinstance(dst, str) and src and dst:
            return src, dst
    return None


def load_graph(repo_path: str) -> tuple[set[str], dict[str, set[str]]]:
    """Load graphify's graph.json → (file set, undirected adjacency map).

    Parses defensively: node/edge key names vary across graphify versions.
    Returns empty structures when the graph file is missing or unreadable.
    """
    graph_path = Path(repo_path) / _GRAPH_JSON_SUBPATH
    if not graph_path.exists():
        return set(), {}
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return set(), {}
    if not isinstance(data, dict):
        return set(), {}

    files: set[str] = set()
    # Edges reference nodes by id, which is not the file path on symbol-level
    # graphs — keep the mapping so endpoints can be resolved back to files.
    path_by_id: dict[str, str] = {}
    raw_nodes = data.get("nodes") or data.get("files") or []
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            path = _node_path(node)
            if not path:
                continue
            path = path.lstrip("./")
            files.add(path)
            node_id = _node_id(node)
            if node_id:
                path_by_id[node_id] = path

    adjacency: dict[str, set[str]] = {}
    raw_edges = data.get("edges") or data.get("links") or data.get("relations") or []
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            endpoints = _edge_endpoints(edge)
            if not endpoints:
                continue
            src = path_by_id.get(endpoints[0], endpoints[0]).lstrip("./")
            dst = path_by_id.get(endpoints[1], endpoints[1]).lstrip("./")
            # Symbol-level graphs produce many intra-file edges; a file being its
            # own neighbor adds nothing to a wiki page's Relationships section.
            if src == dst:
                continue
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)
    return files, adjacency


def expand_neighbors(seeds: set[str], adjacency: dict[str, set[str]], hops: int = _NEIGHBOR_HOPS) -> set[str]:
    """Expand a file set to its graph neighbors up to `hops` hops (BFS)."""
    expanded = set(seeds)
    frontier = set(seeds)
    for _ in range(max(0, hops)):
        next_frontier: set[str] = set()
        for node in frontier:
            next_frontier.update(adjacency.get(node, set()) - expanded)
        if not next_frontier:
            break
        expanded.update(next_frontier)
        frontier = next_frontier
    return expanded


def is_documentable(repo: Path, rel_path: str, scope: Scope | None = None) -> bool:
    """Only document real, non-empty repo files in scope and not generated artifacts.

    Emptiness is judged on content, not size on disk: a file holding one newline
    is as empty as a zero-byte one. Deliberately *only* emptiness — a byte-size
    floor would also drop small-but-load-bearing files (a constants module, a
    tiny entry point), and size measures how much prose a model can write about
    a file, not how much the file matters. A file with no content cannot be
    described, so skipping it removes an LLM call and a page that would
    otherwise compete in retrieval saying nothing: the 2026-09-13 run generated
    877 bytes about an empty __init__.py, and that page then outranked the
    module that answered the query.
    """
    if scope is not None and not scope.matches(rel_path):
        return False
    # GENERATED_DIR_PREFIXES is the shared 2brain-generated set; .git/ is added
    # here because the wiki also must never document version-control internals.
    if rel_path.startswith(GENERATED_DIR_PREFIXES + (".git/",)):
        return False
    path = repo / rel_path
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(4096)
            if b"\0" in head:
                return False
            # A short read that is all whitespace can still precede content, so
            # only a file that ends within this read is safe to call empty.
            return bool(head.strip()) or path.stat().st_size > len(head)
    except OSError:
        return False


def is_prose(rel_path: str) -> bool:
    """True when a file is its own documentation and needs no generated page.

    Such files stay in `candidates` — they are documented, just not by a page —
    so they keep counting toward the module tier and reach the semantic index
    directly. Only page generation skips them.
    """
    return rel_path.lower().endswith(_PROSE_SUFFIXES)


def _read_truncated(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_FILE_CHARS:
        text = text[:_MAX_FILE_CHARS] + "\n... [truncated]"
    return text


def _generate_page(repo: Path, rel_path: str, neighbors: set[str]) -> str:
    """Ask the LLM for one wiki page and return its Markdown content."""
    neighbor_lines = "\n".join(f"- {n}" for n in sorted(neighbors)[:_MAX_NEIGHBORS_IN_PROMPT]) or "- (none)"
    prompt = _PAGE_PROMPT.format(
        rel_path=rel_path,
        neighbors=neighbor_lines,
        content=_read_truncated(repo / rel_path),
    )
    return call_llm(prompt).strip() + "\n"


def _generate_overview(files: list[str], adjacency: dict[str, set[str]]) -> str:
    """Ask the LLM for the top-level overview page."""
    listed = files[:_MAX_OVERVIEW_FILES]
    file_lines = "\n".join(f"- {f}" for f in listed)
    if len(files) > _MAX_OVERVIEW_FILES:
        file_lines += f"\n- ... and {len(files) - _MAX_OVERVIEW_FILES} more"
    hubs = sorted(adjacency, key=lambda node: len(adjacency[node]), reverse=True)[:10]
    graph_summary = "\n".join(f"- {node} connects to {len(adjacency[node])} files" for node in hubs) or "- (no edges)"
    prompt = _OVERVIEW_PROMPT.format(files=file_lines, graph_summary=graph_summary)
    return call_llm(prompt).strip() + "\n"


def _prune_stale_pages(repo_path: str, valid_pages: set[str]) -> list[str]:
    """Delete wiki pages whose source file no longer exists; return removed paths."""
    out_dir = llm_wiki_dir(repo_path)
    if not out_dir.exists():
        return []
    removed: list[str] = []
    keep = valid_pages | {_OVERVIEW_FILENAME}
    for page in out_dir.rglob("*.md"):
        rel = page.relative_to(out_dir).as_posix()
        if rel not in keep:
            page.unlink()
            removed.append(rel)
    # Mirroring the source tree means a deleted page can strand an empty
    # directory. Walk deepest-first so nested empties collapse in one pass.
    for directory in sorted((d for d in out_dir.rglob("*") if d.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return sorted(removed)


def _page_is_fresh(repo_path: str, rel_path: str, cached: dict[str, str], content_hash: str) -> bool:
    """A page is fresh when its cached source hash matches and the page file still exists."""
    return cached.get("hash") == content_hash and (llm_wiki_dir(repo_path) / page_path_for(rel_path)).exists()


def generate(
    repo_path: str,
    *,
    changed_files: set[str] | None,
    force_all: bool = False,
    dry_run: bool = False,
    scope: Scope | None = None,
) -> dict[str, object]:
    """Generate/update the wiki incrementally and return a summary.

    changed_files=None means "no usable baseline" → consider every graph file
    (the hash cache still prevents regenerating unchanged pages).
    """
    repo = Path(repo_path)
    graph_files, adjacency = load_graph(repo_path)
    if not graph_files and not adjacency:
        raise FileNotFoundError(
            f"graph not found or empty: {repo / _GRAPH_JSON_SUBPATH} — run '2brain graph <repo>' first"
        )
    graph_files.update(adjacency)

    candidates = sorted(f for f in graph_files if is_documentable(repo, f, scope))
    if not candidates:
        if scope is not None and not scope.is_empty:
            raise ValueError(
                f"no documentable files left after applying the scope ({scope.describe()}) — "
                f"widen it in {config.OUT_DIR}/../.2brainignore or re-run with --rescope"
            )
        raise ValueError("no documentable files found in the dependency graph")

    # Prose files are documented as themselves: they stay in `candidates` (so the
    # module tier still counts them and index.py still indexes them) but never
    # become a page, so they are subtracted here rather than above.
    page_candidates = [f for f in candidates if not is_prose(f)]

    if force_all or changed_files is None:
        targets = set(page_candidates)
    else:
        seeds = changed_files & set(candidates)
        targets = expand_neighbors(seeds, adjacency) & set(page_candidates)

    cache = _load_cache(repo_path)
    plan: list[tuple[str, str]] = []  # (rel_path, content_hash)
    for rel_path in sorted(targets):
        content_hash = _hash_bytes((repo / rel_path).read_bytes())
        cached = cache.get(rel_path, {})
        if not force_all and _page_is_fresh(repo_path, rel_path, cached, content_hash):
            continue
        plan.append((rel_path, content_hash))

    # Built from page_candidates, so a file that used to get a page and no longer
    # does (prose, or newly emptied) has its stale page pruned below.
    valid_pages = {page_path_for(f) for f in page_candidates}

    if dry_run:
        for rel_path, _ in plan:
            print(f"LLM Wiki : would regenerate {page_path_for(rel_path)}  ({rel_path})")
        if not plan:
            print("LLM Wiki : nothing to regenerate (all pages fresh)")
        return {
            "artifact": str(_LLM_WIKI_SUBPATH),
            "dry_run": True,
            "planned": [rel for rel, _ in plan],
            "page_count": len(valid_pages),
            "candidates": candidates,
            "adjacency": adjacency,
        }

    out_dir = llm_wiki_dir(repo_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    progress = Progress(len(plan), "LLM Wiki")
    for rel_path, content_hash in plan:
        neighbors = adjacency.get(rel_path, set())
        page = _generate_page(repo, rel_path, neighbors)
        page_rel = page_path_for(rel_path)
        page_file = out_dir / page_rel
        page_file.parent.mkdir(parents=True, exist_ok=True)
        page_file.write_text(page, encoding="utf-8")
        cache[rel_path] = {"hash": content_hash, "page": page_rel, "generated_at": now_iso()}
        # Persist after every page, not once at the end: a run interrupted at page
        # 300 of 430 must not throw away the 300 it already paid for.
        _save_cache(repo_path, cache)
        written.append(page_rel)
        progress.step(rel_path)

    for stale in set(cache) - set(page_candidates):
        cache.pop(stale, None)
    removed = _prune_stale_pages(repo_path, valid_pages)
    for name in removed:
        print(f"LLM Wiki : pruned {name}")

    overview_path = out_dir / _OVERVIEW_FILENAME
    if written or removed or not overview_path.exists():
        overview_path.write_text(_generate_overview(candidates, adjacency), encoding="utf-8")
        print(f"LLM Wiki : wrote {_OVERVIEW_FILENAME}")

    _save_cache(repo_path, cache)
    if not written and not removed:
        print("LLM Wiki : nothing to regenerate (all pages fresh)")

    return {
        "artifact": str(_LLM_WIKI_SUBPATH),
        "dry_run": False,
        "written": written,
        "removed": removed,
        "page_count": len(list(out_dir.rglob("*.md"))) - (1 if overview_path.exists() else 0),
        # Handed to the module tier so it can group the documented set and lift
        # the file-level dependency graph to module level.
        "candidates": candidates,
        "adjacency": adjacency,
    }


def read_pages(repo_path: str, candidates: list[str]) -> dict[str, str]:
    """Read what documents each candidate file, keyed by source path.

    The module tier summarises these instead of re-reading source, which is what
    keeps it ~25 LLM calls rather than one per file. Prose files have no
    generated page, so they contribute themselves — already the shape this
    wants, and one paraphrase closer to what the author actually wrote.
    Truncated to the same budget a page prompt uses, so a long README cannot
    crowd the rest of a module out of the prompt.
    """
    repo = Path(repo_path)
    out_dir = llm_wiki_dir(repo_path)
    pages: dict[str, str] = {}
    for rel_path in candidates:
        source = repo / rel_path
        if is_prose(rel_path):
            if source.is_file():
                pages[rel_path] = _read_truncated(source)
            continue
        page = out_dir / page_path_for(rel_path)
        if page.is_file():
            pages[rel_path] = page.read_text(encoding="utf-8", errors="replace")
    return pages


def prune_legacy_vault_mirror(repo_path: str, vault_path: Path) -> list[str]:
    """Remove the flat per-file page mirror written by earlier 2brain versions.

    Until the module tier existed, every per-file page was copied into
    Projects/<repo>/Generated/ — hundreds of machine-oriented notes sitting in a
    human vault, which is exactly what the module tier replaced. Nothing writes
    there any more, so anything still present is legacy output to clear out.
    Files under Generated/Modules/ and Generated/Architecture/ are untouched.
    """
    generated = vault_path / "Projects" / repo_display_name(repo_path) / "Generated"
    if not generated.is_dir():
        return []
    removed = []
    for page in generated.glob("*.md"):
        page.unlink()
        removed.append(page.name)
    return sorted(removed)
