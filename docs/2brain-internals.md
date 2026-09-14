# 2brain — internals, logic & theory

This document explains *how* `2brain` works under the hood: what the moving parts are, how they combine, how incremental refresh is decided, and how staleness is detected. If you just want commands and examples, read **[2brain.md](2brain.md)** instead.

---

## 1. The core idea: one pipeline, seven layers

You're right that `2brain` is not a single feature — it's a **pipeline of independent layers that stack on top of each other**. Each layer produces one or more files under `.2brain/`, and every layer above consumes the ones below it.

```mermaid
flowchart TD
    A["1 · Graph extraction<br/>(graphify)"] --> B["2 · Execution knowledge"]
    A --> C["3 · Durable memory"]
    B --> D["4 · Semantic index"]
    C --> D
    A --> D
    D --> E["5 · Canonical context"]
    E --> F["6 · Editor injection"]
    A -.-> G["7 · Living wiki<br/>(optional)"]
    G --> D
    F --> H["8 · State / staleness"]
    D --> H
```

The design rule behind the whole thing: **one canonical source, zero duplicated AI summaries.** Everything funnels into `REPO_CONTEXT.md`, and the editor bridge files (Claude/Copilot/Cursor) only *point* at it — they never copy it. Regenerate once, every assistant sees the update.

A second rule: **fail-fast, no placeholders.** If a required artifact is missing (e.g. `GRAPH_REPORT.md`, `EXECUTION.md`), the run aborts rather than writing an empty or fake file. Layers refuse to build on a broken foundation.

Here's what each layer actually is.

### Layer 1 — Graph extraction (`graphify`)
The foundation. `2brain` shells out to the external `graphify` tool, which parses the codebase into a **dependency graph**: nodes are files, edges are relationships (imports, references). Output: `GRAPH_REPORT.md` (human/AI-readable) and `graph.json` (raw graph). Everything else keys off this graph. `graphify` honors `.gitignore`/`.graphifyignore` and skips heavy dirs (`node_modules`, `dist`, `.next`, …).

This is the only layer that calls an LLM as part of *extraction* (for semantic enrichment). The provider is chosen by preset and mapped to a graphify backend: `anthropic→claude`, `openai→openai`, `ollama→ollama`.

### Layer 2 — Execution knowledge (`EXECUTION.md`)
**Purely deterministic — no LLM.** It scrapes the repo for *how to run it*:
- `package.json` scripts, `Makefile` targets, `pyproject.toml` scripts (project/poetry/poe)
- GitHub Actions workflows (parsed for `run:` commands, including block scalars)
- Migration directories (Alembic, Prisma, Django, Flyway…) and tool-hint files

It then distills a short "Quick Commands" list by keyword-matching script names (`test`, `build`, `lint`, `start`, `dev`, `check`, `format`). This is the layer that lets an assistant answer "how do I run the tests?" without guessing.

### Layer 3 — Durable memory (`repo-memory.json` + `REPO_MEMORY.md`)
Facts you explicitly store with `2brain remember`. Three kinds: `fact`, `decision`, `runbook`. Entries are **deduplicated by `(kind, case-insensitive text)`** — re-remembering the same thing updates the existing entry instead of duplicating it. Each entry carries an `id` (SHA-256 prefix of `kind:text`), a `created_at`, and pointers to the git `head` and `index_revision` it was last synced against. The JSON is the source of truth; the `.md` is a human-readable mirror.

### Layer 4 — Semantic index (`repo-index.json`)
The retrieval engine behind `2brain query`. It chunks the text artifacts from layers 1–3 (plus runtime metadata and, if present, wiki pages) and builds a **TF-IDF vector index** served by cosine similarity. Full algorithm in §4.

### Layer 5 — Canonical context (`REPO_CONTEXT.md`)
A small, always-regenerated index page that lists the core artifacts, the current index metadata (provider, model, revision, chunk count, memory count), and the query commands. This is *the* file assistants are pointed at.

### Layer 6 — Editor injection (bridge files)
Writes one editor-specific file that references `REPO_CONTEXT.md`:
- **Claude** → a managed block in `CLAUDE.md` that `@`-imports `.2brain/REPO_CONTEXT.md` (Claude Code auto-loads `CLAUDE.md` and resolves `@`-imports, so this is the only file on the load path — nothing under `.claude/` is picked up on its own)
- **Copilot** → managed block in `.github/copilot-instructions.md`
- **Cursor** → `.cursor/rules/2brain.mdc` (a global always-apply rule)
- **Neutral** → nothing (for local/custom setups)

Regardless of target, this layer also writes the managed blocks that the
generated tree depends on:
- **`.graphifyignore`** → written **only when necessary**, and only listing what is necessary. graphify self-prunes just the single directory it writes to, so without an exclusion it re-ingests our own wiki, arch pages and `EXECUTION.md` as source on the next extraction — generated prose feeding the next generation of it. But graphify honors `.gitignore` too, so each candidate (`.2brain/`, `.codeboarding/`) is first put to `git check-ignore --no-index`; already-excluded ones are dropped, and when nothing survives the file is not created (an obsolete managed block from an earlier run is stripped, and the file removed if that leaves it empty). `.codeboarding/` is in our own managed `.gitignore` block, so in practice only `.2brain/` reaches the file. The block opens with a comment explaining what `.graphifyignore` is, since a target repo has no other record of where the file came from.
- **`.gitattributes`** → marks `.2brain/**` as `linguist-generated` so the committed artifacts collapse in reviews. Deliberately not `-diff`, which would suppress the textual diff locally too.
- **`.gitignore`** → excludes only the regeneration-only slice of `.2brain/`: graphify's raw `graph.json`/`manifest.json`/`.graphify_*` dumps (structural data, not prose — see §4's chunk selection), graphify's own AST/semantic cache, graphify's dated snapshot directories (which duplicate its live output), the module tier's incremental content-hash cache, and `.codeboarding/` (its canonical output is already mirrored into `.2brain/arch/`). Everything else — `llm-wiki/`, `modules/`, `arch/`, `EXECUTION.md`, `REPO_MEMORY.md`, `REPO_CONTEXT.md` — is committed on purpose, so a teammate without 2brain/graphify installed (or without hardware to regenerate) can still read and query it.

