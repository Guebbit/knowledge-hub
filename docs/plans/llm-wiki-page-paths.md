# llm-wiki page paths: mirror the source tree

**Status: DONE** (code changed, tests pass, artifacts regenerate on the next `2brain wiki`).

## Who created it and why

`page_name_for()` in `scripts/repo/llm_wiki.py` — part of the original living-wiki
layer (Layer 7). The per-file tier needs a stable filename per source file, and
flattening the path into a single segment was the shortest way to get one without
creating directories. It has been there since the tier was written.

## How it worked before

```python
def page_name_for(rel_path: str) -> str:
    """Return the wiki page filename for a source file (src/a.ts → src_a_ts.md)."""
    return rel_path.replace("/", "_").replace(".", "_") + ".md"
```

Every `/` and `.` became `_`, producing a flat directory of 43 pages.

Four problems, all verified against the real code:

**1. It collided silently.** `_` is the image of three different characters, so
distinct sources mapped onto one page and the last writer won:

```
scripts/repo/wiki.py   -> scripts_repo_wiki_py.md
scripts/repo_wiki.py   -> scripts_repo_wiki_py.md   <- same file
scripts/repo/wiki_py   -> scripts_repo_wiki_py.md   <- same file
```

Harmless in this repo today; a live data-loss bug in any repo that happens to
contain both `a/b.py` and `a_b.py`. Nothing detected or reported it.

**2. It was not invertible.** Given `scripts_repo_wiki_py.md` you cannot recover
the source path — each `_` might have been `/`, `.` or a literal `_`. The page's
first line carries `# scripts/repo/arch.py`, which rescues a reader, but only
*after* opening the file. Tooling upstream of that had nothing to key on.

**3. It was undiscoverable.** The rule lived only in the function body. Nothing in
`CLAUDE.md` or `REPO_CONTEXT.md` stated it, so an assistant pointed at the
llm-wiki directory could not address a page without first reading `llm_wiki.py`.
This is the reason the best artifact in the stack went unused.

**4. It stranded orphans.** Renames left pages for files that no longer exist
(`scripts_repo_modules_py.md`, `tests_test_modules_py.md` are both present now)
while renamed files had no page. `_prune_stale_pages` handles this, but only on
a run, and nothing surfaced the drift in between.

## How it works now

```python
def page_path_for(rel_path: str) -> str:
    return rel_path + ".md"
```

The page tree mirrors the source tree:

```
scripts/repo/wiki.py   ->  .2brain/llm-wiki/scripts/repo/wiki.py.md
docker-compose.yml     ->  .2brain/llm-wiki/docker-compose.yml.md
```

What this buys:

- **No collisions.** Path uniqueness is the filesystem's job and it already does it.
- **Invertible.** Strip `.md`.
- **No rule to document.** This is the real win. An assistant that knows the source
  path knows the page path — there is nothing to look up, so nothing to fail to look
  up. A smarter mangling scheme would have fixed collisions but not this.
- **Orphans become visible** as directories that no longer exist in the source tree.
- **Free navigation.** `ls .2brain/llm-wiki/scripts/repo/` answers "what is documented
  in this package".

Renamed from `page_name_for` to `page_path_for` because the return value is now a
tree-relative path, not a filename, and callers that treated it as a name needed to
change anyway.

## What changed

| File | Change |
|---|---|
| `scripts/repo/llm_wiki.py` | `page_name_for` → `page_path_for`; module docstring; `_prune_stale_pages` walks with `rglob` on relative paths and collapses directories it empties; page writes `mkdir(parents=True)` first; cache and `written` record the tree path; `page_count` recurses |
| `scripts/repo/injection.py` | llm-wiki presence check `glob` → `rglob` (a nested tree has no `*.md` at its root, so REPO_CONTEXT.md would have stopped listing the tier) |
| `tests/test_wiki.py` | collision test follows the rename |
| `tests/test_llm_wiki_graph.py` | new `TestPagePathMapping`: path mapping, invertibility, and the three paths that used to collide |

`scripts/repo/wiki.py` keeps its own separate `page_name_for(module, repo_name)`.
That tier is flat and repo-namespaced on purpose because it is mirrored into a
shared Obsidian vault, where a nested tree would be wrong. Untouched.

`index.py` already used `rglob` over the whole of `.2brain/`, so the semantic index
picks up nested pages with no change.

## Migration

None, by design — generated artifacts are disposable.

The existing 43 flat pages self-clean on the next `2brain wiki` run: the cache
check `(_page_is_fresh)` tests for a page at the *new* path, finds none, and
regenerates every page; `_prune_stale_pages` then deletes every flat page,
because no flat name appears in the new `valid_pages` set. One full-cost wiki
pass, then steady state.

## Deferred: per-page frontmatter

Recommended alongside this, not shipped with it:

```yaml
---
source: scripts/repo/wiki.py
sha256: <content hash>
generated_at: 2026-09-13T...
model: qwen3.8:27b
---
```

Three wins: pages become self-describing; the hash cache could move into the pages
and retire `.llm-wiki-cache.json`; and the index could carry `source` as a
retrievable field, so `2brain query` returns **the source path** instead of a page
path the caller has to translate.

Held back because it changes page *content*, which touches the content-hash cache,
the module tier's `read_pages()` (frontmatter would leak into that prompt) and the
index chunker. That is a separate change with its own test surface, and bundling it
would have made this one hard to verify. See the master plan.
