# 2repo — repository intelligence for AI coding sessions

**What it is:** deterministic repository artifacts generated inside the repo (`graphify-out/*`) plus one optional editor bridge file for your selected AI target.

**How it works:** `2repo ~/Work/my-repo` reads the repo, calls graphify, and builds canonical artifacts (`GRAPH_REPORT.md`, `EXECUTION.md`, `REPO_MEMORY.md`, `repo-index.json`, `REPO_CONTEXT.md`). Then it writes only the selected AI bridge file (Claude/Copilot/Cursor) that points to `REPO_CONTEXT.md`.

**Why it matters:**

When you open a project in Claude Code (or any AI assistant), the AI starts cold — it knows nothing about your codebase. It has to read dozens of files to understand the structure, burning through its context window before you've asked a single question.

With `graphify-out/REPO_CONTEXT.md`, the AI starts every session already knowing:
- What the repo does (purpose)
- Which files do what (key files table)
- How modules depend on each other (Mermaid diagram)
- What conventions to follow and what to avoid
- How to build/test/run it

One canonical source. Zero duplicated AI-specific summaries. The AI is useful from the first message.

**For humans too:** open `graphify-out/GRAPH_REPORT.md` and understand any repo in 30 seconds — no need to read 50 files.

> Want the theory — how the layers combine, how incremental refresh and staleness detection actually work? See **[2repo-internals.md](2repo-internals.md)**.

---

## Quick start

```bash
2repo ~/Work/my-repo             # 1. generate everything (pick an AI target when prompted)
2repo query ~/Work/my-repo "how do I run tests?"   # 2. ask the repo a question
2repo wiki ~/Work/my-repo        # 3. generate the per-file living wiki
2repo arch ~/Work/my-repo        # 4. generate the architecture layer (component docs + Mermaid diagrams)
2repo hook ~/Work/my-repo        # 5. (optional) warn on commit when the graph goes stale
```

Everything from here on is the detail behind those commands.

## Subcommands at a glance

| Command | What it does |
|---|---|
| `2repo <repo>` | Shortcut for `2repo graph <repo>` |
| `2repo graph <repo>` | Full pipeline: extract → execution → memory → index → context → AI bridge |
| `2repo graph <repo> --update` | Incremental refresh (changed files only) |
| `2repo graph <repo> --ai-target <t>` | Non-interactive target select: `claude` `copilot` `cursor` `neutral` |
| `2repo reindex <repo>` | Rebuild index/context/injections from existing artifacts |
| `2repo check <repo>` | Is the graph stale vs. the baseline commit? |
| `2repo hook <repo>` | Install the stale-warning post-commit hook |
| `2repo query <repo> "…"` | Semantic retrieval over artifacts + memory (`--top-k N`) |
| `2repo remember <repo> "…"` | Store a durable memory entry (`--kind fact\|decision\|runbook`) |
| `2repo wiki <repo>` | Generate/update the living per-file wiki |
| `2repo arch <repo>` | Generate/update the architecture layer (component docs + Mermaid diagrams) |

---

## Operational recall (`2repo query` + memory)

**What it is:** semantic recall on top of generated artifacts, with durable repository memory entries.

**How it works:** `2repo query <repo> "question"` retrieves ranked snippets from `graphify-out/*`; `2repo remember` stores durable facts/decisions/runbooks for future retrieval.

**Why it matters for ADHD:**

Coming back to a project after weeks away means re-reading everything. With ADHD, that re-reading costs real time and attention — and the context still doesn't fully load.

With retrieval + durable memory:
- Ask a repo question and get immediate, grounded snippets
- Store key decisions so they survive context resets
- Rehydrate project context after breaks without re-reading everything

---

## What 2repo does

One tool, one subcommand per category (so no single command does too many different things):

| Command | Category | What it does |
|---|---|---|
| `2repo graph <repo>` | Graph pipeline | Full run: extraction, execution knowledge, memory, index, context, AI injection (`--update` for incremental) |
| `2repo check <repo>` | Staleness | Check if the graph is stale vs the last baseline |
| `2repo hook <repo>` | Staleness | Install the stale-warning post-commit hook |
| `2repo reindex <repo>` | Index | Rebuild index/context/injections from existing artifacts |
| `2repo query <repo> "..."` | Recall | Semantic retrieval over artifacts + memory |
| `2repo remember <repo> "..."` | Recall | Store a durable repository memory entry |
| `2repo wiki <repo>` | Wiki | Generate/update the living LLM wiki incrementally |
| `2repo arch <repo>` | Architecture | Generate/update component/topic docs + Mermaid diagrams (CodeBoarding), incrementally |