Injected blocks are wrapped in `<!-- 2brain:start --> … <!-- 2brain:end -->` markers and rewritten **only if the content changed** — so your own edits around them survive, and re-running is idempotent.

### Layer 7 — Living wiki (optional, `.2brain/llm-wiki/`)
One LLM-written Markdown page per source file, plus `OVERVIEW.md`. This is the only layer that's *incremental by design* (§3), because it's the expensive one — every page is an LLM call. Generated pages are folded back into the index (layer 4) so `query` can retrieve them.

**Audience: machines.** One page per file is the right granularity for retrieval and the wrong one for a human — see §8. These pages stay in the repo and are never mirrored into the vault.

### Layer 7c — Module tier (`.2brain/modules/`)
One note per meaningful directory, written from the per-file pages rather than from source, plus a hub note. Filenames are namespaced by repository (`<repo>_src_ui.md`, `<repo>_INDEX.md`). This is the human-facing tier and the only wiki-side output mirrored into the Obsidian vault. Modules are chosen top-down over the directory tree (subtree ≤ 40 documented files becomes a module; bigger trees split into children; the result merges upward until it fits 30 modules), and their edges are the file-level dependency graph lifted to module level. Rationale and the prior art it follows: §8.

### Layer 7b — Architecture layer (optional, `.2brain/arch/`)
The tier *above* the per-file wiki: component/subsystem narrative pages plus **Mermaid architecture diagrams**, generated by [CodeBoarding](https://github.com/CodeBoarding/CodeBoarding) (static analysis + LLM) behind a thin adapter (`scripts/repo/arch.py`). Also opt-in and expensive; also folded back into the index (layer 4). Two design points make it swappable and safe:
- **Isolation seam.** The CodeBoarding-specific surface is confined to a handful of helpers in `scripts/repo/arch.py` (`_run_codeboarding`, `_render_markdown`, `_codeboarding_python`, `_codeboarding_dir`, plus the `_RENDER_SCRIPT` and promo-stripping in `_clean_page`). CodeBoarding writes its native analysis + incremental baseline to `<repo>/.codeboarding/`; because this version's local mode emits only `analysis.json`, the adapter renders the Markdown itself (via `render_docs` in CodeBoarding's venv), then mirrors the pages into `.2brain/arch/` (the indexed, canonical copy). Replacing the generator later means reworking only those helpers — everything downstream keys off `.2brain/arch/`.
- **Deterministic provider.** CodeBoarding selects its LLM provider by which credential env var is set. Since the container may hold several keys at once, the adapter runs it with a scrubbed environment exposing only the selected provider's credentials (ollama/openai/anthropic; `claude-code` is rejected — no CLI backend). Telemetry is force-disabled.

Like the wiki, it deliberately does **not** move the staleness baseline.

### Layer 8 — State (`.2brain-state.json`)
The bookkeeping layer that makes staleness detection possible (§2). Records the git commit the artifacts were generated from, the stale threshold, and per-layer metadata.

---

## 2. How staleness detection works

The question "is this repo stale?" reduces to: **has the code drifted far enough from the commit the artifacts were built at?**

### The baseline
Every full run (`graph`, `reindex`, `remember`) ends by writing `.2brain/.2brain-state.json`:

```json
{
  "generated_at": "2026-07-11T…Z",
  "head": "<git commit SHA at generation time>",
  "threshold": 5,
  "layers": { "execution": {…}, "memory": {…}, "index": {…}, "context": {…} }
}
```

The `head` field is the **baseline commit** — the anchor everything is measured against.

> **Important nuance:** `2brain wiki` deliberately does **not** rewrite the state. The graph baseline must only move when `graphify` itself re-runs; otherwise a wiki refresh would make `check` report a genuinely stale graph as "fresh."

### The measurement (`2brain check`)
1. Read the baseline commit from state. Abort if the commit no longer exists (history was rewritten).
2. Compute the set of **changed files since the baseline**, which is the union of:
   - **committed drift** — `git diff --name-only <baseline>..HEAD`
   - **working-tree drift** — `git status --porcelain` (modified, staged, *and* untracked files)
3. Exclude `2brain`'s own outputs from that set (`.2brain/**`, `.cursor/**`, `.codeboarding/**`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.graphifyignore`, `.gitattributes`) — regenerating artifacts must never count as the repo changing.
4. Compare the count to the threshold: **stale ⇔ `threshold > 0` and `changed_count ≥ threshold`.**

Exit codes make it scriptable: `0` = fresh, `2` = stale, `1` = no state yet.

```mermaid
flowchart LR
    S["baseline commit<br/>(.2brain-state.json)"] --> D{"count changed files<br/>(committed + working tree,<br/>minus generated)"}
    D -->|"≥ threshold"| ST["STALE (exit 2)"]
    D -->|"< threshold"| FR["fresh (exit 0)"]
```

**This is a heuristic by file *count*, not by content or semantics.** Changing 5 trivial files marks the graph stale; changing 1 critical file does not. The threshold (`REPO_STALE_THRESHOLD`, default 5) is your sensitivity knob — set it to `0` to disable staleness warnings entirely.

