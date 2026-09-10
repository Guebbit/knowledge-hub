# 2brain — repository intelligence for AI coding sessions

**What it is:** deterministic repository artifacts generated inside the repo (`.2brain/*`) plus one optional editor bridge file for your selected AI target.

**How it works:** `2brain ~/Work/my-repo` runs every layer in order — `graph`, then `wiki`, then `arch`. The graph layer reads the repo, calls graphify, and builds canonical artifacts (`GRAPH_REPORT.md`, `EXECUTION.md`, `REPO_MEMORY.md`, `repo-index.json`, `REPO_CONTEXT.md`), then writes only the selected AI bridge file (Claude/Copilot/Cursor) that points to `REPO_CONTEXT.md`. The wiki and arch layers add per-file pages and component diagrams on top, and mirror them into the Obsidian vault when one is present. Run a single layer by naming it (`2brain graph <repo>`).

**Why it matters:**

When you open a project in Claude Code (or any AI assistant), the AI starts cold — it knows nothing about your codebase. It has to read dozens of files to understand the structure, burning through its context window before you've asked a single question.

With `.2brain/REPO_CONTEXT.md`, the AI starts every session already knowing:
- What the repo does (purpose)
- Which files do what (key files table)
- How modules depend on each other (Mermaid diagram)
- What conventions to follow and what to avoid
- How to build/test/run it

One canonical source. Zero duplicated AI-specific summaries. The AI is useful from the first message.

**For humans too:** open `.2brain/graphify-out/GRAPH_REPORT.md` and understand any repo in 30 seconds — no need to read 50 files.

> Want the short version first — why to run this and what it actually costs? See **[2brain-why.md](2brain-why.md)**. Want the theory — how the layers combine, how incremental refresh and staleness detection actually work? See **[2brain-internals.md](2brain-internals.md)**.

---

## Quick start

```bash
2brain ~/Work/my-repo             # 1. generate everything: graph + wiki + arch (pick an AI target when prompted)
2brain query ~/Work/my-repo "how do I run tests?"   # 2. ask the repo a question
2brain wiki ~/Work/my-repo        # 3. generate the per-file living wiki
2brain arch ~/Work/my-repo        # 4. generate the architecture layer (component docs + Mermaid diagrams)
2brain hook ~/Work/my-repo        # 5. (optional) warn on commit when the graph goes stale
```

Everything from here on is the detail behind those commands.

## Subcommands at a glance

| Command | What it does |
|---|---|
| `2brain <repo>` | Shortcut for `2brain graph <repo>` |
| `2brain graph <repo>` | Full pipeline: extract → execution → memory → index → context → AI bridge |
| `2brain graph <repo> --update` | Incremental refresh (changed files only) |
| `2brain graph <repo> --ai-target <t>` | Non-interactive target select: `claude` `copilot` `cursor` `neutral` |
| `2brain reindex <repo>` | Rebuild index/context/injections from existing artifacts |
| `2brain check <repo>` | Is the graph stale vs. the baseline commit? |
| `2brain hook <repo>` | Install the stale-warning post-commit hook |
| `2brain query <repo> "…"` | Semantic retrieval over artifacts + memory (`--top-k N`) |
| `2brain remember <repo> "…"` | Store a durable memory entry (`--kind fact\|decision\|runbook`) |
| `2brain wiki <repo>` | Generate/update the living per-file wiki |
| `2brain arch <repo>` | Generate/update the architecture layer (component docs + Mermaid diagrams) |

---

## Operational recall (`2brain query` + memory)

**What it is:** semantic recall on top of generated artifacts, with durable repository memory entries.

**How it works:** `2brain query <repo> "question"` retrieves ranked snippets from `.2brain/*`; `2brain remember` stores durable facts/decisions/runbooks for future retrieval.

**Why it matters for ADHD:**

Coming back to a project after weeks away means re-reading everything. With ADHD, that re-reading costs real time and attention — and the context still doesn't fully load.

With retrieval + durable memory:
- Ask a repo question and get immediate, grounded snippets
- Store key decisions so they survive context resets
- Rehydrate project context after breaks without re-reading everything

---

## What 2brain does

One tool, one subcommand per category (so no single command does too many different things):

