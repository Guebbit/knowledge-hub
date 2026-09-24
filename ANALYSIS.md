# 2brain — analysis of wrong or missing features

Test subject: `../boilerplate-node-backend`. It is a Node/TypeScript repo of about 1,375 tracked
files, run with the local `qwen3.8:27b` model.

Scope of this document:

- **Only defects.** Working features are left out.
- **Not counted as defects:**
  - Artifacts lagging behind HEAD. The repo is being worked on right now.
  - The unfinished arch run. The machine was switched off after its 2-hour window.

Severity:

- **High** — the AI is told something false, or a feature silently does nothing.
- **Med** — the output is noticeably worse than it should be.
- **Low** — cosmetic or inconsistent.

---

## Summary

| ID | Area | Severity | One-line problem |
|---|---|---|---|
| E1 | EXECUTION.md | High | Prose written for knowledge-hub is stamped into every target repo |
| E2 | EXECUTION.md | High | Quick Commands keeps the first 20 matches, so `npm run test` is dropped |
| E3 | EXECUTION.md | Med | Only knowledge-hub's two compose file names are looked for |
| E4 | EXECUTION.md | Med | Compose parser assumes 2-space indent, so it finds zero services |
| E5 | EXECUTION.md | Med | Migration search walks `node_modules/` and `.claude/worktrees/` |
| E6 | EXECUTION.md | Low | "Required env" only understands knowledge-hub's own `.env-example` layout |
| C1 | Context | High | Three different commits are stamped as "the" generation commit |
| C2 | Context | High | The freshness rule compares against HEAD, so it always fires once artifacts are committed |
| C3 | Context | Med | "First contact" routes to a 1,425-line GRAPH_REPORT, not the real orientation pages |
| C4 | Context | Med | GRAPH_REPORT tells the AI to run `graphify update .` directly |
| C5 | Context | Low | CLAUDE.md loads the "Where to look" rules twice |
| Q1 | Query | Med | Natural-language questions miss the document that obviously answers them |
| M1 | Modules | Med | The 30-module cap merges by size, so domain modules lose to test folders |
| M2 | Modules | Med | Co-located `tests/` dirs become separate modules, splitting their domain |
| M3 | Modules | Low | The ROOT pseudo-module links to nearly everything, which clutters the module map |
| H1 | Hook | High | The hook is written to `.git/hooks`, ignoring `core.hooksPath` (husky) and worktrees |
| A1 | Arch | Med | No time awareness: no estimate, no budget, a stopped run keeps nothing |
| S1 | State | Low | The state file points at `repo-memory.json`, which does not exist when memory is empty |
| S2 | Check | Low | 2brain's own `.gitignore` managed block counts as a source change |
| D1 | Docs | Low | `docs/2brain.md` says a bare `2brain <repo>` runs only `graph` |

---

## EXECUTION.md — `scripts/repo/execution.py`

EXECUTION.md is the file the router sends the AI to for "how do I run / build / test this?"
Most of the defects below come from one root cause: the extractor was written against
knowledge-hub itself.

### E1 — knowledge-hub prose leaks into every repo · High

- **Where:** `_render_markdown`, `execution.py:410-446`.
- **What happens:** when the target repo has a compose file, these fixed sentences are written:
  - "there is no bare-metal `pip install` path for the pipeline itself"
  - "Exception: the `2brain` CLI wrapper runs `query` and `check` directly on the host…"
  - "`docker-compose.windows.yml` is standalone… the CPU/Windows definition"
  - "`CONTAINER_ENGINE` in `.env`"
- **Evidence:** `boilerplate-node-backend/.2brain/EXECUTION.md` lines 5-13. That is a Node
  repo with no pip, and 2brain is not its CLI.
- **Impact:** the AI reads false runbook facts about the repo.

### E2 — Quick Commands loses `test` · High

- **Where:** `_quick_commands`, `execution.py:358-389`, with `_MAX_QUICK_COMMANDS = 20`.
- **What happens:**
  - Every script whose name contains a keyword is collected in `package.json` order.
  - The list is then cut at 20.
  - Boilerplate has more than 20 matches before `test`, so `test`, `test:unit` and every
    `test:*` script are cut.
- **Impact:** the section called "Quick Commands" leaves out the single most common command.

### E3 — hardcoded compose file names · Med

- **Where:** `_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.windows.yml")`,
  `execution.py:44`.
- **What happens:** boilerplate's `docker-compose.production.yml`, `.test.yml` and
  `.proxy.yml` are ignored. So are the modern names `compose.yml` and `compose.yaml`.

### E4 — compose parser only reads 2-space YAML · Med

- **Where:** `_COMPOSE_SERVICE_PATTERN = r"^  ([A-Za-z0-9_.-]+):\s*$"` (`:49`), plus the
  `indent == 2` / `indent == 4` checks in `_read_compose_services` (`:267`).