### The automation (`2brain hook`)
`2brain hook` installs a `post-commit` git hook that re-runs the same count-vs-threshold logic after every commit and prints a warning when the graph may be stale. Two differences from `check`:
- The hook only counts **committed** drift (`git diff <baseline>..HEAD`), since it fires right after a commit.
- If you set `REPO_WIKI_AUTO=1` *before* installing the hook, and the alias `2brain` is on your PATH, the hook also auto-runs `2brain wiki .` to keep the wiki fresh.

### Being told, instead of having to look

Everything above is something a person has to run. That was the whole failure: `check` and `hook` both existed, and the artifacts in this repository still went five commits stale, because nothing ever asked. Two additions close the gap from each end.

**The consumer side — a freshness stamp.** `_freshness_note()` in `injection.py` writes the generating commit into every managed block and into `REPO_CONTEXT.md`:

> Artifacts generated from commit `0bafcf3…`. If `git rev-parse HEAD` differs, prefer the source over these artifacts and say so.

The two files that load automatically now carry their own expiry date, so an assistant reading stale artifacts is told they may be stale without anyone running `check`. This matters more as the artifacts get better: the more an assistant is told to trust `.2brain/`, the more damage a stale `.2brain/` does. A *missing* artifact fails loudly; a stale one does not fail at all.

**The producer side — the run offers the hook.** A full run ends by asking once whether to install the post-commit hook, and installs it on a keypress (`_offer_hook` in `scripts/repo.py`). It stays silent when our hook is already installed, outside a git repository, and when `REPO_HOOK_PROMPT=0`. A *foreign* `post-commit` hook is never touched or overwritten — the run says it is there and names the command, nothing more. Non-interactive runs print the one-line command instead of prompting, so a CI log still carries the hint. The end of a run is the only moment the state file is guaranteed fresh, which makes it the honest moment to ask.

---

## 3. How incremental refresh really works

There are two independent notions of "incremental," and they work very differently.

### 3a. `graph --update` — delegated incrementality
`2brain graph <repo> --update` swaps `graphify extract` for `graphify update`. The incrementality of the *graph itself* is entirely `graphify`'s job — it re-extracts only what changed. Everything downstream (execution, memory, index, context, injection) is **rebuilt in full every time**, because those layers are cheap and deterministic. So "incremental graph" means: expensive graph extraction is incremental; the fast layers on top are always recomputed for consistency.

### 3b. `wiki` — genuine incremental generation
The wiki is where incrementality matters, because each page is an LLM call and re-documenting an untouched 500-file repo would be absurdly expensive. Three mechanisms combine:

**Step 1 — What changed (the seed set).** Three ways to seed:
- explicit files: `2brain wiki . src/auth.ts` → seed = those files
- default: `git diff` against the state baseline → seed = changed files
- `--force-all` or no usable baseline → seed = *every* documentable graph file

**Step 2 — Graph closure (2-hop neighbor expansion).** This is the key insight. When you change `auth.ts`, the files that *depend on* `auth.ts` may now be documented incorrectly — so their pages need refreshing too. The seed set is expanded along the (undirected) dependency graph up to **2 hops** via breadth-first search:

```mermaid
flowchart LR
    C["changed:<br/>auth.ts"] -->|"hop 1"| N1["login.ts<br/>session.ts"]
    N1 -->|"hop 2"| N2["routes.ts<br/>middleware.ts"]
    C -.->|"seed"| C
```

So a 1-file change can legitimately regenerate a handful of related pages, but not the whole repo.

**Step 3 — Content-hash cache (the cost floor).** Even after expansion, each candidate page is only regenerated if its source file's SHA-256 hash differs from the one recorded in the page's own frontmatter. **Unchanged source ⇒ cache hit ⇒ zero tokens spent.** `--force-all` bypasses the check.

The hash used to live in a sidecar `.llm-wiki-cache.json`. A sidecar can disagree with the pages it describes — delete a page and the cache still called it fresh, which is why the check needed a second "...or the page file is missing" test to compensate. Reading the hash out of the page removes the disagreement by construction: no page, no hash, no freshness. Cost is one small read per candidate instead of one JSON parse per run, which only bites on a full rebuild that is about to make an LLM call per file anyway.

**Step 4 — Pruning & overview.** Pages whose source file disappeared are deleted. `OVERVIEW.md` is regenerated only if something was written, removed, or it's missing.

After generation, the wiki pages are folded into the semantic index and referenced from `REPO_CONTEXT.md` — but, as noted above, the **state baseline is not touched**.

`--dry-run` runs steps 1–2 and the cache check, then prints which pages *would* regenerate without making a single LLM call — the safe way to preview cost.

> Model selection for the wiki follows its own cascade: `--preset` > `REPO_PRESET_WIKI` > `REPO_PRESET_GRAPH` > default preset. Use a small/fast model for routine refreshes and a big model for `--force-all` rebuilds.

### 3c. `arch` — delegated, all-or-nothing incrementality
The architecture layer's incrementality is CodeBoarding's, not 2brain's. The adapter (`scripts/repo/arch.py`) makes exactly one decision before handing over:

```mermaid
flowchart LR
    S["2brain arch"] --> D{"analysis.json exists<br/>and no --force-all?"}
    D -->|"yes"| I["codeboarding incremental<br/>cheap"]
    D -->|"no"| F["codeboarding full<br/>expensive, whole repo"]
    I --> M["mirror pages into .2brain/arch/"]
    F --> M
    F -.->|"run dies partway"| X["nothing salvaged —<br/>next run is full again"]
```

