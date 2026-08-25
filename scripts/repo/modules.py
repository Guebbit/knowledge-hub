"""
Module tier for 2repo — the human-facing layer between per-file pages and the
whole-architecture view.

WHY THIS EXISTS
───────────────────────────────────────────────────────────────────────────────
The per-file wiki (repo/wiki.py) is written for machines: one page per source
file, hundreds of them, consumed through the semantic index and REPO_CONTEXT.md
so an AI never has to open the file itself. Mirrored into an Obsidian vault it
is unreadable — a thousand disconnected nodes that bury hand-written notes.

Every mature tool in this space solves that the same way: document *units of
meaning*, not files. DeepWiki emits a few dozen topic pages; CodeBoarding (our
arch layer) emits component pages. Obsidian practice calls the same shape a Map
of Content — hub notes that index a domain so the graph reads as hubs and spokes
instead of a hairball.

This module is that tier: one note per meaningful directory, linked to the other
modules it actually depends on (edges taken from the real dependency graph), plus
an INDEX hub linking to all of them. Roughly 20–30 notes for a large repo instead
of 900, and they are the only wiki-side artifacts mirrored into the vault.

COST
───────────────────────────────────────────────────────────────────────────────
Module notes are written from the *already generated* per-file page summaries,
not from source, so a full module tier is ~25 LLM calls rather than ~900. A
content hash over each module's member pages keeps re-runs free when nothing in
the module changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from repo.vault import mirror_markdown_tree, repo_display_name
from shared import config
from shared.progress import Progress
from shared.providers import call_llm
from shared.utils import now_iso

_MODULES_SUBPATH = Path(config.OUT_DIR) / "modules"
_CACHE_FILENAME = ".modules-cache.json"
_INDEX_FILENAME = "INDEX.md"
_ROOT_MODULE = ""
_ROOT_PAGE_NAME = "ROOT"

# Splitting thresholds. A directory becomes its own module when its subtree holds
# at most _MAX_FILES_PER_MODULE files; bigger subtrees are split into their
# children. _MAX_MODULES then merges the smallest modules upward so the vault
# graph stays legible — past ~30 hubs the picture stops being readable, which is
# the whole problem this tier exists to solve.
_MAX_FILES_PER_MODULE = 40
_MAX_MODULES = 30
_MAX_FILES_IN_PROMPT = 40
_MAX_LINKS_IN_NOTE = 15
# Edge budget for the INDEX diagram. A module graph can in principle hold
# n(n-1)/2 edges (435 at 30 modules); past roughly this many the picture stops
# being a map and becomes the hairball this tier exists to avoid, so the least
# structurally interesting edges are dropped and the diagram says so.
_MAX_DIAGRAM_EDGES = 70

_MODULE_PROMPT = """You are writing one page of a codebase wiki, at the level of a module (a directory), not a single file.

Write a concise Markdown page for the module `{module}`.

Structure:
## Purpose — one short paragraph: what this module is responsible for.
## Key parts — bullet list of the most important files/areas inside it and what each contributes. Group related files rather than listing every one.
## How it connects — how this module relates to the modules listed as dependencies below. Only describe real relationships.
## Where to start — one or two files a newcomer should read first, and why.

Files in this module (with their documented purpose):
{files}

Modules this one is connected to in the dependency graph:
{links}

Rules:
- Output ONLY the Markdown page body, starting at "## Purpose". No title heading, no preamble, no code fences around the whole page.
- Be factual: describe only what the evidence below supports. Never invent behavior.
- Aim for something a newcomer reads in under a minute."""

_INDEX_PROMPT = """You are writing the landing page of a codebase wiki.

Write a short Markdown introduction (2-4 sentences, no heading) for the repository `{repo}`, orienting a first-time reader: what it appears to be, and how its modules are organized.

Modules:
{modules}