`2repo <repo>` with no subcommand is a shortcut for `2repo graph <repo>`. Every other action uses its subcommand (`2repo wiki <repo>`, `2repo check <repo>`, ...).

The `graph` pipeline:

1. Graph extraction (`graphify extract` or `graphify update`)
2. Execution knowledge extraction (`EXECUTION.md`)
3. Repo memory materialization (`repo-memory.json`, `REPO_MEMORY.md`)
4. Semantic index build (`repo-index.json`)
5. Canonical context build (`REPO_CONTEXT.md`)
6. Targeted editor injection (single selected AI target)
7. State write for staleness + layer metadata (`.2repo-state.json`)

Fail-fast rule: if required artifacts are missing, 2repo exits with error (no placeholders).

## Generated artifacts (repo-local only)

After a successful run, the target repository gets:

```text
<repo>/
├── graphify-out/
│   ├── GRAPH_REPORT.md
│   ├── graph.json
│   ├── EXECUTION.md
│   ├── repo-memory.json
│   ├── REPO_MEMORY.md
│   ├── repo-index.json
│   ├── REPO_CONTEXT.md
│   ├── wiki/                  # optional, only after 2repo wiki
│   │   ├── OVERVIEW.md
│   │   ├── <path_with_underscores>.md
│   │   └── .wiki-cache.json
│   ├── arch/                  # optional, only after 2repo arch
│   │   ├── overview.md
│   │   └── <Component>.md
│   └── .2repo-state.json
```

`2repo arch` also keeps CodeBoarding's native working/baseline directory at
`<repo>/.codeboarding/` (`analysis.json` + `fingerprint.json` + rendered pages).
That directory is what makes incremental arch runs cheap — it is machine-owned,
marked generated (ignored by staleness checks and never documented by the wiki),
and its Markdown is mirrored into the indexed `graphify-out/arch/` copy.

Only one integration target is generated per run:

- Claude: `.claude/KNOWLEDGE.md` + `CLAUDE.md`
- Copilot: `.github/copilot-instructions.md`
- Cursor: `.cursor/rules/2repo.mdc`
- Neutral target: no editor-specific file

By default, no Obsidian outputs are generated by `2repo`. If you pass `2repo wiki <repo> --mirror-vault`, the generated wiki is mirrored into `vault/Projects/<repo-name>/Generated/`, while `vault/Projects/<repo-name>/Notes/` is reserved for human-authored notes.

### File objectives

| File | Objective |
|---|---|
| `graphify-out/GRAPH_REPORT.md` | Human + AI summary of repository structure, modules, and relationships |
| `graphify-out/graph.json` | Raw graph data produced by graphify |
| `graphify-out/EXECUTION.md` | Build/test/runbook-style operational knowledge extracted from the repo |
| `graphify-out/repo-memory.json` | Durable machine-readable memory entries stored by 2repo |
| `graphify-out/REPO_MEMORY.md` | Human-readable rendering of durable memory entries |
| `graphify-out/repo-index.json` | Semantic retrieval index used by `2repo query` |
| `graphify-out/REPO_CONTEXT.md` | Canonical context synthesized for AI assistant consumption |
| `graphify-out/.2repo-state.json` | Baseline commit + metadata used for staleness checks and hooks |
| `graphify-out/wiki/*.md` | Living wiki: per-file documentation pages + `OVERVIEW.md` (via `2repo wiki`) |
| `graphify-out/wiki/.wiki-cache.json` | Content-hash cache enabling incremental wiki regeneration |
| `graphify-out/arch/*.md` | Architecture layer: component/topic pages with Mermaid diagrams + `overview.md` (via `2repo arch`) |
| `.codeboarding/` | CodeBoarding's native working/baseline dir (incremental baseline for `2repo arch`); machine-owned |
| `.claude/KNOWLEDGE.md` + `CLAUDE.md` | Claude integration that points Claude Code to `REPO_CONTEXT.md` |
| `.github/copilot-instructions.md` | Copilot integration instructions with managed 2repo context block |
| `.cursor/rules/2repo.mdc` | Cursor global project rule that applies 2repo context |

## Commands