| Command | Category | What it does |
|---|---|---|
| `2brain graph <repo>` | Graph pipeline | Full run: extraction, execution knowledge, memory, index, context, AI injection (`--update` for incremental) |
| `2brain check <repo>` | Staleness | Check if the graph is stale vs the last baseline |
| `2brain hook <repo>` | Staleness | Install the stale-warning post-commit hook |
| `2brain reindex <repo>` | Index | Rebuild index/context/injections from existing artifacts |
| `2brain query <repo> "..."` | Recall | Semantic retrieval over artifacts + memory |
| `2brain remember <repo> "..."` | Recall | Store a durable repository memory entry |
| `2brain wiki <repo>` | Wiki | Generate/update the living LLM wiki incrementally |
| `2brain arch <repo>` | Architecture | Generate/update component/topic docs + Mermaid diagrams (CodeBoarding), incrementally |

`2brain <repo>` with no subcommand is a shortcut for `2brain graph <repo>`. Every other action uses its subcommand (`2brain wiki <repo>`, `2brain check <repo>`, ...).

The `graph` pipeline:

1. Graph extraction (`graphify extract` or `graphify update`)
2. Execution knowledge extraction (`EXECUTION.md`)
3. Repo memory materialization (`repo-memory.json`, `REPO_MEMORY.md`)
4. Semantic index build (`repo-index.json`)
5. Canonical context build (`REPO_CONTEXT.md`)
6. Targeted editor injection (single selected AI target)
7. State write for staleness + layer metadata (`.2brain-state.json`)

Fail-fast rule: if required artifacts are missing, 2brain exits with error (no placeholders).

```mermaid
flowchart TD
    CMD["bare 2brain run<br/>= graph, then wiki, then arch"] --> G["graph layer<br/>always runs"]
    G --> W["wiki layer<br/>optional · one LLM call per file"]
    W --> A["arch layer<br/>optional · via CodeBoarding"]

    G --> IDX["repo-index.json<br/>semantic index"]
    G --> CTX["REPO_CONTEXT.md<br/>canonical context"]
    G --> BR["one editor bridge file<br/>CLAUDE.md / Copilot / Cursor"]
    W --> WA[".2brain/llm-wiki/ + .2brain/wiki/"]
    A --> AA[".2brain/arch/<br/>+ Mermaid diagrams"]

    CTX --> BR
    WA -.->|"folded back in"| IDX
    AA -.->|"folded back in"| IDX
```

## Generated artifacts (repo-local only)

After a successful run, the target repository gets:

```text
<repo>/
├── .2brain/
│   ├── EXECUTION.md
│   ├── repo-memory.json
│   ├── REPO_MEMORY.md
│   ├── repo-index.json
│   ├── REPO_CONTEXT.md
│   ├── graphify-out/          # graphify's own output, nested
│   │   ├── GRAPH_REPORT.md
│   │   ├── graph.json
│   │   ├── manifest.json
│   │   └── graph.html
│   ├── llm-wiki/               # per-file pages — machine tier, not mirrored
│   │   ├── OVERVIEW.md
│   │   ├── <path_with_underscores>.md
│   │   └── .llm-wiki-cache.json
│   ├── wiki/                   # per-module notes — human tier, mirrored to the vault
│   │   ├── <repo>_INDEX.md
│   │   ├── <repo>_<module_with_underscores>.md
│   │   └── .wiki-cache.json
│   ├── arch/                  # optional, only after 2brain arch
│   │   ├── overview.md
│   │   └── <Component>.md
│   └── .2brain-state.json
├── .2brainignore               # hand-editable: which files 2brain documents
├── .graphifyignore            # managed block, only when needed: keeps .2brain/ out of the graph
├── .gitattributes             # managed block: marks .2brain/ generated
└── .gitignore                 # managed block: excludes regen-only caches/dupes
```

The tree is named after the tool that owns it. 2brain writes the execution,
memory, index, context and wiki artifacts; CodeBoarding writes `arch/`; graphify
gets the nested subdirectory. 2brain arranges that nesting by exporting
`GRAPHIFY_OUT=.2brain/graphify-out` to every graphify subprocess — graphify reads
that env var once at import time and every one of its readers honours it.

The nested directory keeps the basename `graphify-out` on purpose: graphify
injects `basename(GRAPHIFY_OUT)` into its own scan-skip set so it never
re-ingests its output as source, so a basename like `graph` would silently drop
every `graph/` directory in the *target* repo from extraction.

