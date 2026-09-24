# 2brain — fix plan

Fixes every issue in [ANALYSIS.md](ANALYSIS.md). Issue IDs (E1, C2, …) refer to that file.

Ground rules (from CLAUDE.md and project feedback):

- **Replace, don't shim.** No fallbacks that keep the old output shape.
- **Generated artifacts are disposable.** No migration step for existing `.2brain/` trees; the
  next run just rewrites them.
- **Deterministic first.** Phases 1-4 cost zero LLM tokens.
- **Every fix gets a pure-logic test in `tests/`.** They run on the host in seconds.

Validation target for every phase: `../boilerplate-node-backend`.

## Decisions

| Topic | Decision |
|---|---|
| Hook (phase 2) | Auto-install only where it is private and collision-free (git's own hooks dir; husky via an excluded `.husky/post-commit`). Otherwise print a note with the lines to add |
| Tests in the module tier (phase 5) | One note for all of `tests/**` |
| Arch budget (phase 6) | No budget feature. Only an automatic time estimate (from project size), printed before arch starts |
| Query (phase 4) | Keyword fixes only, no embeddings. Revisit only if the four test queries still fail |
| GRAPH_REPORT (phase 3) | Dropped from routing. God nodes + hyperedges inlined into REPO_CONTEXT.md |

---

## Order at a glance

| Phase | Fixes | LLM cost | Why this order |
|---|---|---|---|
| 1. What the AI reads is true | E1-E6, C1, C2, C5 | none | False facts are worse than missing ones |
| 2. The hook actually runs | H1 | none | Small; unblocks keeping artifacts fresh |
| 3. Routing points at the right pages | C3, C4 | none | Small; builds on phase 1's injection changes |
| 4. Query finds the obvious answer | Q1 | none | Self-contained in `index.py` |
| 5. Module tier spends its slots well | M1-M3 | ~10 module notes regenerate | Changes vault output |
| 6. Arch says how long it will take | A1 | investigation only | Needs a CodeBoarding investigation first |
| 7. Loose ends | S1, S2, D1 | none | Trivial; can ride along with any phase |

---

## Phase 1 — what the AI reads is true

### 1.1 Make EXECUTION.md repo-agnostic · E1

- **File:** `scripts/repo/execution.py`, `_render_markdown`.
- **Change:**
  - Delete the fixed sentences: the pip sentence, the "2brain CLI wrapper" exception, the
    "Platform variants … CPU/Windows" paragraph and the `CONTAINER_ENGINE` mention.
  - Keep only what is read from the target repo: file names, services, images, mounts,
    depends_on.
  - The run pattern stays generic: `docker compose -f <file> …`, with no engine claims.
- **Where the deleted facts go:** they are true for knowledge-hub itself, so they move to
  knowledge-hub's own hand-written `CLAUDE.md` (outside the managed block).
- **Test:** render with a compose fixture and assert that none of `pip`, `2brain` or
  `windows` appears.

### 1.2 Quick Commands by priority, not file order · E2

- **File:** `execution.py`, `_quick_commands`.
- **Change:** two passes, same 20 cap:
  1. **Canonical names first**, in a fixed order: `test`, `build`, `dev`, `start`, `lint`,
     `format`, `check`, `typecheck`/`ts-check`. Exact match only.
  2. **The rest** of the keyword matches, in file order, until the cap.
- **Test:** a `package.json` fixture with 25 `lint:*`/`check:*` scripts before `test`. Assert
  that `npm run test` is in the output and is first.

### 1.3 Find every compose file · E3

- **File:** `execution.py`, replacing `_COMPOSE_FILES` with a discovery helper.
- **Change:** at the repo root, glob `compose.y*ml`, `compose.*.y*ml`, `docker-compose.y*ml` and
  `docker-compose.*.y*ml`. Sort with the base file first, then the variants alphabetically.
- **Test:** a fixture directory with base + `.production` + `.test` → all three listed.

### 1.4 Indentation-agnostic compose parsing · E4

- **File:** `execution.py`, `_read_compose_services`.
- **Change:**
  - Detect the indent unit from the first non-comment line under `services:`.
  - Derive the service level (1 unit) and key level (2 units) from it, and drop the literal
    `indent == 2` / `indent == 4` checks and the `^  ` regex.
- **Why not PyYAML:** it is not a declared dependency, and this extractor only needs four keys.
  Revisit only if a real repo breaks the line parser (anchors and merge keys already pass
  through harmlessly).
- **Test:** the same services fixture at 2-space and at 4-space indent must give identical
  output.

### 1.5 Migrations from tracked files only · E5

- **File:** `execution.py`, `_read_migrations`.
- **Change:**
  - Build candidate directories from `git ls-files`, falling back to a walk that prunes
    `node_modules`, `.git` and dot-dirs when the repo is not a git repo.
  - Match directory *paths* against the existing glob list.
  - This respects `.gitignore` for free, and it is faster than `**` over `node_modules/`.
- **Test:** fixture with `node_modules/x/migrations/` and `db/migrations/` → only
  `db/migrations` reported.

### 1.6 Required env without a house convention · E6

- **File:** `execution.py`, `_read_required_env` + render.
- **Change:** when no `REQUIRED` header exists, print one pointer line:
  "`.env-example` defines N variables — copy it to `.env`". No guessing at which ones are
  required.
- **Test:** `.env-example` without the header → pointer line with the correct N.

### 1.7 One commit, captured once · C1

- **Files:** `scripts/repo.py` (`_graph`, `_build_layers`, `_write_state`),
  `scripts/repo/injection.py`.
- **Change:**
  - Resolve HEAD **once, when graph extraction starts**, and pass that value down.
  - `_build_layers` stops calling `_resolve_head()` itself.
  - Wiki/arch runs already pin the prior head (`_refresh_state_layers`); they pass that same pinned
    value to injection.
  - Result: state, REPO_CONTEXT, CLAUDE.md and GRAPH_REPORT all state the same commit.
- **Test:** call `_build_layers` with an explicit head while the fake repo's HEAD is different.
  Assert the injected stamp equals the explicit head.

### 1.8 Per-file freshness rule · C2

- **File:** `injection.py`, `_freshness_note`.
- **New text (shape):**
  > Artifacts describe commit `<baseline>`. Before relying on a wiki page, check its source:
  > `git diff --quiet <baseline> -- <file>` (and `git status` for uncommitted edits). Changed →
  > prefer the source for that file and say so. Unchanged → trust the page.
- **Why:** committing the artifacts moves HEAD, so any HEAD comparison is permanently false. A
  per-file diff against the baseline commit is exact, and it ignores the artifact commit itself.
- **Test:** snapshot test of the rendered rule.
- **Note:** once GRAPH_REPORT is dropped from routing (3.1), this is the only freshness
  statement the AI sees.

### 1.9 No duplicate routing in CLAUDE.md · C5

- **File:** `injection.py`, `_claude_inline`.
- **Change:** the Claude block keeps only the directive line and `@.2brain/REPO_CONTEXT.md`.
  Copilot and Cursor keep the inline rules, because they cannot import.
- **Test:** Claude block does not contain `## Where to look`; Copilot block does.

### 1.10 `reindex` also regenerates EXECUTION.md

- **File:** `scripts/repo.py`, the reindex path.
- **Why:** EXECUTION.md is deterministic and free, yet today only a full `graph` run rebuilds
  it. Validating phase 1 should not require re-running graphify.

**Phase 1 done when:** `2brain reindex ../boilerplate-node-backend` produces:

- an EXECUTION.md with `npm run test` in Quick Commands, 4 compose files with their services,
  no migrations section noise, and no knowledge-hub prose;
- one commit hash across all four artifacts.

---

## Phase 2 — the hook actually runs · H1

- **File:** `scripts/repo.py`, hook install, `_hook_is_ours` and the full-run prompt (`:466`,
  `:511`, `:541`). One shared helper decides *where* the hook goes; all three call sites use it.
- **Rule (decision):** install automatically only where it is private to the user and can't
  collide. Anywhere else, write nothing and print a short note telling the user what to add.

### 2.1 Where the hook goes

Detection is `git rev-parse --git-path hooks`: the folder git actually runs hooks from. It
honours `core.hooksPath` and worktrees.

| Detected situation | Action | Why it is safe |
|---|---|---|
| Git's own hooks folder (`.git/hooks`, or a `core.hooksPath` outside the working tree), no `post-commit` there | **Install** `post-commit` | That folder is never committed |
| Same folder, `post-commit` already written by 2brain | **Rewrite in place** | Same file, no duplicate |
| Same folder, `post-commit` written by someone else (e.g. lefthook, pre-commit) | **Note only** | Replacing it would break their tool |
| Husky (`core.hooksPath` ends in `.husky/_` and `.husky/_/h` exists), no `.husky/post-commit` | **Install** `.husky/post-commit` and add it to `.git/info/exclude` | Husky runs it; git ignores it; never pushed |
| Husky, `.husky/post-commit` untracked and ours | **Rewrite in place** | Same file, no duplicate |
| Husky, `.husky/post-commit` tracked or not ours | **Note only** | It's a shared file; editing it would put a diff in the user's repo |
| `core.hooksPath` points to any other folder inside the working tree | **Note only** | Unknown hook manager, likely committed |

- **"Ours"** = the file contains the `# 2brain:start` marker.
- **The note** prints the exact lines to paste and the file to paste them into. For example:
  "Add this to `.husky/post-commit` — 2brain didn't, because that file is shared."
- **The full-run prompt** (`:541`) uses the same helper, so it stops offering an install that
  would do nothing. In "note only" cases it prints the note once instead of asking.

### 2.2 Hook body in POSIX `sh`

- Husky runs hook files with `sh -e`, ignoring the shebang, so today's `[[ ]]` bash syntax
  breaks there.
- One body for every case. It only prints; it never blocks or changes a commit.

### 2.3 Tests

- `hooksPath` unset → `.git/hooks/post-commit` installed.
- Worktree (`.git` is a file) → installed under the common git dir.
- Foreign `.git/hooks/post-commit` → untouched, note printed.
- Husky, no `.husky/post-commit` → file created, listed in `.git/info/exclude`, `git status`
  clean.
- Husky, running `2brain hook` twice → one file, one exclude line (no duplicates).
- Husky, tracked `.husky/post-commit` → untouched, note printed.
- `hooksPath=.githooks` (inside the working tree) → nothing written, note printed.
- Hook body runs under `dash` without errors.

**Done when:** `git commit` in boilerplate prints the 2brain stale warning, and `git status`
there stays clean.

---

## Phase 3 — routing points at the right pages

### 3.1 First contact → OVERVIEW + module index · C3

- **File:** `injection.py`, `_routing_rules` + `_probe_artifacts`.
- **Change:**
  - **First contact:** `.2brain/llm-wiki/OVERVIEW.md`, then `.2brain/modules/<repo>_INDEX.md`
    for the module map.
  - **GRAPH_REPORT: dropped from routing** (decision). On boilerplate its communities are weakly
    cohesive (0.04-0.07), its "surprising connections" are false links, and its suggested
    questions are noise. The file itself stays: it costs nothing and `query` still indexes it.
  - **Inline its two useful sections into REPO_CONTEXT.md** (about 15 lines, parsed from
    GRAPH_REPORT.md after each graph run):
    - `## Most-used code` — the top 10 god nodes, framed as "change these with care".
    - `## Cross-cutting flows` — the hyperedge titles (e.g. "Webhook Delivery Pipeline").
    - Missing section in the report → omit that block silently.
- **Tests:**
  - With OVERVIEW + INDEX present, the first-contact rule names them.
  - No rule mentions GRAPH_REPORT.
  - Fixture report → both inlined blocks rendered; a report without them → blocks absent.

### 3.2 Neutralise graphify's freshness advice · C4

- **File:** `scripts/repo.py`, right after `_run_graphify` writes GRAPH_REPORT.md.
- **Change:** rewrite the report's `## Graph Freshness` section. Replace every
  `graphify update .` / `git rev-parse HEAD` line with `2brain check <repo>` and
  `2brain <repo>`. Also rewrite `graphify query` in `## Knowledge Gaps` to `2brain query`.
- **Why post-process instead of patching graphify:** graphify is pinned (`graphifyy==0.9.13`)
  and ships breaking changes often. A text rewrite on our side survives version bumps.
- **Fragility guard:** if the section heading is not found, leave the file alone and print a
  warning. Never fail the run over it.
- **Test:** fixture report text in → rewritten section out. A report without the section is
  unchanged.
- **First:** confirm C4's worst case (the root `graphify-out/`) by running `graphify update .`
  in a scratch copy. That only changes how the analysis describes it, not the fix.

---

## Phase 4 — query finds the obvious answer · Q1

- **File:** `scripts/repo/index.py` (`_tokenize`, chunk records, scoring). Stays pure stdlib,
  so host mode is unaffected.
- **Change, in this order, measuring after each step:**
  1. **Stop words.** A small fixed English list (`how`, `do`, `does`, `i`, `the`, `what`,
     `where`, …), applied to query *and* documents.
  2. **Light suffix stemmer.** Strip `ing`/`ed`/`es`/`s` with a minimum stem length. This
     replaces the current plural-only rule.
  3. **Path/title field.** Tokens from the source path and the first `#` heading are stored
     as a separate field and weighted ×3 (tunable). `strategic-ddd.md` then wins
     `strategic DDD …`.
  4. **Expansion only on a confident seed.** Skip query expansion when the top score is not
     clearly ahead of #2, so a wrong top hit can't reinforce itself.
- **Regression fixture:** `tests/test_index.py` gets a small synthetic corpus that reproduces
  the four ANALYSIS.md queries in miniature:
  - an EXECUTION-like page vs. test-file pages;
  - a doc *named* after the topic vs. pages that cite it.
  Each case asserts the right source is in the top 3.
- **No embeddings (decision).** Search by meaning through Ollama would need the model server
  at query time, which breaks the ~50 ms host-mode `query`. The main caller is Claude, which can
  rephrase into keywords or fall back to `grep`. Reconsider only if steps 1-4 fall short on the
  boilerplate queries.

**Done when:** all four ANALYSIS.md queries return the right source in the top 3 on
boilerplate.

---

## Phase 5 — module tier spends its slots well

- **File:** `scripts/repo/modules.py`, `select_modules`, `_mermaid_overview`,
  `_mermaid_local`, adjacency.

### 5.1 Fold co-located tests into their module · M2

- Before selection, files under a `tests/`, `test/` or `__tests__/` directory that sits *inside*
  another directory count toward that parent.
  - `src/modules/account/tests/**` → `src/modules/account/`.
- Top-level test trees (`tests/` at the root) are unaffected by this step.

### 5.2 Merge test trees before domain code · M1

- The merge loop's key changes from `(size, name)` to `(is_test_tree, size, name)`, and test
  trees merge first.
- Boilerplate outcome: the six `tests/**` notes collapse toward one `tests/` note. That frees
  slots, so `access`, `antibot`, `audit-logs`, `addresses` and `api-keys` keep their own notes.
- `src/kernel` should then also surface. If it doesn't, add a rule: never merge a directory
  whose files have the highest graph in-degree. Only if needed, and measure first.

### 5.3 Drop ROOT edges from diagrams · M3

- The ROOT module keeps its note and its `## Files` list.
- ROOT stops being drawn as an edge in the module map and in other modules' local diagrams.
- Its own note still shows what it links to.

**Tests (`tests/test_modules.py`):**

- A synthetic file list shaped like boilerplate: 18 domain modules, co-located tests, a root
  `tests/` tree with 6 subdirs.
- Assert that every domain module keeps a note, that co-located tests land in their parent,
  and that the count is ≤ 30.
- Assert that ROOT does not appear in any overview edge.

**Cost when rolled out:** changed module membership invalidates those modules' cache digests,
so about 10 module notes are regenerated by the LLM on the next `2brain wiki`. Per-file pages
are untouched.

---

## Phase 6 — arch says how long it will take · A1

Investigation first. The answers decide the shape of the fix.

### 6.0 Investigate (no code)

1. **Is a killed run's `analysis.json` renderable?**
   - Run `_render_markdown` (the inline renderer, `arch.py:279`) on boilerplate's
     current partial `.codeboarding/analysis.json`.
   - Check whether the pages are complete enough to show.
2. **Does CodeBoarding reuse `cache/meta_agent_llm.sqlite` across runs?** If yes, a rerun after
   a kill is partly cached, and "nothing is kept" is only half true.
3. **Can the run's duration be predicted?** Use the step counts in the log: 42
   `_step_llm_analysis`, 40 `_step_api_surfaces` and 35 `_step_relation_analysis` over
   ~2 hours. The goal is a seconds-per-file figure, recorded in `.2brain-state.json` after
   each arch run.

### 6.1 Estimate up front

- `2brain arch --dry-run` also prints the file count and an estimated duration.
- The estimate comes from the last recorded rate, or a conservative default on first run.
- A full run prints the same estimate before it starts.

### 6.2 No budget (decision)

- **No time budget feature.**
- **Why:** the budget would be "how long the PC can stay on", which 2brain can't know from the
  project. A manual setting was judged useless.
- **What stays:** the automatic estimate from 6.1, computed from project size, printed before
  arch starts. Arch then always runs.
- **Never kill a running arch.** Stopping mid-way loses all its work.

### 6.3 Salvage (only if 6.0 step 1 says yes)

- When `analysis.json` exists without `fingerprint.json`, render its pages into `.2brain/arch/`
  with `partial: true` in the frontmatter and a one-line banner.
- The existing guard stays: still no baseline, and the next run is still full.
- The partial pages are replaced when the full run succeeds.

### 6.4 Progress

- Tail CodeBoarding's log and print one line per completed step, with an ETA.

**Also, after one complete arch run:** re-check component naming (the "not assessable" note in
ANALYSIS.md).

---

## Phase 7 — loose ends

| ID | File | Change | Test |
|---|---|---|---|
| S1 | `scripts/repo/memory.py` | Always write `repo-memory.json` (an empty list is valid), so the state file never points at a missing file | Empty memory → file exists, `[]` |
| S2 | `scripts/shared/config.py` | Add `.gitignore` to `GENERATED_FILES`, same precedent as `CLAUDE.md`. Keep `.2brainignore` counted: a scope change is a real reason to re-run the wiki | `check` after a fresh run reports 0 changes |
| D1 | `docs/2brain.md:42`, `:90` | Say bare `2brain <repo>` = `all` (graph → wiki → arch) | — |

---

## Final validation on boilerplate

1. `pytest` passes, and `ruff` is clean.
2. `2brain reindex ../boilerplate-node-backend` covers phases 1 and 3.
   - Read EXECUTION.md, REPO_CONTEXT.md and the CLAUDE.md block by eye.
3. `2brain check` passes right after a run (0 self-inflicted changes).
4. `git commit` in boilerplate prints the 2brain hook output.
5. The four query cases from ANALYSIS.md return the right sources.
6. `2brain wiki` regenerates only the affected module notes; the vault shows the new module
   set.
7. `2brain arch --dry-run` prints an estimate; then one complete arch run, in a window long
   enough.