```bash
# Full run (graph is the default command)
2repo /path/to/repo
2repo graph /path/to/repo

# Optional non-interactive target selection (otherwise 2repo shows a small CLI selector)
2repo graph /path/to/repo --ai-target copilot

# Incremental graph update
2repo graph /path/to/repo --update

# Rebuild index/context/injections from existing artifacts
2repo reindex /path/to/repo

# Staleness check / hook
2repo check /path/to/repo
2repo hook /path/to/repo

# Semantic retrieval
2repo query /path/to/repo "how do I run tests?" --top-k 5

# Durable repo memory
2repo remember /path/to/repo "Use make test for fast CI parity" --kind runbook --source manual

# Living wiki (LLM-generated, incremental)
2repo wiki /path/to/repo                        # regenerate pages for changed files + 2-hop graph neighbors
2repo wiki /path/to/repo src/auth.ts src/db.ts  # target specific files (+ their graph neighbors)
2repo wiki /path/to/repo --force-all            # full rebuild (ignore cache and baseline)
2repo wiki /path/to/repo --dry-run              # preview which pages would regenerate (no LLM calls)
2repo wiki /path/to/repo --mirror-vault         # also mirror wiki pages into vault/Projects/<repo-name>/Generated/

# Architecture layer (component/topic docs + Mermaid diagrams, via CodeBoarding)
2repo arch /path/to/repo                         # incremental if a baseline exists, else a full analysis
2repo arch /path/to/repo --force-all             # full re-analysis (ignore the incremental baseline)
2repo arch /path/to/repo --dry-run               # report full-vs-incremental without calling the LLM
2repo arch /path/to/repo --mirror-vault          # also mirror pages into vault/Projects/<repo-name>/Generated/Architecture/
```

`--kind` values:

- `fact`
- `decision`
- `runbook`

### A typical session, start to finish

```bash
# First time on a repo — generate everything, choose Claude as the AI target
2repo graph ~/Work/api --ai-target claude

# Capture a decision you don't want to re-derive later
2repo remember ~/Work/api "Auth lives in src/auth; tokens are RS256" --kind decision
2repo remember ~/Work/api "make test runs the fast suite; make e2e is slow" --kind runbook

# A week later, coming back cold — ask instead of re-reading
2repo query ~/Work/api "where is request validation handled?" --top-k 5

# After a feature branch touched a few files — cheap incremental refresh
2repo graph ~/Work/api --update
2repo wiki ~/Work/api               # only changed files + their graph neighbors regenerate

# Keep it honest automatically
2repo hook ~/Work/api               # commits now warn when the graph drifts
```

## Living wiki (`2repo wiki`)

**What it is:** DeepWiki-style living documentation — one readable Markdown page per source file, plus a top-level `OVERVIEW.md`, written to `graphify-out/wiki/`. Pages describe purpose, key elements, and graph relationships so humans and AI can understand a file without reading it.

**Incrementality is the core design** (this is what makes LLM documentation affordable):

1. Changed files are detected via `git diff` against the `.2repo-state.json` baseline commit (or pass explicit files: `2repo wiki <repo> src/auth.ts`)
2. The changed set expands to dependency-graph neighbors up to **2 hops** (from `graphify-out/graph.json`)
3. A per-file content-hash cache (`graphify-out/wiki/.wiki-cache.json`) skips pages whose source did not change — untouched pages cost zero tokens
4. Pages whose source file disappeared are pruned automatically

Page naming replaces `/` and `.` with `_` (e.g. `src/auth/login.ts` → `src_auth_login_ts.md`).