**Committing the artifacts is the intended workflow.** Regenerating them costs
real LLM tokens, the caches that keep re-runs cheap live in the same tree, and a
teammate who clones without them gets a `CLAUDE.md` pointing at a file that does
not exist. They are also not reproducible the way build output is — a different
provider, model, or day yields different text. The generated `.gitattributes`
block marks them `linguist-generated` so they collapse in GitHub reviews;
`graph.html` and `.codeboarding/` are the two things worth adding to your own
`.gitignore`, being large and regenerable respectively.

`2brain arch` also keeps CodeBoarding's native working/baseline directory at
`<repo>/.codeboarding/` (`analysis.json` + `fingerprint.json` + rendered pages).
That directory is what makes incremental arch runs cheap — it is machine-owned,
marked generated (ignored by staleness checks and never documented by the wiki),
and its Markdown is mirrored into the indexed `.2brain/arch/` copy.

Only one integration target is generated per run:

- Claude: `CLAUDE.md`
- Copilot: `.github/copilot-instructions.md`
- Cursor: `.cursor/rules/2brain.mdc`
- Neutral target: no editor-specific file

Every target gets the same directive — use the generated context before
proposing changes — plus the artifact list. Claude's block additionally
`@`-imports `REPO_CONTEXT.md`, which is what puts it in context automatically at
session start; the other two name the path and rely on the assistant reading it.

`2brain wiki` and `2brain arch` mirror their pages into the Obsidian vault **by default**, whenever a vault is found at `VAULT_PATH` — that is, the directory exists and holds either `.obsidian/` or one of the standard 2brain folders. Wiki pages land in `vault/Projects/<repo-name>/Generated/` and architecture pages in `vault/Projects/<repo-name>/Generated/Architecture/`, while `vault/Projects/<repo-name>/Notes/` is reserved for human-authored notes. The other subcommands (`graph`, `reindex`, `query`, …) never touch the vault.

Override the default in either direction:

| Setting | Effect |
|---|---|
| *(nothing)* | Mirror when a vault is found, skip quietly when it is not |
| `--no-mirror-vault` | Never mirror, this run |
| `--mirror-vault` | Always mirror, and fail loudly if the pages or vault are missing |
| `REPO_MIRROR_VAULT=0` in `.env` | Never mirror |
| `REPO_MIRROR_VAULT=1` in `.env` | Always mirror |

The command-line flag always beats the env var, which always beats auto-detection.

### File objectives