`analysis.json` is both the rendered pages' source *and* the incremental baseline — there is no separate cache file and no per-component hash check on 2brain's side. Three consequences worth internalising:

- **The first successful run is the expensive one.** It is a full analysis of the whole repo. Every run after it is incremental and much cheaper, until you pass `--force-all` or delete `.codeboarding/`.
- **A failed run is not resumable.** CodeBoarding writes `analysis.json` at the end of a run, not progressively. If a run dies — crashed CLI, killed container, unreachable model — nothing is salvaged and the *next* run starts a full analysis again from zero. There is no partial-progress file to resume from.
- **`--force-all` does not delete the old pages up front.** It re-runs the full analysis, then `_mirror_pages` overwrites `.2brain/arch/` and prunes pages the new analysis no longer produces. So a failed `--force-all` leaves the previous pages intact.

Unlike the wiki, the arch layer never consults git: it does not diff against the `.2brain-state.json` baseline and does not expand along the dependency graph. Deciding what changed is entirely CodeBoarding's `fingerprint.json` business.

`--dry-run` prints which mode *would* run (`baseline present` / `no baseline yet` / `--force-all`) and makes no LLM calls — the cheapest way to check whether you are about to pay for a full analysis.

### 3d. `modules` — cached bodies, always-fresh wiring
The module tier splits every note into two halves with different lifetimes:

- **The LLM body** (Purpose / Key parts / How it connects / Where to start) is cached in `.modules-cache.json` under a SHA-256 over the module's member paths *and* the text of their per-file pages. Change a file → its wiki page changes → that module's digest changes → exactly that one module is rewritten. Nothing else in the tier costs a token.
- **The deterministic wrapper** (YAML frontmatter, `## Connected modules` wikilinks, the `## Files` list) is re-rendered for *every* module on *every* run, from the current graph. That is free, and it means links and file lists never drift from the codebase even when no body was regenerated.

That split is also the upgrade path: an existing tier picks up changes to the wrapper format on the next ordinary run, without regenerating a single body.

The `updated:` frontmatter timestamp deliberately records when the *body* was last written, not when the wrapper was last rendered — otherwise every run would rewrite every note, churning the index revision and Obsidian's file times for nothing.

---

## 4. The semantic retrieval algorithm (`2brain query`)

No embeddings model, no vector database — the index is a **classic TF-IDF + cosine similarity** engine implemented in pure Python, with a pseudo-relevance-feedback twist. That keeps it dependency-light and fully local.

**What is in the corpus — an explicit allowlist.** This is the part that decides answer quality, and it is a short list rather than a walk with exclusions:

| In the corpus | Why |
|---|---|
| `llm-wiki/**.md` | the per-file pages — the bulk of it, and what the tier exists for |
| `arch/**.md` | component/topic narrative |
| `EXECUTION.md`, `REPO_MEMORY.md`, `REPO_CONTEXT.md` | the top-level reports |
| in-scope prose sources (`README.md`, `docs/**.md`, …) | indexed as themselves, since no page is generated for them |
| durable memory entries + 1 runtime-metadata chunk | |

Everything else generated under `.2brain/` is absent **by construction**: a new artifact tier has to be named in the allowlist to be indexed at all, rather than silently joining by virtue of living under `OUT_DIR`. Two exclusions are deliberate and were arrived at the hard way:

- **`modules/` (the human tier).** It is written *from* the llm-wiki pages, so indexing both means roughly 79% of the corpus is the same facts stated twice. Duplication is not neutral here: IDF is a global statistic, so restating a fact halves the discriminating weight of exactly the terms that should identify the page holding it. Live symptom — a persuasion document outranked the implementation page for a question about the implementation.
- **`GRAPH_REPORT.md`.** The same problem in a worse form. It concatenates every community label, identifier and truncated docstring in the repository, so it overlaps the vocabulary of any question about the repo — maximum recall, near-zero precision. Each chunk is an index of names rather than an explanation, so it ranks high and answers nothing. Asked "how do I run the test suite" it returned a cluster label and three docstrings cut mid-sentence, while `EXECUTION.md` — which contains the literal line `make test` — missed the top ten. Its real job is first-contact orientation, which `REPO_CONTEXT.md` handles by telling a reader to open the file. That is a read-the-file job and is unaffected.

**Building the index (`build_index`):**
1. **Collect chunks** from the allowlist above, splitting the frontmatter off every llm-wiki page first. That header would otherwise put the literal tokens `source`, `sha256`, `generated_at` and `model` into *every* page — words common enough to be worth querying, present everywhere, therefore discriminating nothing — plus one unique 64-character digest per page, which is pure vocabulary growth.
2. **Chunk** long text into paragraph-like blocks capped at 1200 chars.
3. **Tokenize**: lowercase `[a-z0-9]{2,}` tokens, with a light plural fold (`configs` → also `config`) to improve recall. Not a real stemmer.
4. **Weight**: `idf(t) = log((1+N)/(1+df(t))) + 1`; term weight = `(tf/max_tf) · idf`. Each chunk vector is stored sparse with its precomputed L2 norm.

**Querying (`semantic_query`):**
1. Vectorize the query with the stored IDF; cosine-score it against every chunk → **base score**.
2. **Query expansion (pseudo-relevance feedback):** take the top seed chunks (≈ `top_k·2`), harvest their highest-weighted terms, and add the 8 strongest *new* terms to the query vector at weight `0.35`. This pulls in synonyms/co-occurring vocabulary the original query didn't contain.
3. Re-score with the expanded query, then blend: **`final = 0.65·base + 0.35·expanded`**.
4. Return the top-`k` chunks with their `kind`, `source`, and score.

