from __future__ import annotations

"""
Living wiki generator for 2repo (Karpathy / DeepWiki-style llm-wiki concept).

Turns the graphify dependency graph into readable per-file wiki pages plus a
top-level overview, written to <repo>/graphify-out/wiki/.

Incrementality is the core design:
- only changed files (git diff vs the .2repo-state.json baseline) are candidates
- the changed set is expanded to graph neighbors up to 2 hops
- a per-file content-hash cache skips pages whose source did not change

Page naming replaces `/` and `.` with `_` (e.g. src/auth/login.ts → src_auth_login_ts.md).
"""

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from providers import call_llm

_WIKI_SUBPATH = Path("graphify-out/wiki")
_CACHE_FILENAME = ".wiki-cache.json"
_OVERVIEW_FILENAME = "OVERVIEW.md"
_GRAPH_JSON_SUBPATH = Path("graphify-out/graph.json")

_NEIGHBOR_HOPS = 2
_MAX_FILE_CHARS = 12000
_MAX_NEIGHBORS_IN_PROMPT = 15
_MAX_OVERVIEW_FILES = 60

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


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def wiki_dir(repo_path: str) -> Path:
    """Return the wiki output directory for a repository."""
    return Path(repo_path) / _WIKI_SUBPATH


def _cache_file(repo_path: str) -> Path:
    return wiki_dir(repo_path) / _CACHE_FILENAME


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
    payload = {"version": 1, "updated_at": _now_iso(), "pages": pages}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def page_name_for(rel_path: str) -> str:
    """Return the wiki page filename for a source file (src/a.ts → src_a_ts.md)."""
    return rel_path.replace("/", "_").replace(".", "_") + ".md"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _node_path(node: object) -> str | None:
    """Extract a repo-relative file path from a graph node of unknown shape."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    for key in ("path", "file", "file_path", "filepath", "id", "name"):
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
    """Load graphify-out/graph.json → (file set, undirected adjacency map).

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
    raw_nodes = data.get("nodes") or data.get("files") or []
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            path = _node_path(node)
            if path:
                files.add(path.lstrip("./"))

    adjacency: dict[str, set[str]] = {}
    raw_edges = data.get("edges") or data.get("links") or data.get("relations") or []
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            endpoints = _edge_endpoints(edge)
            if not endpoints:
                continue
            src, dst = (endpoints[0].lstrip("./"), endpoints[1].lstrip("./"))
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


def _is_documentable(repo: Path, rel_path: str) -> bool:
    """Only document real repo files that are not generated artifacts."""
    if rel_path.startswith(("graphify-out/", ".git/", ".claude/", ".cursor/")):
        return False
    path = repo / rel_path
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return b"\0" not in handle.read(4096)
    except OSError:
        return False


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
    """Delete wiki pages whose source file no longer exists; return removed names."""
    out_dir = wiki_dir(repo_path)
    if not out_dir.exists():
        return []
    removed: list[str] = []
    keep = valid_pages | {_OVERVIEW_FILENAME}
    for page in out_dir.glob("*.md"):
        if page.name not in keep:
            page.unlink()
            removed.append(page.name)
    return removed


def _page_is_fresh(repo_path: str, rel_path: str, cached: dict[str, str], content_hash: str) -> bool:
    """A page is fresh when its cached source hash matches and the page file still exists."""
    return cached.get("hash") == content_hash and (wiki_dir(repo_path) / page_name_for(rel_path)).exists()


def generate(
    repo_path: str,
    *,
    changed_files: set[str] | None,
    force_all: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Generate/update the wiki incrementally and return a summary.

    changed_files=None means "no usable baseline" → consider every graph file
    (the hash cache still prevents regenerating unchanged pages).
    """
    repo = Path(repo_path)
    graph_files, adjacency = load_graph(repo_path)
    if not graph_files and not adjacency:
        raise FileNotFoundError(
            f"graph not found or empty: {repo / _GRAPH_JSON_SUBPATH} — run '2repo graph <repo>' first"
        )
    graph_files.update(adjacency)

    candidates = sorted(f for f in graph_files if _is_documentable(repo, f))
    if not candidates:
        raise ValueError("no documentable files found in the dependency graph")

    if force_all or changed_files is None:
        targets = set(candidates)
    else:
        seeds = changed_files & set(candidates)
        targets = expand_neighbors(seeds, adjacency) & set(candidates)

    cache = _load_cache(repo_path)
    plan: list[tuple[str, str]] = []  # (rel_path, content_hash)
    for rel_path in sorted(targets):
        content_hash = _hash_bytes((repo / rel_path).read_bytes())
        cached = cache.get(rel_path, {})
        if not force_all and _page_is_fresh(repo_path, rel_path, cached, content_hash):
            continue
        plan.append((rel_path, content_hash))

    valid_pages = {page_name_for(f) for f in candidates}

    if dry_run:
        for rel_path, _ in plan:
            print(f"Wiki     : would regenerate {page_name_for(rel_path)}  ({rel_path})")
        if not plan:
            print("Wiki     : nothing to regenerate (all pages fresh)")
        return {
            "artifact": str(_WIKI_SUBPATH),
            "dry_run": True,
            "planned": [rel for rel, _ in plan],
            "page_count": len(valid_pages),
        }

    out_dir = wiki_dir(repo_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for rel_path, content_hash in plan:
        neighbors = adjacency.get(rel_path, set())
        page = _generate_page(repo, rel_path, neighbors)
        page_file = out_dir / page_name_for(rel_path)
        page_file.write_text(page, encoding="utf-8")
        cache[rel_path] = {"hash": content_hash, "page": page_file.name, "generated_at": _now_iso()}
        written.append(page_file.name)
        print(f"Wiki     : wrote {page_file.name}  ({rel_path})")

    for stale in set(cache) - set(candidates):
        cache.pop(stale, None)
    removed = _prune_stale_pages(repo_path, valid_pages)
    for name in removed:
        print(f"Wiki     : pruned {name}")

    overview_path = out_dir / _OVERVIEW_FILENAME
    if written or removed or not overview_path.exists():
        overview_path.write_text(_generate_overview(candidates, adjacency), encoding="utf-8")
        print(f"Wiki     : wrote {_OVERVIEW_FILENAME}")

    _save_cache(repo_path, cache)
    if not written and not removed:
        print("Wiki     : nothing to regenerate (all pages fresh)")

    return {
        "artifact": str(_WIKI_SUBPATH),
        "dry_run": False,
        "written": written,
        "removed": removed,
        "page_count": len(list(out_dir.glob("*.md"))) - (1 if overview_path.exists() else 0),
    }


def _repo_display_name(repo_path: str) -> str:
    """Best-effort repository name: git origin basename, else directory name."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        name = result.stdout.strip().rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if name:
            return name
    return Path(repo_path).resolve().name


def mirror_to_vault(repo_path: str, vault_path: Path) -> Path:
    """Copy graphify-out/wiki into the Obsidian vault under Projects/<repo-name>/."""
    source = wiki_dir(repo_path)
    if not source.exists():
        raise FileNotFoundError(f"wiki not generated yet: {source}")
    destination = vault_path / "Projects" / _repo_display_name(repo_path)
    destination.mkdir(parents=True, exist_ok=True)
    for page in source.glob("*.md"):
        shutil.copy2(page, destination / page.name)
    return destination