- **What happens:** boilerplate indents with 4 spaces, so zero services are found. The section
  prints the heading `### docker-compose.yml` with nothing under it.

### E5 — migration search walks dependencies · Med

- **Where:** `_MIGRATION_PATH_GLOBS` (`:29-36`) is run through `repo.glob("**/migrations")`
  in `_read_migrations` (`:242`).
- **What happens:**
  - The search ignores `.gitignore` and the scope.
  - All four "migration directories" it reported are inside `node_modules/` or
    `.claude/worktrees/*/node_modules/`.
  - The repo has no migrations of its own.
- **Also:** walking `node_modules/` with `**` is slow on big repos.

### E6 — required env needs knowledge-hub's header convention · Low

- **Where:** `_read_required_env` with `_ENV_SECTION_HEADER_PATTERN` (`:51`, `:333`).
- **What happens:**
  - The parser only reads a `# ── REQUIRED ──` section.
  - Boilerplate's `.env-example` is 44 KB and has no such header, so the section silently
    disappears.
- **Missing behaviour:** when the convention is absent there is no fallback, such as listing
  the variables that have no default value.

---

## Context and bridge — `scripts/repo/injection.py`, `scripts/repo.py`

### C1 — three different "generation commits" · High

| Artifact | Commit it states | Where it comes from |
|---|---|---|
| `.2brain-state.json` `head` | `ad8d8602` | pinned baseline (correct) |
| `GRAPH_REPORT.md` "Built from commit" | `ad8d8602` | graphify |
| `REPO_CONTEXT.md` + `CLAUDE.md` stamp | `d0616e30` | `_resolve_head()` at write time, `repo.py:578` |

- **What happens:** the stamp shown to the AI is HEAD at the moment the context file was
  written, three hours into the run. It is not the commit the graph and wiki were built from.
- **Impact:** the AI is told the artifacts are newer than they are.

### C2 — the freshness rule can never pass · High

- **Where:** `_freshness_note`, `injection.py:89-95`.
- **Rule text:** "If `git rev-parse HEAD` differs, prefer the source over these artifacts."
- **Why it always fires:** the documented workflow is to commit the artifacts. That commit is a
  new HEAD, so HEAD differs from the stamp on every session after the first commit.
- **Impact:** the AI is told to distrust every artifact, all the time. The rule should be
  per-file: a page is only suspect when its own source file changed since the baseline.

### C3 — "first contact" points at the wrong page · Med

- **Where:** `_routing_rules`, `injection.py:121-126`.
- **What happens:**
  - The router sends first-contact orientation to `GRAPH_REPORT.md`.
  - On boilerplate that file is 1,425 lines with 229 listed communities, which is not
    orientation.
  - The pages written for orientation are never routed to: `.2brain/llm-wiki/OVERVIEW.md`
    (62 lines) and `.2brain/modules/<repo>_INDEX.md`, the module map.

### C4 — GRAPH_REPORT tells the AI to bypass 2brain · Med

- **Where:** graphify's own report template. 2brain does not post-process it.
- **Text:** "Run `graphify update .` after code changes (no API cost)."
- **What happens:**
  - An AI following that runs graphify outside 2brain, without `GRAPHIFY_OUT`.
  - In the best case graphify is not installed on the host and the command fails.
  - In the worst case graphify writes a second `graphify-out/` at the repo root and skips
    2brain's dedup patch.
- **Needs checking:** the second outcome is inferred from how `GRAPHIFY_OUT` is documented.
  It was not reproduced.

### C5 — routing rules duplicated in CLAUDE.md · Low

- **Where:** `_claude_inline`, `injection.py:137`.
- **What happens:** the managed block contains `## Where to look` and also `@`-imports
  `REPO_CONTEXT.md`, which contains the same section. Claude gets both copies.

---

## Query — `scripts/repo/index.py`

### Q1 — natural-language recall is weak · Med

Observed on boilerplate:

| Query | Right answer | Got |
|---|---|---|
| `how do I run tests?` | `EXECUTION.md`, `docs/reference/tests.md` | 5 wiki pages of individual test files |
| `test script npm run test` | `EXECUTION.md` | ✅ `EXECUTION.md` first |
| `strategic DDD module boundaries` | `docs/theory/strategic-ddd.md` | 5 `src/modules/*/index.ts` wiki pages that *cite* that doc |
| `how does checkout create an order and reserve inventory?` | `src/modules/cart/services/checkout.ts` | the admin order controller and inventory pages; checkout absent |

Keyword queries work. Question-shaped queries do not.

Probable causes, all in `index.py`:

- **No stop-word list.** `how`, `do`, `i` and `does` get weight.
- **No stemming,** beyond stripping a trailing `s` in `_tokenize` (`:87-95`). So `run` never
  matches `runs`/`running`, and `test` never matches `testing`.
- **No boost for the path or title.** A document *named* `strategic-ddd.md` ranks below pages
  that mention its name once.