Rules:
- Output ONLY the prose. No heading, no bullet list, no preamble.
- Be factual and brief. Never invent features the module names do not support."""


def modules_dir(repo_path: str) -> Path:
    return Path(repo_path) / _MODULES_SUBPATH


def _cache_file(repo_path: str) -> Path:
    return modules_dir(repo_path) / _CACHE_FILENAME


def page_name_for(module: str, repo_name: str) -> str:
    """Return the note filename for a module path (src/auth → <repo>_src_auth.md).

    The repo name is part of the filename because the vault is shared across
    projects: without it, two repos that both have `src/ui/` produce two
    `src_ui.md` notes, and an Obsidian wikilink between them would be ambiguous —
    silently welding two project graphs together, which is exactly the mess this
    tier exists to prevent. Obsidian resolves `[[...]]` by filename across the
    whole vault, so uniqueness has to be in the name itself.

    Never collides with a per-file wiki page either: those always end in the
    file's extension (`src/auth.ts` → `src_auth_ts.md`).
    """
    leaf = _ROOT_PAGE_NAME if module == _ROOT_MODULE else module.replace("/", "_")
    return f"{repo_name}_{leaf}.md"


def index_name_for(repo_name: str) -> str:
    """Return the hub note filename for a repository (namespaced, same as modules)."""
    return f"{repo_name}_{_INDEX_FILENAME}"


def module_title(module: str) -> str:
    return "/ (repository root)" if module == _ROOT_MODULE else module + "/"


def _parent(directory: str) -> str:
    return directory.rpartition("/")[0] if "/" in directory else _ROOT_MODULE


def _directory_of(rel_path: str) -> str:
    return rel_path.rpartition("/")[0] if "/" in rel_path else _ROOT_MODULE


def select_modules(files: list[str]) -> dict[str, list[str]]:
    """Group files into modules by directory, splitting big trees and merging small ones.

    Top-down: a directory whose whole subtree fits in _MAX_FILES_PER_MODULE
    becomes one module; anything larger is split into its children, with files
    sitting directly in the split directory kept as a module of their own. The
    result is then merged upward until it fits _MAX_MODULES.
    """
    if not files:
        return {}

    direct: dict[str, list[str]] = {}
    for rel in files:
        direct.setdefault(_directory_of(rel), []).append(rel)

    # Subtree totals and the child-directory map, both keyed by directory.
    subtree: dict[str, int] = {}
    children: dict[str, set[str]] = {}
    for directory, members in direct.items():
        node = directory
        subtree[node] = subtree.get(node, 0) + len(members)
        while node != _ROOT_MODULE:
            parent = _parent(node)
            children.setdefault(parent, set()).add(node)
            subtree[parent] = subtree.get(parent, 0) + len(members)
            node = parent
    subtree.setdefault(_ROOT_MODULE, 0)

    selected: set[str] = set()

    def visit(directory: str) -> None:
        kids = children.get(directory, set())
        if subtree.get(directory, 0) <= _MAX_FILES_PER_MODULE or not kids:
            selected.add(directory)
            return
        for child in kids:
            visit(child)
        if direct.get(directory):
            selected.add(directory)

    visit(_ROOT_MODULE)

    grouped = _assign(files, selected)

    # Merge the smallest modules into their parent until the count is legible.
    # Promoting a module to its parent does not always reduce the count on the
    # step that does it (the parent can absorb the child's files while the other
    # children stay separate), so bail out if a pass makes no progress rather
    # than risk spinning.
    while len(grouped) > _MAX_MODULES:
        mergeable = [m for m in grouped if m != _ROOT_MODULE]
        if not mergeable:
            break
        smallest = min(mergeable, key=lambda m: (len(grouped[m]), m))
        selected.discard(smallest)
        selected.add(_parent(smallest))
        merged = _assign(files, selected)
        if set(merged) == set(grouped):
            break
        grouped = merged
    return grouped


def _assign(files: list[str], selected: set[str]) -> dict[str, list[str]]:
    """Assign every file to its longest selected directory prefix."""
    grouped: dict[str, list[str]] = {}
    for rel in files:
        node = _directory_of(rel)
        while node not in selected and node != _ROOT_MODULE:
            node = _parent(node)
        grouped.setdefault(node, []).append(rel)
    return {module: sorted(members) for module, members in grouped.items() if members}


def module_adjacency(
    grouped: dict[str, list[str]], adjacency: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Lift the file-level dependency graph to module level (self-edges dropped)."""
    module_of = {rel: module for module, members in grouped.items() for rel in members}
    lifted: dict[str, set[str]] = {module: set() for module in grouped}
    for source, targets in adjacency.items():
        src_module = module_of.get(source)
        if src_module is None:
            continue
        for target in targets:
            dst_module = module_of.get(target)
            if dst_module is None or dst_module == src_module:
                continue
            lifted[src_module].add(dst_module)
            lifted[dst_module].add(src_module)
    return lifted


