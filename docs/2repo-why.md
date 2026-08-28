# Why run `2repo`?

**The one-line answer:** every AI coding session starts from zero — it has to read your codebase before it can help. `2repo` does that reading once, so every future session (and every future you) starts already knowing the repo, instead of re-discovering it from scratch each time.

## Is it actually expensive?

Only two of the three layers are — and only on the first run.

| Layer | Cost | Why |
|---|---|---|
| `graph` | cheap — seconds, ~no LLM calls | static analysis (graphify) + deterministic file scans |
| `wiki` | expensive on first run | one LLM call per source file |
| `arch` | expensive on first run | one full LLM-backed analysis of how components fit together |

After the first run, `wiki` and `arch` are incremental: `wiki` only regenerates pages for files that changed since last time (an unchanged file is a cache hit — zero tokens), and `arch` only re-analyzes what changed. A repeat `2repo <repo>` run on an otherwise-untouched repo is close to free.

> Not sure it's worth it yet? Run `2repo graph <repo>` alone first. It's cheap and gives you `GRAPH_REPORT.md` — readable in 30 seconds. Add `wiki` and `arch` once you actually want file-level or system-level detail, not before.

## What each layer gives you

### `graph` — the map (always cheap, always runs first)
Extracts the dependency graph and writes `REPO_CONTEXT.md`: purpose, key files, how modules depend on each other, conventions, how to build/test/run. This is what gets injected into `CLAUDE.md` (or Copilot/Cursor).

**Without it:** every AI session burns its own context window re-discovering this from scratch, every single time you open the repo.

### `wiki` — the per-file explanation (expensive once, opt-in)
One readable page per source file: purpose, key elements, how it connects to the rest of the graph. Written so an AI — or you — never has to open the raw file to know what it does.

**Without it:** understanding a file means opening and reading it, every time, for every file.

### `arch` — the system-level picture (expensive once, opt-in)
Groups files into components/subsystems and writes narrative "how X works" pages plus Mermaid diagrams of how they connect. This is the layer above the wiki: the wiki tells you what one file does, `arch` tells you how the pieces work together.

**Without it:** you can see individual trees but not the shape of the forest.

## How they fit together

```
graph  →  wiki  →  arch
(map)     (per-file)  (system view)
```

Each layer builds on the one before it — `wiki` pages reference the graph's dependency info, and `arch` groups wiki pages into components. `wiki` and `arch` output is also folded back into the graph's semantic index, so `2repo query` can retrieve from all three at once.

A bare `2repo <repo>` runs all three in order. Run one layer on its own with `2repo graph <repo>` / `2repo wiki <repo>` / `2repo arch <repo>`.

## When to actually run which

- **`graph`** — always fine to run. Cheap, and every AI session benefits from it.
- **`wiki`** — run it when an AI is about to work extensively in this repo and should understand files without reading them itself.
- **`arch`** — run it when you (or the AI) need the "how does this whole thing work" view: onboarding, a big refactor, explaining the codebase to someone else.
- **Skip `wiki`/`arch`** for a repo you're only glancing at, or one that changes so often the pages would go stale before you'd use them.

## More detail

- Full command reference, flags, examples: [2repo.md](2repo.md)
- The internals — how incremental refresh, staleness, and caching actually work: [2repo-internals.md](2repo-internals.md)
