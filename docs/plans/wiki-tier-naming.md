# The `wiki/` vs `llm-wiki/` name collision

**Status: review after the next full `2brain` run.** The concrete damage below was
caused by stale artifacts, but the naming that *allowed* it is still in place.

## What happened

Commit `03249e4` ("Split the wiki tier into llm-wiki (machine) and wiki (human)")
renamed two directories at once:

| Before | After | Contents |
|---|---|---|
| `.2brain/wiki/` | `.2brain/llm-wiki/` | one page per **source file** (machine tier) |
| `.2brain/modules/` | `.2brain/wiki/` | one note per **directory** (human tier, vault-mirrored) |

`.2brain/wiki/` did not disappear — **it changed meaning**. It used to hold per-file
pages; it now holds directory notes. Any consumer holding the old meaning is not
merely out of date, it is *confidently wrong*.

## The damage this caused

`REPO_CONTEXT.md` on disk, generated before the split, described:

> `.2brain/wiki/` — living wiki: per-file documentation pages plus `OVERVIEW.md`

That path exists. It contains something else entirely. This is the failure mode a
plain missing file never has: an assistant reading that line goes to a real
directory, finds real Markdown, and reads directory notes believing they are
per-file pages — with no error anywhere to signal the mistake.

The semantic index inherited the same confusion and returned
`.2brain/wiki/scripts_repo_wiki_py.md` as a live result. That path no longer exists
in any form.

`scripts/repo/injection.py:362-380` already emits the corrected description, so a
re-run fixes today's instance.

## The part a re-run does not fix

The names still differ by a prefix. `wiki/` and `llm-wiki/` are one token apart and
name **opposite audiences** — machine and human — with the shorter, more obvious
name given to the *less* used tier. Consequences that survive regeneration:

- `wiki_dir()` lives in `wiki.py` and `llm_wiki_dir()` in `llm_wiki.py`; both modules
  define a `page_name_for`/`page_path_for`, a `_load_cache` and a `generate`. Reading
  one and editing the other is a live, easy mistake.
- Both tiers own a cache path in `_SKIP_INDEX_PATHS` that differ only by that prefix.
- A reader who sees `wiki/` reasonably assumes it is the wiki. It is the derived
  summary of the wiki.
- Prose has to disambiguate every single time, which is why `2brain-internals.md`
  numbers them `7` and `7c` instead of naming them.

Same-meaning-different-content is exactly what broke `REPO_CONTEXT.md`. The names
make that class of error easy to repeat.

## Proposal

Rename the human tier to something that describes its *shape* rather than its
relationship to the other tier:

```
.2brain/llm-wiki/   (per-file, machine)   -> unchanged
.2brain/wiki/       (per-directory, human) -> .2brain/modules/  or  .2brain/vault-notes/
```

`modules/` is the honest description — the code already calls these "modules"
throughout (`_MAX_FILES_PER_MODULE`, `module_title`, `_ROOT_MODULE`), the tier is
built by grouping directories into modules, and it was literally the directory's
name before the split. The rename is a revert of half of `03249e4`, keeping the part
that was right (`llm-wiki` is a good name) and undoing the part that created the
collision.

Cost: a constant in `wiki.py`, the `_SKIP_INDEX_PATHS` entry, the `.gitignore`
managed block, vault mirror paths, and prose in `docs/`. No migration — generated
artifacts are disposable.

## Decide after the run

Re-run first and confirm `REPO_CONTEXT.md` describes both tiers correctly. Then the
open question is only whether the naming risk justifies the churn. Two things worth
weighing at that point:

1. Did the corrected `REPO_CONTEXT.md` actually route an assistant to the right tier?
2. With the index duplication fixed (`index-tier-duplication.md`), the human tier
   leaves the retrieval path entirely — which lowers the blast radius of confusing
   the two, and may make the rename optional rather than necessary.