The blend keeps the original query dominant (65%) while letting expansion break ties and surface related context (35%).

**What `source` points at.** Four kinds come back, and the distinction is what makes a result actionable:

| `kind` | `source` is | |
|---|---|---|
| `wiki` | the **source file the page documents**, read from its frontmatter | the page path is that path plus `.md` under `llm-wiki/`, so returning the source loses nothing and saves the caller a translation step |
| `artifact` | the generated file itself | `EXECUTION.md`, `arch/` pages, `OVERVIEW.md` — nothing they document more specifically |
| `source` | the author's own file | prose indexed directly, openable as-is |
| `memory` | `repo-memory:<id>` | |

Before pages carried frontmatter, a wiki hit returned `.2brain/llm-wiki/scripts/repo/index.py.md` and the caller had to work backwards to the file they actually wanted.

---

## 5. The revision & digest model

How does the system know the index is consistent with memory and artifacts? Every build computes a **revision hash**:

```
revision = sha256( artifact_digest : runtime_digest : memory_digest )
```

- `artifact_digest` — hash of all indexed artifact paths + bytes
- `runtime_digest` — hash of the runtime metadata (provider, model, mode, head)
- `memory_digest` — hash of all memory entries (`id|kind|text`)

After the index is built, `sync_entries` stamps every memory entry with the current `head` and this `revision`, so each fact records exactly which git state and index build it was last aligned with. Change any input — a new artifact, a new memory entry, a different model — and the revision changes, making drift detectable at the metadata level (independent of the file-count staleness heuristic in §2).

---

## 6. Which layers each command runs

Putting it together — this is the "what combines with what" map:

| Command | Graph | Execution | Memory | Index | Context | Injection | LLM Wiki | Modules | Arch | Writes state |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `all` (bare `2brain <repo>`) | ● | ● | ● | ●×3 | ●×3 | ●×3 | ● | ● | ● | ● |
| `graph` / `graph --update` | ● | ● | ● | ● | ● | ● | — | — | — | ● |
| `reindex` | — | — | ● | ● | ● | ● | — | — | — | ● |
| `remember` | — | — | ● (add) | ● | ● | ● | — | — | — | ● |
| `wiki` | — | — | ● | ● | ● | ● | ● | ● | — | — |
| `arch` | — | — | ● | ● | ● | ● | — | — | ● | — |
| `query` | — | — | — | read | — | — | — | — | — | — |
| `check` | — | — | — | — | — | — | — | — | — | read |
| `hook` | — | — | — | — | — | — | — | — | — | — |

Reading the table:
- **`all`** runs `graph → wiki → arch` in that order, and each of the three calls `_build_layers` on the way out — so memory/index/context/injection are rebuilt **three times** in one run (`●×3`). They are deterministic and cheap, so this costs seconds, not tokens; the benefit is that a run which dies in the arch layer still leaves a consistent index covering everything the graph and wiki layers produced.
- **`graph`** is the only command that runs the full stack from extraction up.
- **`reindex`** rebuilds everything *above* the graph from existing artifacts — use it after editing memory or switching AI target without paying for re-extraction.
- **`remember`** adds a fact, then rebuilds index→context→injection so the fact is immediately retrievable, and moves the state baseline.
- **`wiki`** runs the per-file layer *and* the module tier built on top of it — the two always move together, so module links can never drift from the page set — then refreshes index+context so both are queryable. It pointedly leaves the state baseline alone (§2).
- **`arch`** behaves exactly like `wiki` (its own optional doc layer, then index+context refresh, no state write), but produces component/topic pages + Mermaid diagrams in `.2brain/arch/` instead of per-file pages. It does not run the wiki layer, and the wiki does not run it — the two are independent tiers over the same graph.
- **`query`** and **`check`** are read-only.

### Where each command runs — host vs container

Everything runs in a container by default, and that default is right: graphify, CodeBoarding and the ollama/GPU wiring are genuinely easier to pin there than to reproduce on a host.

Two commands are carved out of it. `query` and `check` are pure stdlib — a dot product over a JSON file, and a `git diff` line count — and they are also the two commands run most often. Routing them through `podman compose run` cost 2.4 seconds, including starting a GPU model server, to do 50 milliseconds of arithmetic. They now run directly on the host.

- The carve-out is a **static allowlist**, not autodetection. A command is on the list because someone checked it needs nothing but the standard library; probing would eventually guess wrong and guess silently.
- The chosen mode is **printed on every invocation**, so there is never a question about which one answered.
- `REPO_MODE=host|container` (default `auto`), or `--host` / `--container`, forces it either way.
- This is a carve-out, not an inversion. Anything touching graphify, CodeBoarding or a model server stays containerised.

`EXECUTION.md` learned about the compose files at the same time (`_read_compose_files` in `execution.py`). Before that it restated the `Makefile` and never mentioned that the project runs entirely through containers — which is the single most important thing to know about running it.

---

## 7. Change response — what each layer does when things change

§3 explains *how* incrementality works. This section is the practical companion: given some event — a file created, edited, deleted, a run that crashed, a model swapped — what actually recomputes on the next `2brain <repo>`?

### 7.1 What each layer keys off

