# Layer 5: make REPO_CONTEXT.md a router, not a manifest

**Status: planned.** Highest-leverage change in the stack.

## Who creates it and why

`_build_repo_context()` in `scripts/repo/injection.py:349`, run as Layer 5 of every
pipeline. Its job is the design rule the whole project is built on — *one canonical
source, zero duplicated AI summaries*. Every editor bridge file (`CLAUDE.md`,
`.github/copilot-instructions.md`, `.cursor/rules/2brain.mdc`) only **points** at
`REPO_CONTEXT.md`; none of them copies it. Regenerate once, every assistant sees it.

That design is correct and it demonstrably works: `CLAUDE.md` is auto-loaded, its
`@.2brain/REPO_CONTEXT.md` import is resolved, and both files were in context before
a single tool ran. **The delivery mechanism is not the problem.**

## How it works now

Two pieces, and they disagree with each other.

**`_CONTEXT_ARTIFACTS`** (`injection.py:40-45`) is a hardcoded 4-tuple that feeds the
*instruction* written into `CLAUDE.md`:

```python
_CONTEXT_ARTIFACTS = (
    (f"{config.GRAPHIFY_OUT}/GRAPH_REPORT.md", "structural and semantic code graph report"),
    (f"{_OUT}/EXECUTION.md", "runnable build/test/CI/migration knowledge"),
    (f"{_OUT}/REPO_MEMORY.md", "durable repository memory entries"),
    (f"{_OUT}/repo-index.json", "semantic retrieval index"),
)
```

**`_build_repo_context()`** (`injection.py:362-380`) separately probes the filesystem
and appends `llm-wiki/`, `wiki/` and `arch/` to `REPO_CONTEXT.md` if they exist.

The result: the three richest artifacts appear in the *listing* but never in the
*instruction*. The emitted directive reads:

> It lists the expanded sources: `GRAPH_REPORT.md`, `EXECUTION.md`, `REPO_MEMORY.md`,
> `repo-index.json`. Read the ones relevant to the task.

Of those four, measured on this repo today: `REPO_MEMORY.md` says *"No memory entries
recorded yet."*; `EXECUTION.md` is 25 lines of Make targets the Makefile states more
cheaply; `repo-index.json` is 1 MB of TF-IDF vectors that cannot be usefully read as
text at all — it is a query backend, not a document. Only `GRAPH_REPORT.md` is
readable prose, and it is the weakest prose in the tree (see `graph-report-gating.md`).

So the instruction sends an assistant to four dead ends while 30 000 tokens of
excellent per-file documentation sit one directory away, unmentioned. **This is the
whole reason the artifacts get ignored — not assistant laziness, an empty payload.**

A second, subtler failure: the list is a *manifest*. It says what exists, never what
to do with it. "Read the ones relevant to the task" has no trigger condition, so the
cost of checking is certain and the benefit is speculative. That trade loses every
time, against any assistant.

## How it should work

**1. Derive the artifact list; stop hardcoding it.** `_CONTEXT_ARTIFACTS` and
`_build_repo_context()` must share one probe, so the instruction can never again name
a different set than the listing. This is the bug that let llm-wiki go unadvertised.

**2. Suppress artifacts with no content.** Do not advertise `REPO_MEMORY.md` with
zero entries, and never advertise `repo-index.json` as readable — reference it only
as what backs `2brain query`.

**3. Emit routing rules, not a file list.** Replace the flat listing with triggers:

```markdown
## Where to look

- **Editing or reading a source file** → read `.2brain/llm-wiki/<path>.md` first
  (the page path is the source path plus `.md`). It carries the file's purpose,
  its key elements, its graph neighbours, and the gotchas that are not in the source.
- **"How is this structured?" / "where does X live?"** → `.2brain/arch/overview.md`,
  then the component page it points to.
- **"How do I run / build / test / deploy this?"** → `.2brain/EXECUTION.md`.
- **Anything else, or you don't know which file** → `2brain query . "question"`.

Artifacts were generated from commit `<head>`. If `git rev-parse HEAD` differs,
prefer the source and say so.
```

A trigger converts a list into behaviour. That is the entire change.

**4. Make advertisement conditional on measured usefulness**, not on existence —
the same gate as `graph-report-gating.md`. A layer that ran but produced nothing
meaningful should not buy a line in the router.

## Why this is ranked first

It is ~40 lines in one file, needs no regeneration of any expensive artifact to
take effect, and it is the only change that converts work already paid for into
work actually used. Everything else in the backlog improves an artifact; this one
improves whether artifacts are read at all.

## Verification

Ask a fresh assistant session "what does `scripts/repo/arch.py` do?" and check
whether it opens `.2brain/llm-wiki/scripts/repo/arch.py.md` before opening the
source. That is the whole acceptance test.
