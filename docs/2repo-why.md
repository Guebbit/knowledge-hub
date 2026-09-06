# Why run `2repo`?

**The one-line answer:** every AI coding session starts from zero — it has to read your codebase before it can help. `2repo` does that reading once, so every future session (and every future you) starts already knowing the repo, instead of re-discovering it from scratch each time.

## Is it actually expensive?

Only two of the three layers are — and only on the first run.

| Layer | Cost | How | Why |
|---|---|---|---|
| `graph` | cheap — seconds, ~no LLM calls | static analysis (graphify) + deterministic file scans → `REPO_CONTEXT.md` | so every AI session starts already oriented instead of re-discovering the repo from scratch |
| `wiki` | expensive on first run | one LLM call per source file → one page per file | so files are understood once instead of re-read every time |
| `arch` | expensive on first run | one LLM-backed analysis (CodeBoarding) → component pages + Mermaid diagrams | so you can see how the whole system fits together, not just one file at a time |

After the first run, `wiki` and `arch` are incremental: `wiki` only regenerates pages for files that changed since last time (an unchanged file is a cache hit — zero tokens), and `arch` only re-analyzes what changed. A repeat `2repo <repo>` run on an otherwise-untouched repo is close to free.

> Not sure it's worth it yet? Run `2repo graph <repo>` alone first. It's cheap and gives you `GRAPH_REPORT.md` — readable in 30 seconds. Add `wiki` and `arch` once you actually want file-level or system-level detail, not before.

## Why each layer matters

### `graph`
Without it, every AI session — including your very next one — burns its own context window re-discovering the repo's shape before it can do anything useful: what files exist, what depends on what, how to build and run it. That rediscovery happens *every single time you open the repo*, in every tool, forever, unless something writes it down once.

`REPO_CONTEXT.md` is that write-down. The graph layer pays the discovery cost once (and near-free after that, since it's incremental), and every session after — Claude Code, Copilot, Cursor, or a human — starts already oriented instead of exploring first and helping second.

It pays off outside AI sessions too: open `GRAPH_REPORT.md` and understand an unfamiliar repo in about 30 seconds instead of clicking through 50 files. That's just as useful the first time you touch a coworker's codebase as it is re-opening your own project after months away — the graph doesn't forget what you did, even if you did.

### `wiki`
Without it, knowing what a specific file does means opening it and reading it — every time, for every file, whether it's you or the AI doing the reading. On a repo of any size that's a lot of repeated re-reading: the same auth helper re-parsed from scratch in five different sessions because nothing remembered what it learned last time.

The wiki front-loads that reading. Each page is written once, by an LLM, and then reused for free until the file changes (a cache hit costs zero tokens). An AI assistant retrieves the finished summary instead of spending its context window re-parsing implementation details; you can skim a page in seconds instead of tracing through code you don't currently need to touch. This pays off most on files you touch rarely — the ones you'd otherwise have to "re-learn" cold every time you come back to them, which is exactly the kind of repeated cognitive reload that's expensive to redo and cheap to just have written down.

**Where to actually read it.** Three ways, depending on what you want:
- **The raw pages** — `<repo>/.2repo/wiki/*.md`, one plain Markdown file per source file, plus a top-level `OVERVIEW.md`. Open any of them directly, no tooling required.
- **`2repo query <repo> "question"`** — semantic retrieval over the wiki (plus the graph and memory), when you want an answer instead of a page to browse.
- **The Obsidian vault** — *not* the raw per-file pages. One page per file is the right granularity for retrieval and the wrong one for a human to browse (a 430-file repo would be 430 disconnected notes), so what actually lands in `vault/Projects/<repo-name>/Generated/Modules/` is the synthesized **module tier**: one note per meaningful directory, built from the per-file pages and linked along the real dependency graph. That's the human-readable digest; the per-file pages stay repo-side for machine retrieval.

### `arch`
Without it, you can inspect any single file (via the wiki) but there's nothing that shows how a change in one place ripples through the rest of the system, or that lets you explain the codebase's shape to someone else without drawing the diagram yourself, from memory, on the spot. You can see individual trees but not the shape of the forest — and "how does this whole thing fit together" is not a question any single file's wiki page can answer.

`arch` answers that question directly: narrative pages per component plus Mermaid diagrams of how components connect, generated from real static analysis rather than a best guess. That's the artifact you reach for during onboarding (new person, or new-to-you codebase), before a large refactor (what else touches this?), or any time the question moves from "what does this file do" to "what happens if I change this."

## How the layers connect

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
