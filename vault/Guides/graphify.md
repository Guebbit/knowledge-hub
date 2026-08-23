---
title: "graphify"
tags:
  - graphify
  - knowledge-graph
  - ai-assistants
  - dev-tools
created: 2026-06-21
folder: Guides
---

## Summary
Graphify converts a codebase into a queryable knowledge graph, so AI assistants can search structure and semantics without re-reading files. Code parsing is local via tree-sitter; semantic extraction over docs/markdown optionally goes through [[Ollama]].

In this stack graphify is **not run by hand** — it is a pinned dependency of [[2repo]], which drives it as the first of three layers. The direct CLI is still worth knowing for ad-hoc queries against an existing graph.

## How it runs here

`2repo graph <repo>` shells out to graphify inside the `scripts` container, then builds its own layers on top. Two details of that wiring matter:

- **Pinned version.** `graphifyy==0.9.13` in `pyproject.toml` and `Dockerfile.scripts`. The package publishes near-daily and has shipped breaking CLI changes without a major bump — `extract` stopped clustering mid-0.9.x, which is why `2repo` calls `cluster-only` as a follow-up. Bump deliberately.
- **Output location.** 2repo exports `GRAPHIFY_OUT=2repo/graphify-out` to every graphify subprocess, so the graph lands nested under 2repo's own output tree instead of at the repo root. graphify reads that env var once at import time and every one of its readers honours it.

> [!WARNING] The PyPI package is `graphifyy` (double-y). The CLI command is `graphify` (single-y).

## Direct CLI

Useful against a graph 2repo has already built:

```bash
graphify query "how does auth work?"
graphify explain "RequestHandler"
graphify path "router" "database"
```

Build/rebuild commands — normally 2repo's job, not yours:

```bash
graphify extract . --backend <backend> --model <model>
graphify cluster-only . --backend <backend> --model <model>   # names communities, writes GRAPH_REPORT.md
graphify update .                                             # incremental
```

## Artifacts

Under `<repo>/2repo/graphify-out/`:

| File | What it is |
|---|---|
| `graph.json` | Raw nodes/edges — the graph itself |
| `manifest.json` | Extraction manifest; its presence marks a usable incremental baseline |
| `GRAPH_REPORT.md` | Human-readable structure/module/relationship summary |
| `graph.html` | Standalone interactive viewer (`xdg-open` it) |

These are **committed**, not ignored — see [[2repo]] for why. `graph.html` is the one worth adding to `.gitignore`: large, and regenerable from `graph.json`.

## Exclusions

- `.graphifyignore` in the project root, gitignore syntax. Both `.gitignore` and `.graphifyignore` are respected, merged per directory.
- 2repo writes a managed block into `.graphifyignore` listing `2repo/` and `.codeboarding/`. This is load-bearing: graphify self-prunes only the single directory it writes to (by basename of `GRAPHIFY_OUT`), so without that block it would re-ingest 2repo's own wiki and arch pages as source.
- Common heavy dirs (`node_modules`, `dist`, `build`, `.next`, venvs, caches) are skipped by name automatically.

## Gotcha: the output basename

graphify injects `basename(GRAPHIFY_OUT)` into its own scan-skip set. Renaming the output directory to something generic — `graph`, `out`, `docs` — would silently drop every directory of that name in the *target* repo from extraction. The nested dir keeps the basename `graphify-out` for exactly this reason.

## Related
- [[2repo]] — the pipeline that drives graphify and adds execution, memory, index, wiki, and architecture layers
- [[llm-wiki]] — the living-documentation layer built on top of the graph
- [[Ollama]] — local backend for semantic extraction
