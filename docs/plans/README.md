# 2brain improvement plan

Working plan from the 2026-09-13 review. Each item links to a self-contained
document; this page is only the ordering and the reasoning behind it.

## The one-line diagnosis

The artifacts are good and largely unused. `llm-wiki/` creates information that is
not in the source, `arch/` is the best orientation material in the tree — and the
instruction that actually reaches an assistant names neither. Nearly all the
recoverable value is in the last mile between "artifact exists" and "artifact gets
read", not in generating more.

## Status

| # | Item | Doc | Status |
|---|---|---|---|
| 1 | llm-wiki pages mirror the source tree | [llm-wiki-page-paths.md](llm-wiki-page-paths.md) | **done** |
| 2 | REPO_CONTEXT.md becomes a router | [repo-context-router.md](repo-context-router.md) | **done** |
| 3 | Stamp artifact freshness into the injected block | [artifact-staleness.md](artifact-staleness.md) | **done** (proposal 1; 2 and 3 still open) |
| 4 | Stop double-indexing the two wiki tiers | [index-tier-duplication.md](index-tier-duplication.md) | **done** |
| 5 | Host mode + teach EXECUTION.md about compose | [host-container-mode.md](host-container-mode.md) | **done** |
| 6 | Gate and conditionally advertise GRAPH_REPORT.md | [graph-report-gating.md](graph-report-gating.md) | **done** |
| 7 | Resolve the `wiki/` vs `llm-wiki/` name collision | [wiki-tier-naming.md](wiki-tier-naming.md) | after re-run |
| 8 | Per-page frontmatter | [llm-wiki-page-paths.md](llm-wiki-page-paths.md#deferred-per-page-frontmatter) | deferred |
| 9 | Passive memory capture (Layer 3) | below | after re-run |
| 10 | Real embeddings | below | only after #4 |

Items 1-6 are implemented and committed. What's left needs a real `2brain <repo-path>` re-run (regenerates graph/wiki/arch against the current code) before it can be reviewed or decided — see Phase 3 below.

---

## Phase 0 — done

**1. llm-wiki page paths.** `page_name_for` flattened `/` and `.` into `_`, which
collided silently (three real paths mapped onto `scripts_repo_wiki_py.md`), was not
invertible, and — the part that actually mattered — was documented nowhere, so no
assistant could address a page without first reading `llm_wiki.py`. Pages now mirror
the source tree: the page path is the source path plus `.md`, so there is no rule to
look up and nothing to fail to look up. Tests pass, lint clean. Old flat pages
self-prune on the next `2brain wiki` run.

## Phase 1 — the last mile (done)

These were small, independent of the pending re-run, and the only changes that
convert work already paid for into work actually used.

**2. REPO_CONTEXT.md becomes a router. Done.** `_CONTEXT_ARTIFACTS` is a hardcoded 4-tuple
that feeds the `CLAUDE.md` directive, while `_build_repo_context()` separately probes
for `llm-wiki/`, `wiki/` and `arch/`. So the richest artifacts appear in the listing
and never in the instruction — and of the four that *are* advertised, one is empty,
one is unreadable JSON, and one restates the Makefile. Derive the list from one
shared probe, suppress empty artifacts, and emit trigger conditions ("editing a
source file → read its llm-wiki page first") instead of a flat manifest. ~40 lines,
no regeneration needed.

**3. Stamp artifact freshness into the injected block. Done** (proposal 1 —
proposals 2 and 3 below are still open). Everything needed to catch
staleness already exists — `.2brain-state.json` holds the generating commit,
`2brain check` compares it, `2brain hook` automates it — and all of it requires
someone to go and look. The two files that load automatically carry no freshness
signal at all. Emit the baseline commit plus "if HEAD differs, prefer the source"
into the managed block. **Sequencing matters: do this alongside #2**, because #2
increases trust in the artifacts and stale artifacts are worse than missing ones.

**4. Stop double-indexing the wiki tiers. Done.** Confirmed as real code behaviour, not a
missed re-run: `_artifact_files()` walks all of `.2brain/`, so the per-file tier
(64.5% of the corpus) and the directory tier derived from it (14.6%) are both
indexed. 79% of the corpus is the same facts twice, which depresses IDF on exactly
the terms that should discriminate — which is why a persuasion doc outranked the
implementation page in a live query. Exclude the human tier; make the corpus an
explicit allowlist so the next tier has to opt in.

## Phase 2 — friction and fit (done)

**5. Host mode. Done**, with one deviation: the plan's env var name
`2BRAIN_MODE` isn't a legal shell identifier (can't start with a digit) — shipped
as `REPO_MODE` instead, matching this project's existing `REPO_*` convention.
`query` and `check` are pure stdlib and are routed through
`podman compose run` like everything else — 2.4 s observed, including starting a GPU
model server, to do a 50 ms dot product. These are also the most frequently run
commands. Static allowlist rather than probing autodetection, with the chosen mode
printed every time. Start with `query` alone. **Verify `config.py` has no
container-absolute paths before starting** — that is the real blocker if it exists.

Bundled with it: `execution.py` has no compose reader, so `EXECUTION.md` omits that
this project runs entirely through containers. Fixing that turns Layer 2 from a
Makefile restatement into the layer that answers "how do I run this".

**6. Gate GRAPH_REPORT.md on graph size. Done.** Revised from the earlier "just drop it":
it is cheap (3 898 input / 253 output tokens — the expensive pass is `extract`,
which you need anyway for `graph.json`), it is noise on a 30-file repo at cohesion
0.06-0.09, and it is genuinely valuable on the 3 000-file repos this tool targets.
Gate the `cluster-only` call on node count from `graph.json`, make the artifact
optional rather than required, and advertise it **when it was generated** — which
falls out for free once #2 derives its list instead of hardcoding it.

## Phase 3 — after the next full run

Re-run `2brain` first, then re-review. Check specifically: does `REPO_CONTEXT.md`
describe both wiki tiers correctly, does `2brain query` return only live paths, and
are the orphan pages gone.

**7. `wiki/` vs `llm-wiki/`.** The stale-artifact damage is fixed by the re-run; the
naming that allowed it is not. Two directories one token apart naming opposite
audiences, with the shorter name on the less-used tier. Renaming the human tier to
`modules/` reverts half of `03249e4` and keeps the half that was right. Decide after
the re-run — #4 removes that tier from the retrieval path, which lowers the stakes
and may make this optional.

**8. Per-page frontmatter.** `source`, `sha256`, `generated_at`, `model` per page.
Would let the hash cache move into the pages and retire `.llm-wiki-cache.json`, and
let the index carry `source` as a retrievable field so `query` returns source paths
instead of page paths. Held back from #1 because it changes page *content*, which
touches the content-hash cache, the module tier's `read_pages()` prompt, and the
chunker.

**9. Layer 3 (durable memory).** `REPO_MEMORY.md` is written by
`write_memory_report()` in `scripts/repo/memory.py` from `repo-memory.json`, which is
populated **only** by explicit `2brain remember` calls. It is generated
unconditionally — even empty — because Layer 4 indexes it and Layer 5 lists it, which
is how an empty file ends up advertised in the directive. Currently zero entries.
The schema is fine; the capture ritual is what fails. Try passive capture: at the end
of a run, propose a few candidate entries from recent commit messages and accept on a
keypress. Judge its value after a run with real entries in it.

**10. Real embeddings.** Only after #4. Swapping TF-IDF for ollama embeddings on a
corpus that states everything twice buys a slower index with the same confusion in
it. Fix the corpus, re-measure the same query, then decide — it may not be needed.

---

## Not changing

- **Container-by-default.** Correct for graphify, CodeBoarding and the ollama/GPU
  wiring. #5 carves out an allowlist, it does not invert the default.
- **The injection mechanism.** `CLAUDE.md` → `@`-import → `REPO_CONTEXT.md` works and
  is proven; only its payload is underspecified.
- **`graphify` as infrastructure.** `graph.json` is load-bearing for llm-wiki's
  neighbour expansion. #6 is about the *report*, not the graph.
- **The module tier itself.** It earns its place in the Obsidian vault. #4 removes it
  from the index, not from the product.
