# Stale artifacts are silently trusted

**Status: review after the next full `2brain` run.** Yes, this instance was a missed
re-run. The design gap it exposed is not fixed by re-running.

## What was observed

At review time the artifacts were generated from commit `23e6965`; `HEAD` was
`667dc58` — five commits and one directory-layout change later. Consequences:

- `REPO_CONTEXT.md` described `.2brain/wiki/` as holding per-file pages. After
  commit `03249e4` that directory holds directory notes instead, so the description
  pointed at a real path with the wrong contents (see `wiki-tier-naming.md`).
- `2brain query` returned `.2brain/wiki/scripts_repo_wiki_py.md`, a path that no
  longer exists anywhere.
- `llm-wiki/` still carried `scripts_repo_modules_py.md` and
  `tests_test_modules_py.md` for renamed files, and had no page for
  `tests/test_llm_wiki_graph.py`.

## The actual gap

**Nothing surfaced the staleness.** Not to you, not to an assistant. It was caught
by manually diffing `.2brain-state.json` against `git rev-parse HEAD` during review.

Everything needed to catch it was already present and unused:

- `.2brain-state.json` records `"head": "23e6965…"` and a `threshold`.
- `2brain check` exists and compares exactly this (`scripts/repo.py:367`).
- `2brain hook` installs a post-commit staleness warning (`scripts/repo.py:395`).
- `GRAPH_REPORT.md` even prints its own remedy: *"Run `git rev-parse HEAD` and compare
  to check if the graph is stale."*

Every one of these requires someone to *go and look*. None of them reaches the
consumer at the moment of consumption. The artifacts that get loaded automatically —
`CLAUDE.md` and `REPO_CONTEXT.md` — carry no freshness signal at all, so a stale
artifact and a fresh one are indistinguishable to the thing reading them.

That is the whole bug: **staleness is detectable on demand and invisible by default.**

## Why it matters more than it looks

A stale artifact is worse than a missing one. Missing fails loudly and the reader
falls back to source. Stale costs tokens *and* actively misroutes, and the reader
has no signal to distrust it. The query returning a dead path is the benign version;
the dangerous version is a page that describes code which no longer behaves that way.

This risk rises as the artifacts get better. The more an assistant is taught to
trust `.2brain/`, the more damage a stale `.2brain/` does — so freshness has to be
solved *before* the router in `repo-context-router.md` succeeds at increasing trust.

## Proposal

**1. Stamp the baseline into the injected block** (the real fix). `_claude_inline()`
already writes to `CLAUDE.md`; make it emit the generating commit and a fallback
instruction:

```markdown
Artifacts generated from commit `23e6965`.
If `git rev-parse HEAD` differs, prefer the source over these artifacts and say so.
```

This moves the check from "a command someone must remember to run" to "a fact
present in the context that already loads". Cost: a few lines, no new machinery,
`.2brain-state.json` already holds the value.

**2. Offer the hook at the end of the first run.** `2brain hook` exists and solves
this for committed work; it is opt-in, and opt-in features that require remembering
do not get adopted. Prompt once, install on a keypress.

**3. Make `2brain check` cheap enough to be reflexive.** It is pure git + JSON with
no LLM. It should not cost a container start — see `host-container-mode.md`.

## Decide after the run

Re-run, then confirm:

- `REPO_CONTEXT.md` describes both wiki tiers correctly.
- `2brain query .` returns only paths that exist.
- The orphan pages are gone (the new page-path scheme prunes them automatically —
  see `llm-wiki-page-paths.md`).

Then proposal 1 stands on its own merits regardless, because the next drift is a
matter of when, not whether.
