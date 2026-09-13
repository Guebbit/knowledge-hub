# The semantic index double-counts the same facts

**Status: confirmed code behaviour, not a stale artifact. Must fix.**

You asked whether this was you forgetting to re-run, or a real defect. **It is a real
defect.** The stale artifacts changed the directory *names* in the evidence below,
but not the behaviour: after any re-run the index will ingest the same content at two
granularities exactly as it does now.

## The evidence

`2brain query . "how does the wiki cache decide to skip a page"` ranked a
*persuasion document* (`docs/2brain-why.md`) first, above the file that actually
implements the behaviour, and the returned snippet did not contain the answer.

Counting the live corpus by tier:

| Tier | Chunks | Share |
|---|---:|---:|
| per-file pages (`llm-wiki/`, named `wiki/` when indexed) | 394 | 64.5% |
| directory notes (`wiki/`, named `modules/` when indexed) | 89 | 14.6% |
| `arch/` | 70 | 11.5% |
| `GRAPH_REPORT.md` | 43 | 7.0% |
| `EXECUTION.md`, `REPO_CONTEXT.md`, `REPO_MEMORY.md`, runtime | 15 | 2.4% |

**79% of the corpus is two descriptions of the same facts**, because the directory
notes are *written from* the per-file pages (`llm_wiki.read_pages()` feeds
`wiki.py` — that is exactly what keeps the module tier at ~25 LLM calls instead of
one per file). Same content, two granularities, both indexed.

## Why this wrecks ranking specifically

The index is TF-IDF (`scripts/repo/index.py:185-222`), so IDF is computed across
that corpus. When every real concept appears in two or three phrasings, the terms
that identify it get their IDF *depressed* — the vocabulary looks common because
the corpus repeats itself. Discriminating terms stop discriminating.

What survives is documents whose vocabulary is unusual, which in this corpus means
prose *about* the system rather than description *of* it. Hence a marketing-ish doc
outranking the implementation page. This is a corpus construction bug wearing a
ranking bug's clothes.

## Root cause

`_artifact_files()` (`scripts/repo/index.py:108-135`) walks **all** of `.2brain/`:

```python
for path in sorted(out_dir.rglob("*")):
    ...
    if rel.is_relative_to(_GRAPHIFY_OUT_DIR) and rel != _GRAPH_REPORT_PATH:
        continue
    if path.suffix.lower() not in {".md", ".json", ".txt"}:
        continue
```

The only exclusions are graphify's raw dumps and five named paths in
`_SKIP_INDEX_PATHS` (state, index, memory JSON, two caches). Both wiki tiers fall
through and are indexed. There was never a decision to index one tier and not the
other — the walk simply takes everything, and the tier split arrived later.

## The fix

**Exclude the directory tier from the index.** It exists to be read by a human in
Obsidian; it is the only wiki-side output mirrored into the vault, and it is
explicitly the human-facing tier (`docs/2brain-internals.md` §8). It has no
retrieval job. For an assistant it is strictly dominated by the per-file pages it
was derived from.

Make the corpus **llm-wiki + arch + EXECUTION + REPO_MEMORY + GRAPH_REPORT**, and
make the selection an explicit allowlist rather than "everything we did not think
to exclude" — so the next new tier has to opt in instead of silently joining.

Expected effect: corpus drops ~15%, and the terms that identify real concepts get
their discriminating power back.

## Sequencing

**Do this before considering embeddings.** Swapping TF-IDF for ollama embeddings on
a corpus that says everything twice would buy a slower index with the same confusion
in it. Fix the corpus, re-measure the same query, then decide whether embeddings are
still needed. They may not be.

## Verification

Re-run `2brain query . "how does the wiki cache decide to skip a page"`. The
per-file page for the module that implements the content-hash cache should rank
first, and the returned snippet should mention the SHA-256 hash comparison. If a
`docs/` page still wins, the problem is deeper than duplication and embeddings
become the next lever.