| File | Objective |
|---|---|
| `.2brain/graphify-out/GRAPH_REPORT.md` | Human + AI summary of repository structure, modules, and relationships |
| `.2brain/graphify-out/graph.json` | Raw graph data produced by graphify |
| `.2brain/EXECUTION.md` | Build/test/runbook-style operational knowledge extracted from the repo |
| `.2brain/repo-memory.json` | Durable machine-readable memory entries stored by 2brain |
| `.2brain/REPO_MEMORY.md` | Human-readable rendering of durable memory entries |
| `.2brain/repo-index.json` | Semantic retrieval index used by `2brain query` |
| `.2brain/REPO_CONTEXT.md` | Canonical context synthesized for AI assistant consumption |
| `.2brain/.2brain-state.json` | Baseline commit + metadata used for staleness checks and hooks |
| `.2brain/llm-wiki/*.md` | Per-file LLM wiki: machine-oriented documentation pages + `OVERVIEW.md` (via `2brain wiki`) |
| `.2brain/llm-wiki/.llm-wiki-cache.json` | Content-hash cache enabling incremental per-file regeneration |
| `.2brain/wiki/*.md` | Living wiki: one note per meaningful directory + `INDEX.md`, mirrored to the vault (via `2brain wiki`) |
| `.2brain/wiki/.wiki-cache.json` | Content-hash cache enabling incremental module-note regeneration |
| `.2brain/arch/*.md` | Architecture layer: component/topic pages with Mermaid diagrams + `overview.md` (via `2brain arch`) |
| `.codeboarding/` | CodeBoarding's native working/baseline dir (incremental baseline for `2brain arch`); machine-owned |
| `.graphifyignore` | Managed block keeping generated dirs out of graphify's source scan — written **only** for dirs `.gitignore` does not already exclude, and not written at all when it covers them all |
| `.gitattributes` | Managed block marking `.2brain/**` as generated so it collapses in reviews |
| `.gitignore` | Managed block excluding regeneration-only caches and duplicates (graphify's raw dumps, its dated snapshot dirs, the wiki/module incremental caches, `.codeboarding/`) — everything else under `.2brain/` is committed |
| `CLAUDE.md` | Managed block that `@`-imports `REPO_CONTEXT.md` into every Claude Code session |
| `.github/copilot-instructions.md` | Copilot integration instructions with managed 2brain context block |
| `.cursor/rules/2brain.mdc` | Cursor global project rule that applies 2brain context |

## Commands

```bash
# Full run — `all` is the default command, so these two are equivalent
2brain /path/to/repo
2brain all /path/to/repo

# One layer only
2brain graph /path/to/repo

# Optional non-interactive target selection (otherwise 2brain shows a small CLI selector)
2brain graph /path/to/repo --ai-target copilot

# Every layer at once (graph + wiki + arch) — this is what a bare `2brain <repo>` runs
2brain all /path/to/repo
2brain all /path/to/repo --force-all              # rebuild every layer from scratch
2brain all /path/to/repo --ai-target neutral      # skip the interactive target selector

# Incremental graph update
2brain graph /path/to/repo --update

# Rebuild index/context/injections from existing artifacts
2brain reindex /path/to/repo

# Staleness check / hook
2brain check /path/to/repo
2brain hook /path/to/repo

# Semantic retrieval
2brain query /path/to/repo "how do I run tests?" --top-k 5

# Durable repo memory
2brain remember /path/to/repo "Use make test for fast CI parity" --kind runbook --source manual

# Living wiki (LLM-generated, incremental)
2brain wiki /path/to/repo                        # regenerate pages for changed files + 2-hop graph neighbors
2brain wiki /path/to/repo src/auth.ts src/db.ts  # target specific files (+ their graph neighbors)
2brain wiki /path/to/repo --force-all            # full rebuild (ignore cache and baseline)
2brain wiki /path/to/repo --dry-run              # preview which pages would regenerate (no LLM calls)
2brain wiki /path/to/repo --no-mirror-vault      # skip the vault mirror (on by default when a vault exists)

# Architecture layer (component/topic docs + Mermaid diagrams, via CodeBoarding)
2brain arch /path/to/repo                         # incremental if a baseline exists, else a full analysis
2brain arch /path/to/repo --force-all             # full re-analysis (ignore the incremental baseline)
2brain arch /path/to/repo --dry-run               # report full-vs-incremental without calling the LLM
2brain arch /path/to/repo --no-mirror-vault       # skip the vault mirror (on by default when a vault exists)
```

`--kind` values:

- `fact`
- `decision`
- `runbook`

### A typical session, start to finish

```bash
# First time on a repo — generate everything, choose Claude as the AI target
2brain graph ~/Work/api --ai-target claude

# Capture a decision you don't want to re-derive later
2brain remember ~/Work/api "Auth lives in src/auth; tokens are RS256" --kind decision
2brain remember ~/Work/api "make test runs the fast suite; make e2e is slow" --kind runbook

# A week later, coming back cold — ask instead of re-reading
2brain query ~/Work/api "where is request validation handled?" --top-k 5

# After a feature branch touched a few files — cheap incremental refresh
2brain graph ~/Work/api --update
2brain wiki ~/Work/api               # only changed files + their graph neighbors regenerate

# Keep it honest automatically
2brain hook ~/Work/api               # commits now warn when the graph drifts
```

## Living wiki (`2brain wiki`)

**What it is:** DeepWiki-style living documentation — one readable Markdown page per source file, plus a top-level `OVERVIEW.md`, written to `.2brain/llm-wiki/`. Pages describe purpose, key elements, and graph relationships so humans and AI can understand a file without reading it.

**Incrementality is the core design** (this is what makes LLM documentation affordable):

1. Changed files are detected via `git diff` against the `.2brain-state.json` baseline commit (or pass explicit files: `2brain wiki <repo> src/auth.ts`)
2. The changed set expands to dependency-graph neighbors up to **2 hops** (from `.2brain/graphify-out/graph.json`)
3. A per-file content-hash cache (`.2brain/llm-wiki/.llm-wiki-cache.json`) skips pages whose source did not change — untouched pages cost zero tokens
4. Pages whose source file disappeared are pruned automatically

Page naming replaces `/` and `.` with `_` (e.g. `src/auth/login.ts` → `src_auth_login_ts.md`).

Model selection: `--preset NAME` > `REPO_PRESET_WIKI` > `REPO_PRESET_GRAPH` > default preset. Use a fast model for routine updates and a big model for `--force-all` rebuilds. Wiki generation goes through the shared `call_llm` path, so any provider works here — including the subscription-backed CLI providers `claude-code` and `copilot-cli` (no metered API key; `copilot-cli` draws on your GitHub Copilot request allowance). See **[docs/2brain-quick.md](2brain-quick.md#presets--mixing-local-and-paid-models)** for the provider list.

After generation the wiki pages are folded into the semantic index (`2brain query` retrieves them) and referenced from `REPO_CONTEXT.md`. Wiki pages are **generated artifacts — never edit them by hand**; regenerate with `2brain wiki <repo>`.

**These pages are the machine tier and are not mirrored into the vault.** One page per file is the right granularity for retrieval and the wrong one for a human. The same run builds the [module tier](#module-tier-2brainwiki) on top of them, and that is what reaches Obsidian. Keep human-written project notes in `vault/Projects/<repo-name>/Notes/` so they are never touched by a refresh.

Post-commit automation: `2brain hook` always adds a wiki refresh reminder to the stale warning. Set `REPO_WIKI_AUTO=1` before running `2brain hook` to make the hook run `2brain wiki .` automatically after commits (requires the `2brain` alias on the host).

## Architecture layer (`2brain arch`)

**What it is:** the tier *above* the per-file wiki. Where `2brain wiki` writes one page per source file, `2brain arch` clusters the codebase into **components/subsystems** and writes narrative "how X works" pages plus **Mermaid architecture diagrams** — the two things the file-by-file wiki cannot give you. Output lands in `.2brain/arch/` (`overview.md` + one page per component).

**How it works:** it delegates to [CodeBoarding](https://github.com/CodeBoarding/CodeBoarding) (MIT) — static analysis (language servers) + LLM reasoning → Mermaid diagrams + component Markdown. 2brain runs it behind a thin adapter, then mirrors the rendered Markdown into `.2brain/arch/` so the pages fold into the semantic index (`2brain query` retrieves them) and are referenced from `REPO_CONTEXT.md`.

**Incrementality:** CodeBoarding keeps a baseline in `<repo>/.codeboarding/` (`analysis.json` + `fingerprint.json`). When that baseline exists, `2brain arch` runs an incremental re-analysis of only the changed parts; otherwise (or with `--force-all`) it runs a full analysis. `--dry-run` reports which mode would run without any LLM calls.

**Model selection:** `--preset NAME` > `REPO_PRESET_ARCH` > `REPO_PRESET_WIKI` > `REPO_PRESET_GRAPH` > default preset. Point it at an **ollama**, **openai**, or **anthropic** preset — `claude-code` presets are not usable here because CodeBoarding has no CLI/subscription backend (2brain fails fast with guidance if you try). Provider selection is deterministic: the adapter runs CodeBoarding with an environment exposing only the selected provider's credentials, even if several API keys are present in the container.

**Privacy:** CodeBoarding telemetry is disabled unconditionally (`CODEBOARDING_TELEMETRY=false` / `DO_NOT_TRACK=1`), consistent with 2brain's local-first design. No source code leaves the machine.

Like the wiki, the architecture layer is **opt-in and expensive** (never run by `2brain graph`), its pages are **generated artifacts — never edit them by hand** (regenerate with `2brain arch <repo>`), and it deliberately does **not** move the staleness baseline (only `graphify` does).

> Swappable by design: if CodeBoarding is ever abandoned, only two helpers in `scripts/repo/arch.py` (`_run_codeboarding` and `_codeboarding_dir`) know the tool — replace them with another generator that emits Markdown into `<repo>/.codeboarding/` and the rest (indexing, context, CLI) is unchanged.

## Module tier (`.2brain/wiki/`)

**What it is:** one note per meaningful directory — the tier between the per-file wiki and the whole-repo architecture view. This is what you read, and the only wiki-side output mirrored into the Obsidian vault.

**Why it exists.** The per-file wiki is written for machines: one page per source file, hundreds of them, consumed through the semantic index so an AI never has to open the file. Mirrored into a vault it is unreadable — a 430-file repo becomes 430 disconnected notes that bury your hand-written ones. Every mature tool in this space documents *units of meaning* instead: DeepWiki emits a few dozen topic pages, CodeBoarding (our arch layer) emits component pages, and Obsidian practice calls the same shape a Map of Content. The module tier is that layer.

**How modules are chosen.** Top-down over the directory tree: a directory whose entire subtree holds at most 40 documented files becomes one module; anything larger splits into its children, with files sitting directly in the split directory kept as a module of their own. The result is then merged upward until it fits 30 modules. A 430-file frontend lands on ~30 modules like `src/modules/cart/`, `src/ui/`, `scripts/`.

**What each note contains:** an LLM-written Purpose / Key parts / How it connects / Where to start, then three deterministic sections — a **Mermaid diagram** of the module and its direct neighbours (Obsidian renders these natively), `## Connected modules` as wikilinks taken from the real dependency graph, and `## Files` listing members with their one-line purpose. The hub note opens with a **module map**: the whole dependency graph as one flowchart, edge-capped so it stays a map rather than a hairball. YAML frontmatter carries `tags: 2brain, 2brain/module, project/<repo>` so the vault graph can filter or colour generated notes separately from your own (`-tag:2brain` shows only your thinking). `<repo>_INDEX.md` is the hub every module links back to. Note filenames are namespaced by repository — Obsidian resolves wikilinks by filename across the whole vault, so two projects with a `src/ui/` would otherwise collide.

**Cost:** module notes are written from the already-generated per-file summaries, not from source — about 30 LLM calls for a repo where the per-file tier costs 430. A content hash over each module's member pages makes unchanged modules free on re-runs, and the deterministic parts (frontmatter, links, file lists) are re-rendered every run at zero cost, so links stay correct as the codebase moves.

## Scope: which files get documented (`.2brainignore`)

`2brain` asks once per repository which paths to document, and persists the answer to `.2brainignore` at the repo root:

```text
[include]
src/**

[exclude]
**/*.test.ts
docs/**
```

Both sections take gitignore-syntax patterns matched against repo-relative paths — `src/**`, `**/*.test.ts`, `!keep/this.ts`. `[include]` restricts the documented set (empty = everything), `[exclude]` removes from it (empty = nothing), and exclude always wins. The file is hand-editable; the prompt only exists to write it the first time.

```bash
2brain <repo> --exclude '**/*.test.ts,docs/**'   # set it non-interactively (persists)
2brain <repo> --include 'src/**,api/**'          # document only these
2brain <repo> --rescope                          # re-ask the prompt
REPO_INCLUDE=... REPO_EXCLUDE=... 2brain <repo>  # override for one run, no persistence
```

Precedence: `--include`/`--exclude` > `REPO_INCLUDE`/`REPO_EXCLUDE` > `.2brainignore` > the interactive prompt > everything.

**Scope is a documentation filter, not an extraction filter.** It decides which files get a wiki page — and therefore which modules exist and what reaches the vault. graphify still extracts everything, so the dependency graph stays complete and neighbour expansion still sees the real topology. Note that narrowing the scope prunes the pages that fall outside it, and widening it later costs one LLM call per file to regenerate them.

> Scope alone will not make a vault readable — excluding tests and docs takes a 430-file repo to 285, still far too many notes. That is what the module tier is for; scope is for cost control and for keeping noise out of the graph.

## Vault layout

When a vault is present, a run produces:

```text
vault/Projects/<repo-name>/
├── Notes/                     # yours, never touched
└── Generated/
    ├── Modules/               # INDEX.md + one note per module  ← what you read
    └── Architecture/          # CodeBoarding component pages + Mermaid diagrams
```

Per-file wiki pages are **not** mirrored: they stay in `<repo>/.2brain/llm-wiki/` where the AI reads them. Earlier versions did mirror them flat into `Generated/`; the next wiki run clears that legacy output automatically and reports how many notes it removed.

**The mirror is exact, both directions.** `Generated/Modules/` and `Generated/Architecture/` are re-synced from `.2brain/wiki/` and `.2brain/arch/` on every `wiki`/`arch` run: changed notes are re-copied, and any vault note whose source note no longer exists is deleted — not just skipped. So removing a module (delete its files, or narrow `.2brainignore` until it has none left) removes that module's page from `.2brain/wiki/` *and* from the vault on the next run; editing a file updates its module's note in both places the same way. As with per-file pruning, this only fires once the **graph** layer has seen the change — run a bare `2brain <repo>` (or `2brain graph <repo>` first) rather than `2brain wiki <repo>` alone after deleting or renaming files.


## Re-running: what recomputes, what is cached

2brain is designed to be re-run constantly. Only the three LLM-backed layers are cached; everything else is deterministic and rebuilt every time (milliseconds, no tokens).

| Layer | Cached in | Re-runs when |
|---|---|---|
| Graph | `.2brain/graphify-out/manifest.json` | a file changed (delegated to `graphify update`) |
| LLM Wiki | `.2brain/llm-wiki/.llm-wiki-cache.json` | the source file's SHA-256 changed, or the page is missing |
| Wiki | `.2brain/wiki/.wiki-cache.json` | any per-file page inside the module changed, or its file set moved |
| Arch | `.codeboarding/analysis.json` | every arch run (incremental if the baseline exists, full otherwise) |
| Execution / Memory / Index / Context / Injection | *(not cached)* | always — they are free |

**Creating, editing, deleting files.** Uncommitted and untracked changes count, so you do not have to commit before refreshing. A new file gets a wiki page and a deleted file's page is pruned — but only after the graph layer has seen it, so use a bare `2brain <repo>` (graph runs first) rather than `2brain wiki <repo>` alone when the file set changed.

**Switching model or preset invalidates nothing.** The wiki cache hashes source bytes, not the model. To re-document with a better model, ask explicitly: `--force-all`.

**After a failed run — or a deliberate pause** (Ctrl+C included), retry at layer granularity — completed layers are cache hits, so only the layer that died (or that you interrupted) costs anything. The wiki layer resumes page-by-page: its cache is saved after every page, so killing it at page 300 of 430 re-uses those 300 for free. The exception is `arch`: CodeBoarding writes its baseline only on success, so a crashed or paused arch run leaves nothing to resume from and the next attempt is another full analysis.

> Full mechanics, per-event breakdown and reset recipes: **[2brain-internals.md §7](2brain-internals.md#7-change-response--what-each-layer-does-when-things-change)**.


## Semantic retrieval model

`repo-index.json` stores chunked vectors from:

- `.2brain/*` textual artifacts
- runtime metadata
- persisted repo memory entries

Querying uses cosine similarity over TF-IDF vectors plus query expansion from top-ranked chunks, then returns ranked context snippets.

## State model

2brain writes `.2brain/.2brain-state.json` with:

- baseline git commit (`head`)
- stale threshold (`threshold`)
- per-layer metadata (`layers.execution`, `layers.memory`, `layers.index`, `layers.context`)

`2brain check` compares git changes since the baseline commit while excluding generated artifacts.

## AI target selection and injections

All integrations use one canonical source:

- `.2brain/REPO_CONTEXT.md`

When `--ai-target` is not passed, 2brain prompts a small CLI selection (non-interactive runs default to `neutral`):

- `claude`
- `copilot`
- `cursor`
- `neutral` (local models/custom setups; no editor-specific file generation)

Generated outputs by selection:

- Claude: managed block in `CLAUDE.md`
- Copilot: managed block in `.github/copilot-instructions.md`
- Cursor: `.cursor/rules/2brain.mdc`
- Neutral: no claude/copilot/cursor files

## 2brain configuration (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `REPO_PRESET_GRAPH` | `smart` | Preset used for graphify extraction (`2brain graph`) |
| `REPO_PRESET_WIKI` | falls back to `REPO_PRESET_GRAPH` | Preset used for wiki page generation (`2brain wiki`) |
| `REPO_PRESET_ARCH` | falls back to `REPO_PRESET_WIKI` → `REPO_PRESET_GRAPH` | Preset used for the architecture layer (`2brain arch`); ollama/openai/anthropic only |
| `COPILOT_GITHUB_TOKEN` | — | Token for a `copilot-cli` preset (fine-grained PAT with the "Copilot Requests" permission); see [docs/2brain-quick.md](2brain-quick.md#configuration-reference) |
| `REPO_AI_TARGET` | — | Optional default AI target (`claude`, `copilot`, `cursor`, `neutral`) |
| `REPO_STALE_THRESHOLD` | `5` | Files-changed threshold for stale warnings (`0` disables warning mode) |
| `REPO_WIKI_AUTO` | — | Set to `1` before `2brain hook` to auto-refresh the wiki after each commit |

Shared variables (`LINUX_USERNAME`, `DEFAULT_PRESET`, `PRESET_*`, API keys, Ollama tuning) are documented in **[docs/2brain-quick.md](2brain-quick.md#configuration-reference)**.

For a single-page comparison of every provider type (API vs CLI, credentials, and
which commands each works with), see **[docs/presets.md](presets.md)**.

---

See the main [README](../README.md) for installation, the shared model cache, and troubleshooting.