- **Many near-identical wiki pages crowd out the right one.** `_MAX_CHUNKS_PER_SOURCE = 1`
  (`:79`) stops one document from filling the results. It does not stop 20 near-identical wiki
  pages from filling them.
- **Query expansion reinforces the mistake.** It seeds from the (wrong) top hits
  (`_QUERY_EXPANSION_*`, `:64-68`).

---

## Module tier — `scripts/repo/modules.py`

### M1 — the merge picks by size, not by meaning · Med

- **Where:** `select_modules`, the merge loop at `modules.py:201-213`. It always merges the
  module with the fewest files into its parent.
- **Result on boilerplate (30 slots):**

| Got its own note | Folded into the catch-all `src/modules/` note |
|---|---|
| `tests/unit`, `tests/unit/infrastructure/adapters`, `tests/unit/infrastructure/http`, `tests/integration`, `tests/cross-cutting`, `tests/support` | `access` (8 files), `antibot` (9), `audit-logs` (17), `addresses` (19), `api-keys` (21) |
| `src/modules/account/tests`, `src/modules/orders/tests` | |

- **Also:** `src/kernel` (11 files, the core) is buried inside the generic `src/` note.
- **Impact:** in the vault, 5 real bounded contexts have no note, while 8 slots go to test
  folders.

### M2 — co-located tests split their domain · Med

- **What happens:** `src/modules/account/` has three notes: `account`, `account/controllers`
  and `account/tests`.
- **Why:** the split is by file count only, so a module's own tests compete with it for a slot.
- **What a reader wants:** one note per bounded context, with its tests described inside it.

### M3 — ROOT pseudo-module adds noise · Low

- **What happens:** the repo-root "module" (64 config files) is linked to 9 modules in the
  module map and to almost every module note.
- **Why:** `package.json`, `tsconfig.json` and `jest.config.js` reference everything.
- **Impact:** those edges are true but carry no information, and they clutter every diagram.

---

## Hook — `scripts/repo.py`

### H1 — the hook is installed where git never looks · High

- **Where:** `repo.py:466`, `:511` and `:541`, which all hard-code
  `<repo>/.git/hooks/post-commit`.
- **What happens:**
  - Boilerplate sets `core.hooksPath = .husky/_`, so git never runs `.git/hooks/post-commit`.
    The hook installs "successfully" and never fires.
  - In a git worktree `.git` is a file, not a directory, so `mkdir` / write fails.
- **Also:** the full-run prompt checks the same wrong path, so on a husky repo it keeps
  offering to install a hook that can never run.

---

## Arch — `scripts/repo/arch.py`

### A1 — no time awareness · Med

The run itself was not at fault: the machine was switched off after its window. What is
missing on 2brain's side:

- **No up-front estimate.** `--dry-run` only reports full vs incremental. It does not report
  expected duration or file count.
- **No progress or ETA while running.** CodeBoarding's log shows steps, but 2brain does not
  surface them.
- **No budget.** A run can't be told "stop cleanly after N minutes".
- **Nothing is kept when stopped.** Two hours of LLM work went into
  `.codeboarding/analysis.json` (written at 22:38, about 7 minutes before shutdown), but no
  `.2brain/arch/` pages were rendered from it. The partial-baseline guard (`arch.py:50-64`)
  correctly refuses to treat it as incremental. Nothing tries to salvage it for display.

Why it matters: with local models and a limited server window (the local-model-first
constraint), arch is the layer most likely to hit the window. It is also the only one that
cannot resume.

> Not assessable yet: the partial analysis named all 5 top-level components after
> scenarios/contracts, although 360 of its 431 files are under `src/`. Re-check component
> naming after one complete run before calling it a defect.

---

## State, check, docs

### S1 — state references a missing file · Low

- `.2brain-state.json` → `layers.memory.artifact = ".2brain/repo-memory.json"`.
- That file is not created when there are 0 entries. Every other listed artifact exists.

### S2 — 2brain's own writes look like source changes · Low

- **What happens:** `2brain check` listed `.2brainignore` and `.gitignore` among the changed
  files. Both were written by 2brain itself during the run.
- **Why:**
  - `GENERATED_FILES` (`shared/config.py:122`) already excludes `CLAUDE.md`, `.gitattributes`
    and `.graphifyignore`.
  - `.gitignore` also carries a managed block, but it is missing from that list.
  - `.2brainignore` is debatable. A scope change does not touch the graph, but it does change
    what the wiki should hold.
- **Impact:** a fresh run starts out one or two files "stale".

### D1 — docs contradict the CLI · Low

- `docs/2brain.md:42`: "`2brain <repo>` | Shortcut for `2brain graph <repo>`".
- `docs/2brain.md:90`: "`2brain <repo>` with no subcommand is a shortcut for `2brain graph`".
- The code (`repo.py:6`), the README and line 5 of the same doc all say a bare run is
  graph → wiki → arch.