| Layer | Persisted state | Invalidated by | Cost when nothing changed |
|---|---|---|---|
| Graph (`graphify`) | `.2brain/graphify-out/graph.json` + `manifest.json` | graphify's own manifest (per-file) | `update` walks the manifest; near-zero LLM calls |
| Execution | *(none)* | nothing — always regenerated | milliseconds, no LLM (pure file scan of `package.json`, `Makefile`, `pyproject.toml`, workflows, migrations) |
| Memory | `.2brain/repo-memory.json` | `2brain remember` only | milliseconds, no LLM |
| Index | `.2brain/repo-index.json` | rebuilt in full every time; its **revision** changes when artifacts, memory, or runtime metadata change | seconds, no LLM (TF-IDF is local) |
| Context / Injection | `REPO_CONTEXT.md` + managed blocks in `CLAUDE.md` etc. | rebuilt every time; blocks are only rewritten if the bytes differ | milliseconds, no LLM |
| LLM Wiki | each page's own `sha256:` frontmatter field (SHA-256 of the source file) | source-file content hash — no page, no hash, so a deleted page is stale by construction | zero LLM calls — every page is a cache hit |
| Modules | `.2brain/modules/.modules-cache.json` (SHA-256 per module over its member pages) | a member page changed, or the module's file set moved | zero LLM calls; the deterministic wrapper is still re-rendered (free) |
| Arch | `.codeboarding/analysis.json` + `fingerprint.json` | CodeBoarding's fingerprint | one incremental CodeBoarding run (still an LLM pass, but scoped) |

The dividing line: **everything except the graph, wiki, and arch layers is recomputed unconditionally**, because those layers are deterministic and free. Only the three LLM-backed layers are cached.

### 7.2 Event by event

**You create a new file.**
The graph layer picks it up (`graphify update` sees a new entry in its manifest). The wiki then documents it, because `git status --porcelain --untracked-files=normal` counts untracked files as changed — a new file does **not** need to be committed first. The arch layer notices it only if CodeBoarding's fingerprint decides the component structure moved.

> Ordering matters: wiki candidates come from `graph.json`, so a file that is not yet in the graph gets no page. A bare `2brain <repo>` is safe (graph runs first, in the same run). Running `2brain wiki <repo>` on its own against a stale graph will silently skip the new file — refresh the graph first.

**You edit an existing file.**
Its content hash changes → its wiki page regenerates, plus its 2-hop dependency-graph neighbors (§3b). Committed and uncommitted edits both count: the changed set is the union of `git diff <baseline>..HEAD` and the working-tree/untracked status, minus 2brain's own generated paths.

**You delete or rename a file.**
Once the graph refreshes, the file leaves `candidates`; `_prune_stale_pages` deletes its wiki page, and with it the only record that the page ever existed. A rename is seen as a delete + create, so the old page is pruned and a new one generated. Same caveat as above: run the graph layer (or a bare `2brain <repo>`), not `2brain wiki` alone, or the stale page survives.

If the deleted file was the last member of a module, that module disappears too: `modules.py::generate` recomputes `grouped` from the current candidate set, `_prune` deletes the now-orphaned note from `.2brain/modules/`, and its `.modules-cache.json` entry is dropped. The vault follows automatically — `mirror_to_vault` calls `vault.mirror_markdown_tree`, which treats the vault's `Generated/Modules/` folder as an exact reflection of `.2brain/modules/`: it copies every current note over and `unlink()`s any destination note whose source is gone. So a module deleted (or emptied by scope) vanishes from the vault on the same run, not just from the repo-local tier. Arch pages behave the same way through `mirror_to_vault` in `arch.py` → `Generated/Architecture/`.

**Nothing changed since the last run.**
`2brain <repo>` is close to free on the LLM budget: `graphify update` finds no dirty files, every wiki page is a cache hit ("nothing to regenerate — all pages fresh"), and only the deterministic layers rewrite themselves. The arch layer is the exception — it still performs an incremental CodeBoarding run, which is real work. Use `2brain graph <repo> --update` or `2brain wiki <repo>` if you specifically want to avoid that.

**You narrow or widen the scope** (`.2brainignore`, `--include`/`--exclude`).
Narrowing prunes: files that fall out of scope lose their wiki page, their cache entry is dropped, and any module that becomes empty disappears from the tier and from the vault mirror. Widening costs one LLM call per newly-included file, plus a regeneration of every module whose membership changed. Scope never touches graphify, so the dependency graph — and therefore neighbour expansion and module edges — stays complete either way.

**You switch preset or model.**
This invalidates **nothing**. The wiki cache hashes source bytes, not the model, and CodeBoarding's fingerprint is structural. A better model will only be applied to files that happen to change. To actually re-document a repo with a new model, you must ask for it: `2brain wiki <repo> --force-all`, `2brain arch <repo> --force-all`, or `2brain <repo> --force-all` for everything. The model change *is* visible in the index revision (it feeds `runtime_digest`), but that is metadata, not regeneration.

**You switch AI target** (`--ai-target claude|copilot|cursor|neutral`).
Only the injection step reacts: managed blocks are rewritten in the new target's bridge files. If every block already matches byte-for-byte, 2brain prints `Inject : skipped (all managed blocks already current)` — that is an idempotent re-run, not a misconfiguration.

**You hand-edit a generated page.**
Don't — but know what happens if you do. A hand-edited wiki page is **not** restored on the next run: `_page_is_fresh` only checks the source hash and that the page file exists, so your edit survives until the source file changes or you pass `--force-all`. Arch pages are the opposite: they are re-mirrored from `.codeboarding/` on every arch run, so edits are overwritten. Either way the index picks the edited bytes up (they change `artifact_digest`, hence the revision). Put durable human knowledge in `2brain remember` or the vault's `Notes/` folder instead.

**You delete a generated page by hand.**
The wiki regenerates a missing page only if that file is in the current target set. If nothing changed, the target set is empty and the page stays missing — use `2brain wiki <repo> <the-file>` to target it explicitly, or `--force-all`.