Model selection: `--preset NAME` > `REPO_PRESET_WIKI` > `REPO_PRESET_GRAPH` > default preset. Use a fast model for routine updates and a big model for `--force-all` rebuilds. Wiki generation goes through the shared `call_llm` path, so any provider works here — including the subscription-backed CLI providers `claude-code` and `copilot-cli` (no metered API key; `copilot-cli` draws on your GitHub Copilot request allowance). See **[docs/2brain.md](2brain.md#presets--mixing-local-and-paid-models)** for the provider list.

After generation the wiki pages are folded into the semantic index (`2repo query` retrieves them) and referenced from `REPO_CONTEXT.md`. Wiki pages are **generated artifacts — never edit them by hand**; regenerate with `2repo wiki <repo>`.

When mirrored to Obsidian, generated pages stay one-way and machine-owned in `vault/Projects/<repo-name>/Generated/`.
Keep human-written project notes in the sibling `vault/Projects/<repo-name>/Notes/` folder so they are not overwritten on refresh.

Post-commit automation: `2repo hook` always adds a wiki refresh reminder to the stale warning. Set `REPO_WIKI_AUTO=1` before running `2repo hook` to make the hook run `2repo wiki .` automatically after commits (requires the `2repo` alias on the host).

## Architecture layer (`2repo arch`)

**What it is:** the tier *above* the per-file wiki. Where `2repo wiki` writes one page per source file, `2repo arch` clusters the codebase into **components/subsystems** and writes narrative "how X works" pages plus **Mermaid architecture diagrams** — the two things the file-by-file wiki cannot give you. Output lands in `graphify-out/arch/` (`overview.md` + one page per component).

**How it works:** it delegates to [CodeBoarding](https://github.com/CodeBoarding/CodeBoarding) (MIT) — static analysis (language servers) + LLM reasoning → Mermaid diagrams + component Markdown. 2repo runs it behind a thin adapter, then mirrors the rendered Markdown into `graphify-out/arch/` so the pages fold into the semantic index (`2repo query` retrieves them) and are referenced from `REPO_CONTEXT.md`.

**Incrementality:** CodeBoarding keeps a baseline in `<repo>/.codeboarding/` (`analysis.json` + `fingerprint.json`). When that baseline exists, `2repo arch` runs an incremental re-analysis of only the changed parts; otherwise (or with `--force-all`) it runs a full analysis. `--dry-run` reports which mode would run without any LLM calls.

**Model selection:** `--preset NAME` > `REPO_PRESET_ARCH` > `REPO_PRESET_WIKI` > `REPO_PRESET_GRAPH` > default preset. Point it at an **ollama**, **openai**, or **anthropic** preset — `claude-code` presets are not usable here because CodeBoarding has no CLI/subscription backend (2repo fails fast with guidance if you try). Provider selection is deterministic: the adapter runs CodeBoarding with an environment exposing only the selected provider's credentials, even if several API keys are present in the container.

**Privacy:** CodeBoarding telemetry is disabled unconditionally (`CODEBOARDING_TELEMETRY=false` / `DO_NOT_TRACK=1`), consistent with 2repo's local-first design. No source code leaves the machine.

Like the wiki, the architecture layer is **opt-in and expensive** (never run by `2repo graph`), its pages are **generated artifacts — never edit them by hand** (regenerate with `2repo arch <repo>`), and it deliberately does **not** move the staleness baseline (only `graphify` does).

> Swappable by design: if CodeBoarding is ever abandoned, only two helpers in `scripts/repo/arch.py` (`_run_codeboarding` and `_codeboarding_dir`) know the tool — replace them with another generator that emits Markdown into `<repo>/.codeboarding/` and the rest (indexing, context, CLI) is unchanged.

## Semantic retrieval model

`repo-index.json` stores chunked vectors from:

- `graphify-out/*` textual artifacts
- runtime metadata
- persisted repo memory entries

Querying uses cosine similarity over TF-IDF vectors plus query expansion from top-ranked chunks, then returns ranked context snippets.

## State model

2repo writes `graphify-out/.2repo-state.json` with:

- baseline git commit (`head`)
- stale threshold (`threshold`)
- per-layer metadata (`layers.execution`, `layers.memory`, `layers.index`, `layers.context`)

`2repo check` compares git changes since the baseline commit while excluding generated artifacts.

## AI target selection and injections

All integrations use one canonical source:

- `graphify-out/REPO_CONTEXT.md`

When `--ai-target` is not passed, 2repo prompts a small CLI selection (non-interactive runs default to `neutral`):

- `claude`
- `copilot`
- `cursor`
- `neutral` (local models/custom setups; no editor-specific file generation)

Generated outputs by selection:

- Claude: `.claude/KNOWLEDGE.md` and managed block in `CLAUDE.md`
- Copilot: managed block in `.github/copilot-instructions.md`
- Cursor: `.cursor/rules/2repo.mdc`
- Neutral: no claude/copilot/cursor files

## 2repo configuration (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `REPO_PRESET_GRAPH` | `smart` | Preset used for graphify extraction (`2repo graph`) |
| `REPO_PRESET_WIKI` | falls back to `REPO_PRESET_GRAPH` | Preset used for wiki page generation (`2repo wiki`) |
| `REPO_PRESET_ARCH` | falls back to `REPO_PRESET_WIKI` → `REPO_PRESET_GRAPH` | Preset used for the architecture layer (`2repo arch`); ollama/openai/anthropic only |
| `COPILOT_GITHUB_TOKEN` | — | Token for a `copilot-cli` preset (fine-grained PAT with the "Copilot Requests" permission); see [docs/2brain.md](2brain.md#configuration-reference) |
| `REPO_AI_TARGET` | — | Optional default AI target (`claude`, `copilot`, `cursor`, `neutral`) |
| `REPO_STALE_THRESHOLD` | `5` | Files-changed threshold for stale warnings (`0` disables warning mode) |
| `REPO_WIKI_AUTO` | — | Set to `1` before `2repo hook` to auto-refresh the wiki after each commit |

Shared variables (`LINUX_USERNAME`, `DEFAULT_PRESET`, `PRESET_*`, API keys, Ollama tuning) are documented in **[docs/2brain.md](2brain.md#configuration-reference)**.

---

See the main [README](../README.md) for installation, the shared model cache, and troubleshooting.