_PURPOSE_PATTERN = re.compile(r"^##\s*Purpose\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def file_purpose(page_text: str) -> str:
    """Pull the one-line purpose out of a generated per-file wiki page."""
    match = _PURPOSE_PATTERN.search(page_text)
    body = match.group(1) if match else page_text
    for line in body.strip().splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if cleaned and not cleaned.startswith("#"):
            return cleaned
    return ""


def _member_digest(members: list[str], page_texts: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    for rel in members:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(page_texts.get(rel, "").encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _load_cache(repo_path: str) -> dict[str, dict[str, str]]:
    path = _cache_file(repo_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    modules = data.get("modules") if isinstance(data, dict) else None
    return modules if isinstance(modules, dict) else {}


def _save_cache(repo_path: str, modules: dict[str, dict[str, str]]) -> None:
    path = _cache_file(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "updated_at": now_iso(), "modules": modules}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _count_label(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _mermaid_id(module: str) -> str:
    """Return a Mermaid-safe node id for a module path."""
    return "m_" + (re.sub(r"[^0-9A-Za-z]+", "_", module).strip("_") or "root")


def _edge_pairs(linked: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Return each connection once, as a sorted (a, b) pair list."""
    seen = {tuple(sorted((source, target))) for source, targets in linked.items() for target in targets}
    return sorted(seen)


def _mermaid_overview(grouped: dict[str, list[str]], linked: dict[str, set[str]]) -> str:
    """Render the whole module graph as a Mermaid flowchart.

    Obsidian renders ```mermaid blocks natively, so this puts the architecture in
    the note itself rather than asking the reader to reconstruct it from the
    global graph view. Edges are undirected (`---`): the dependency graph is
    symmetrised when it is lifted to module level, so an arrow would imply a
    direction the data no longer carries.
    """
    edges = _edge_pairs(linked)
    dropped = 0
    if len(edges) > _MAX_DIAGRAM_EDGES:
        # Keep the edges that carry the most structure: rank by the summed degree
        # of their endpoints, so hub connections survive and leaf-to-leaf noise goes.
        degree = {module: len(targets) for module, targets in linked.items()}
        edges.sort(key=lambda pair: (-(degree.get(pair[0], 0) + degree.get(pair[1], 0)), pair))
        dropped = len(edges) - _MAX_DIAGRAM_EDGES
        edges = sorted(edges[:_MAX_DIAGRAM_EDGES])

    lines = ["```mermaid", "flowchart LR"]
    for module in sorted(grouped, key=lambda m: (m == _ROOT_MODULE, m)):
        lines.append(f'    {_mermaid_id(module)}["{module_title(module)}<br/>{_count_label(len(grouped[module]), "file")}"]')
    for source, target in edges:
        lines.append(f"    {_mermaid_id(source)} --- {_mermaid_id(target)}")
    lines.append("```")
    if dropped:
        lines.append("")
        lines.append(f"_{dropped} lower-traffic connection(s) hidden to keep the diagram readable._")
    return "\n".join(lines)


def _mermaid_local(module: str, linked: dict[str, set[str]], grouped: dict[str, list[str]]) -> str:
    """Render one module and its direct neighbours — the readable 'local graph'.

    A whole-repo picture answers 'how is this organised'; this one answers 'what
    does this touch', which is the question you actually have while reading a
    module.
    """
    neighbours = sorted(linked.get(module, set()))[:_MAX_LINKS_IN_NOTE]
    if not neighbours:
        return ""
    lines = ["```mermaid", "flowchart LR"]
    lines.append(f'    {_mermaid_id(module)}["{module_title(module)}"]')
    for neighbour in neighbours:
        lines.append(f'    {_mermaid_id(neighbour)}["{module_title(neighbour)}<br/>{_count_label(len(grouped.get(neighbour, [])), "file")}"]')
    for neighbour in neighbours:
        lines.append(f"    {_mermaid_id(module)} --- {_mermaid_id(neighbour)}")
    lines.append(f"    style {_mermaid_id(module)} stroke-width:3px")
    lines.append("```")
    return "\n".join(lines)


def _frontmatter(fields: dict[str, object], tags: list[str]) -> str:
    """Render YAML frontmatter.

    Tags are what make the vault usable once generated notes live beside
    hand-written ones: Obsidian's graph view can colour or filter on them, so
    `-tag:2repo` shows only your own thinking.
    """
    lines = ["---", "tags:"]
    lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(f"{key}: {value}" for key, value in fields.items())
    lines.append("---")
    return "\n".join(lines)


def _wikilinks(modules: list[str], repo_name: str) -> str:
    """Render module names as Obsidian wikilinks, capped so hubs stay readable."""
    shown = modules[:_MAX_LINKS_IN_NOTE]
    rendered = " · ".join(f"[[{page_name_for(m, repo_name)[:-3]}|{module_title(m)}]]" for m in shown)
    if len(modules) > len(shown):
        rendered += f" · … and {len(modules) - len(shown)} more"
    return rendered or "_(none)_"


def _render_note(
    module: str,
    *,
    body: str,
    members: list[str],
    purposes: dict[str, str],
    linked: list[str],
    repo_name: str,
    updated: str,
    diagram: str = "",
) -> str:
    """Compose a module note from its cached LLM body plus fresh deterministic parts.

    Everything outside `body` is regenerated on every run, so links and file
    lists stay correct as the codebase moves without spending a single token.
    """
    parts = [
        _frontmatter(
            {"type": "module", "module": module_title(module), "files": len(members), "updated": updated},
            ["2repo", "2repo/module", f"project/{repo_name}"],
        ),
        "",
        f"# {module_title(module)}",
        "",
        body.strip(),
        "",
        "## Connected modules",
    ]
    if diagram:
        parts.extend([diagram, ""])
    parts.extend([
        _wikilinks(linked, repo_name),
        "",
        "## Files",
    ])
    for rel in members:
        purpose = purposes.get(rel, "")
        parts.append(f"- `{rel}`" + (f" — {purpose}" if purpose else ""))
    parts.extend(["", "---", f"[[{index_name_for(repo_name)[:-3]}|← {repo_name} index]]"])
    return "\n".join(parts).rstrip() + "\n"


def _render_index(
    repo_name: str,
    *,
    intro: str,
    grouped: dict[str, list[str]],
    linked: dict[str, set[str]],
    updated: str,
    diagram: str = "",
) -> str:
    """Compose the hub note that every module links back to."""
    parts = [
        _frontmatter(
            {"type": "index", "modules": len(grouped), "updated": updated},
            ["2repo", "2repo/index", f"project/{repo_name}"],
        ),
        "",
        f"# {repo_name}",
        "",
        intro.strip(),
        "",
    ]
    if diagram:
        parts.extend(["## Module map", diagram, ""])
    parts.append("## Modules")
    for module in sorted(grouped, key=lambda m: (m == _ROOT_MODULE, m)):
        members = grouped[module]
        degree = len(linked.get(module, set()))
        parts.append(
            f"- [[{page_name_for(module, repo_name)[:-3]}|{module_title(module)}]] — "
            f"{_count_label(len(members), 'file')}, {_count_label(degree, 'connected module')}"
        )
    return "\n".join(parts).rstrip() + "\n"


def _prune(out_dir: Path, valid: set[str]) -> list[str]:
    removed = []
    for note in out_dir.glob("*.md"):
        if note.name not in valid:
            note.unlink()
            removed.append(note.name)
    return removed


def generate(
    repo_path: str,
    *,
    grouped: dict[str, list[str]],
    adjacency: dict[str, set[str]],
    page_texts: dict[str, str],
    force_all: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Generate/update the module tier and return a summary.

    `page_texts` maps repo-relative source paths to their generated per-file wiki
    page. Module notes are written from those summaries rather than from source,
    which is what keeps this tier roughly 25 LLM calls instead of 900.
    """
    if not grouped:
        raise ValueError("no modules to document — the wiki produced no documentable files")

    repo_name = repo_display_name(repo_path)
    linked = module_adjacency(grouped, adjacency)
    purposes = {rel: file_purpose(text) for rel, text in page_texts.items()}
    cache = _load_cache(repo_path)

    stale = [
        module
        for module, members in sorted(grouped.items())
        if force_all or cache.get(module, {}).get("digest") != _member_digest(members, page_texts)
    ]

    if dry_run:
        for module in stale:
            print(f"Modules  : would regenerate {page_name_for(module, repo_name)}  ({module_title(module)})")
        if not stale:
            print("Modules  : nothing to regenerate (all module notes fresh)")
        return {
            "artifact": str(_MODULES_SUBPATH),
            "dry_run": True,
            "planned": stale,
            "module_count": len(grouped),
        }

    out_dir = modules_dir(repo_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    progress = Progress(len(stale), "Modules")
    for module in stale:
        members = grouped[module]
        listed = members[:_MAX_FILES_IN_PROMPT]
        file_lines = "\n".join(
            f"- {rel}" + (f" — {purposes.get(rel)}" if purposes.get(rel) else "") for rel in listed
        )
        if len(members) > len(listed):
            file_lines += f"\n- ... and {len(members) - len(listed)} more"
        link_lines = "\n".join(f"- {module_title(m)}" for m in sorted(linked.get(module, set()))) or "- (none)"
        body = call_llm(
            _MODULE_PROMPT.format(module=module_title(module), files=file_lines, links=link_lines)
        ).strip()
        cache[module] = {"digest": _member_digest(members, page_texts), "body": body, "updated": now_iso()}
        # Persist after every body, not once at the end: a run that dies at module
        # 25 of 30 must not throw away the 25 it already paid for.
        _save_cache(repo_path, cache)
        written.append(page_name_for(module, repo_name))
        progress.step(f"{module_title(module)}  ({_count_label(len(members), 'file')})")

    # Re-render every note, not just the regenerated ones: links and file lists are
    # deterministic, so keeping them current across the whole tier is free.
    for module, members in grouped.items():
        note = _render_note(
            module,
            body=cache.get(module, {}).get("body", ""),
            members=members,
            purposes=purposes,
            linked=sorted(linked.get(module, set())),
            repo_name=repo_name,
            updated=cache.get(module, {}).get("updated", ""),
            diagram=_mermaid_local(module, linked, grouped),
        )
        (out_dir / page_name_for(module, repo_name)).write_text(note, encoding="utf-8")

    index_path = out_dir / index_name_for(repo_name)
    intro = cache.get("__index__", {}).get("body", "")
    index_digest = _member_digest(sorted(grouped), {m: "" for m in grouped})
    if force_all or not intro or cache.get("__index__", {}).get("digest") != index_digest:
        intro = call_llm(
            _INDEX_PROMPT.format(
                repo=repo_name,
                modules="\n".join(f"- {module_title(m)} ({len(v)} files)" for m, v in sorted(grouped.items())),
            )
        ).strip()
        cache["__index__"] = {"digest": index_digest, "body": intro, "updated": now_iso()}
        written.append(index_name_for(repo_name))
        print(f"Modules  : wrote {index_name_for(repo_name)}")
    index_path.write_text(
        _render_index(
            repo_name,
            intro=intro,
            grouped=grouped,
            linked=linked,
            updated=cache.get("__index__", {}).get("updated", ""),
            diagram=_mermaid_overview(grouped, linked),
        ),
        encoding="utf-8",
    )

    valid = {page_name_for(m, repo_name) for m in grouped} | {index_name_for(repo_name)}
    removed = _prune(out_dir, valid)
    for name in removed:
        print(f"Modules  : pruned {name}")
    for key in set(cache) - set(grouped) - {"__index__"}:
        cache.pop(key, None)
    _save_cache(repo_path, cache)

    return {
        "artifact": str(_MODULES_SUBPATH),
        "dry_run": False,
        "written": written,
        "removed": removed,
        "module_count": len(grouped),
        "page_count": len(valid),
    }


def mirror_to_vault(repo_path: str, vault_path: Path) -> Path:
    """Mirror the module tier into the vault under Projects/<repo>/Generated/Modules/."""
    source = modules_dir(repo_path)
    if not source.exists() or not any(source.glob("*.md")):
        raise FileNotFoundError(f"module tier not generated yet: {source}")
    project_root = vault_path / "Projects" / repo_display_name(repo_path)
    (project_root / "Notes").mkdir(parents=True, exist_ok=True)
    return mirror_markdown_tree(source, project_root / "Generated" / "Modules")