### 7.3 Re-running after a failed run

A `2brain <repo>` that dies partway leaves everything the completed layers wrote on disk, so the retry resumes at layer granularity rather than starting over:

| Failed in | On retry, the graph layer | the wiki layer | the arch layer |
|---|---|---|---|
| Graph | full extract if `graph.json`/`manifest.json` are missing, otherwise `update` | not reached before, so runs now | runs now |
| Wiki | `update` (baseline intact) | resumes: already-written pages are cache hits, only the unwritten remainder costs tokens | runs now |
| Arch | `update` | all cache hits, ~zero cost | **restarts from zero** |

Two things are worth spelling out:

- **The wiki resumes page-by-page — this is 2brain's pause mechanism.** Each page records its own source hash as it is written, so it is complete the moment it lands and nothing else has to be flushed in step to prove it. So killing a wiki run at page 300 of 430 — a deliberate Ctrl+C to pause it, or a crash — re-uses those 300 for free on the next `2brain wiki <repo>`; only the unwritten remainder costs tokens.
- **The arch layer does not resume at all** (§3c). CodeBoarding writes `analysis.json` only on success, so a crashed *or paused* arch run leaves no baseline and the next attempt is another full analysis. This is the one place where interrupting a run costs you the whole layer — let an arch run finish, or accept redoing it.

Because the state baseline is written by the graph layer and never by wiki or arch, a run that dies in the arch layer still records the graph baseline at the new HEAD. The retry therefore sees "nothing changed" for the wiki — which is correct, since the wiki already completed.

### 7.4 Forcing a rebuild

| Goal | Command |
|---|---|
| Rebuild every layer from scratch | `2brain <repo> --force-all` |
| Re-document every file with a new model | `2brain wiki <repo> --force-all` |
| Full architecture re-analysis | `2brain arch <repo> --force-all` |
| Re-document specific files (+ their neighbors) | `2brain wiki <repo> src/a.ts src/b.ts` |
| Preview cost without spending tokens | `2brain wiki <repo> --dry-run` / `2brain arch <repo> --dry-run` |
| Rebuild index/context/injection from existing artifacts | `2brain reindex <repo>` |
| Hard reset of one layer | delete `.2brain/llm-wiki/` (or `.2brain/modules/` for the module tier) / `.codeboarding/` / `.2brain/graphify-out/` and re-run |

Deleting `.2brain/` entirely resets everything, including the staleness baseline — the next run is a first run.

---

## 8. Why not one note per file — the tier split

The wiki layer produces one page per source file. That is correct for its actual
consumer and catastrophic for the other one, and the difference is worth stating
plainly because it drove the design of the module tier (layer 7c).

### The two audiences

| | Per-file wiki (`.2brain/llm-wiki/`) | Module tier (`.2brain/modules/`) |
|---|---|---|
| Read by | the semantic index, `2brain query`, `REPO_CONTEXT.md` | a human, in Obsidian |
| Unit | one source file | one meaningful directory |
| Count on a 430-file repo | 430 | ~30 |
| Mirrored to the vault | no | yes |
| Cost to build | one LLM call per file | one LLM call per module, from the pages above |

An AI resolving "where is auth handled" wants the page that corresponds exactly
to `src/auth/login.ts`; retrieval is keyword-driven and more, smaller chunks make
it *better*. A human opening a vault wants twenty things they can name, not four
hundred they cannot. Mirroring the machine tier into a human tool was the actual
defect: it produced 1,340 notes across two repos, none of them linked, burying
the hand-written ones underneath.

### What the rest of the field does

Three traditions, and none of them ships per-file pages into a knowledge graph:

- **AI codebase wikis.** DeepWiki — which this layer's docstring cites as its
  model — generates a *topic-structured* wiki with a table of contents, on the
  order of tens of pages for a large repo. Source files are cited inside those
  pages, never given their own. CodeBoarding, which backs our arch layer, works
  the same way at component granularity. We already had the right shape at the
  top of the stack and the wrong one directly beneath it.
- **API doc generators.** Doxygen, Sphinx, TypeDoc and javadoc *do* emit a page
  per file or symbol — thousands of them. But they are consumed through search
  and an index, never presented as a network. Per-file granularity is fine there
  precisely because nobody is asked to look at it all at once.
- **PKM practice.** Obsidian's convention for exactly this problem is the Map of
  Content: hub notes that index a domain so the graph reads as hubs and spokes
  rather than a hairball. The companion convention is that generated reference
  material is kept out of the thinking graph — PARA files it under Resources,
  and the common advice is to segregate or exclude it rather than interleave it.

The module tier is the MOC layer, sized the way the AI-wiki tools size theirs.

### Why the directory is called `modules/` and not `wiki/`

Commit `03249e4` split the tier and renamed two directories in one move: the per-file pages went from `.2brain/wiki/` to `.2brain/llm-wiki/`, and the new directory tier took over the name `.2brain/wiki/`.

That path did not disappear — **it changed meaning**, which is strictly worse. A consumer holding the old sense went to a real directory, found real Markdown, and read directory notes believing they were per-file pages, with no error anywhere to signal it. `REPO_CONTEXT.md` did exactly that, describing `.2brain/wiki/` as "per-file documentation pages plus `OVERVIEW.md`" for as long as it went unregenerated. A missing file never fails this way.

Regenerating fixed that instance. It did not fix the naming that allowed it, and the hazard outlived the artifacts:

- `wiki_dir()` lived in `wiki.py` and `llm_wiki_dir()` in `llm_wiki.py`; both modules defined a `page_path_for`, a `_load_cache` and a `generate`. Reading one and editing the other was a live, easy mistake.
- The two tiers printed `Wiki     :` and `LLM Wiki :` in the same run.
- A reader who sees `wiki/` reasonably assumes it is the wiki. It was the derived summary of the wiki, and the shorter, more obvious name sat on the *less* used tier.
- Prose had to disambiguate every single time, which is why an earlier draft of this document numbered them `7` and `7c` rather than naming them.

`modules/` describes the tier's shape instead of its relationship to the other one, and it is what the code has always called these internally (`_ROOT_MODULE`, `module_title`, `_MAX_FILES_PER_MODULE`). It is also the name the directory had before `03249e4` — so the rename keeps the half of that commit that was right (`llm-wiki` is a good name) and undoes the half that created the collision.

### What follows from it

- **Only the module tier and the arch layer reach the vault.** `llm_wiki.py` has no
  `mirror_to_vault` at all; `prune_legacy_vault_mirror` clears the flat per-file
  mirror that earlier versions wrote, so an existing vault converges on the new
  layout on the next ordinary run.
- **Links are drawn only between notes that exist in the vault.** Module edges
  come from the file-level dependency graph lifted to module level; member files
  are listed as plain code spans, never as wikilinks, because a link to a note
  that was deliberately not mirrored would render in Obsidian as an unresolved
  ghost node — reintroducing the clutter at one remove.
- **Note filenames carry the repository name.** Obsidian resolves `[[...]]` by
  filename across the entire vault, and a vault holds many projects — two repos
  with a `src/ui/` would otherwise both produce `src_ui.md`, and a link meant for
  one could resolve to the other, welding two project graphs together. The prefix
  makes resolution unambiguous; the link alias (`[[repo_src_ui|src/ui/]]`) keeps
  the rendered text short.
- **The graph is drawn, not just linked.** Every module note carries a Mermaid
  flowchart of itself plus its direct neighbours, and the hub note carries the
  whole module map. Obsidian renders Mermaid natively, so the architecture is
  visible *in the note* instead of requiring a trip to the global graph view —
  which is the view that was unusable in the first place. Edges are undirected
  (`---`): lifting file edges to module level symmetrises them, so an arrow would
  assert a direction the data no longer carries. The overview diagram is capped
  at `_MAX_DIAGRAM_EDGES`, dropping the lowest-degree connections first and
  saying how many it hid — a 30-module graph can hold 435 edges, and past a few
  dozen a flowchart stops being a map.
- **Frontmatter is not decoration.** `tags: 2brain, 2brain/module, project/<name>`
  is what lets the graph view separate generated notes from hand-written ones;
  without it the vault has no way to tell the two apart, which was half of the
  original complaint.
- **Scope is not the fix.** Excluding tests and docs from a 430-file repo leaves
  285 pages. Filtering is for cost control and noise; the tier split is what makes
  the vault readable.

---

## 9. Decisions not revisited

Recorded so they are not re-proposed. Each was considered with a concrete case for it and settled against; what would *change* the answer is stated where there is such a thing.

**Container-by-default stays.** Correct for graphify, CodeBoarding and the ollama/GPU wiring. Host mode is the allowlist carve-out described in §6, not an inversion of the default.

**The injection mechanism stays.** `CLAUDE.md` → `@`-import → `REPO_CONTEXT.md` works and is proven. Only its payload was ever underspecified, and that was fixed by making `REPO_CONTEXT.md` a router (§1, layer 5) rather than by changing how it is loaded.

**graphify stays infrastructure.** `graph.json` is load-bearing for llm-wiki's neighbour expansion (§3). The gating work was about the *report*, never the graph.

**The module tier stays.** It earns its place in the Obsidian vault (§8). It was removed from the semantic corpus (§4), not from the product — two different questions that are easy to conflate.

**Embeddings are not the next lever.** Swapping TF-IDF for a model would have been measured on a corpus that stated 79% of its content twice; the ranking failure that motivated it was duplication, not vocabulary. With the corpus fixed (§4) and `query` now returning source paths rather than page paths, the case has to be made again from scratch. *What would change this:* a query that still ranks wrong on the fixed corpus, with the failing query written down.

**Passive memory capture is dropped.** `REPO_MEMORY.md` is populated only by explicit `2brain remember` calls, and in practice nobody makes them — which is why an empty "No memory entries recorded yet" report once ended up advertised in the `CLAUDE.md` directive (it is now suppressed when empty; see `_probe_artifacts`). The proposed fix was to mine recent commit messages at the end of a run and accept candidates on a keypress. Dropped, because it answers a capture problem by generating more low-provenance prose into a layer whose problem is that its contents are not trusted. *What would change this:* real, hand-written entries accumulating and proving the layer is worth feeding automatically. The schema is fine; nothing needs to change to start using it.

**`GRAPH_REPORT.md` is gated, not dropped.** It is cheap (the expensive pass is `extract`, needed for `graph.json` regardless), noise on a 30-file repo at community cohesion 0.06–0.09, and genuinely useful on the 3 000-file repos this tool targets. So it is gated on node count (`REPO_GRAPH_CLUSTER_MIN_NODES`, default 500) and advertised only when generated. *Open measurement:* the threshold was set with no large-repo data point. On the next run against a big codebase, check whether median community cohesion rises meaningfully above 0.07. If it does, tune the threshold against real numbers. If cohesion stays flat even at ~3 000 files, the clustering is not producing signal and the report should be dropped outright — a graphify problem, not a 2brain one.

---

See **[2brain.md](2brain.md)** for the command reference and examples, **[2brain-quick.md](2brain-quick.md#configuration-reference)** for shared configuration, and the main **[README](../README.md)** for installation.
