# Host mode for local-safe commands (+ teaching EXECUTION.md about compose)

**Status: DONE** (both parts — `REPO_MODE`/`--host`/`--container` in `2brain.sh`,
and the compose reader in `execution.py`; see `tests/test_execution.py`). Two
related items: the container routing itself, and the fact
that `EXECUTION.md` does not document it.

---

## Part 1 — Host mode

### How it works now

You read it correctly. `scripts/2brain.sh:146` routes **every** repo command through
the container, and the target repo is bind-mounted in:

```bash
"$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
    -v "${REPO_PATH}:/target-repo:rw" \
    scripts \
    python -u /scripts/repo.py "${ARGS[@]}"
```

Note mode (`-q`) does the same at line 106. The arg scan at lines 119-133 finds the
first argument that is a real directory, `realpath`s it, and substitutes the literal
`/target-repo` in the argument list so the in-container process sees a stable path.

**This is the right default and should stay.** graphify, CodeBoarding's venv, the
ollama/GPU wiring and reproducibility across your Linux and Windows compose files
all depend on it.

### The problem

A specific, small set of commands pays for all of that and uses none of it.

`semantic_query()` (`scripts/repo/index.py:342`) is pure stdlib — `json`, `math`,
`re`, `collections`. No network, no LLM, no graphify. It loads a JSON file and
computes cosine similarity: roughly 50 ms of work.

Observed cost of running it through the current path: **2.4 s**, and it started
`knowledge-hub_ollama_1` — a GPU model server — to do a dot product.

These are also the commands used *interactively and repeatedly*. `query` and `check`
are the ones you would reach for a dozen times an hour, and they are precisely the
ones carrying the heaviest fixed overhead relative to their work. It also means
`query` cannot run anywhere without a container runtime, despite needing nothing
but Python and a file.

### Why not autodetection

You suggested the tool could work it out automatically. I would argue against the
probing version — "try host, fall back to container" produces a tool that is fast on
Tuesday and slow on Wednesday for invisible reasons, and silent divergence between
two execution paths is miserable to debug when results differ.

A **static allowlist** gets the same speed with none of that. It is a rule you can
read in the script and predict without running anything.

### Proposal

```bash
# Commands that are pure-stdlib local reads: no graphify, no CodeBoarding,
# no LLM, no network. Everything else needs the container.
LOCAL_SAFE=" query check "
```

- Command in `LOCAL_SAFE` **and** a usable host interpreter exists → run on host.
- Otherwise → container, exactly as today.
- `2BRAIN_MODE=host|container|auto` (default `auto`) plus `--host` / `--container`
  flags to force either way.
- **Print the chosen mode, always**: `mode: host (query is local-safe)`. A visible
  decision is what separates this from magic.

Autodetection then exists only as a fallback *within* the allowlist: if the host
interpreter is missing or unusable, fall back to the container rather than failing.
Never the reverse.

### Implementation notes

1. **The path rewrite is the one real change.** Lines 119-133 substitute
   `/target-repo`. In host mode that substitution must be skipped and the real path
   passed through. Everything else in the script is already path-agnostic.

2. **Verify `scripts/shared/config.py` has no container-absolute paths** baked in
   (`/scripts`, `/vault`, `/target-repo`). If it does, that is the actual blocker and
   must be sorted first. Check this before writing any shell.

3. **Interpreter selection:** prefer `$ROOT/.venv/bin/python` (it exists), fall back
   to `python3`, fall back to the container if neither imports the `repo` package.

4. **`PYTHONPATH`** must point at `$ROOT/scripts` so `from repo import …` and
   `from shared import …` resolve the same way they do in the image.

5. **Start with `query` alone.** Highest frequency, lowest risk, and it proves the
   host path end to end. Add `check` once it is working.

6. **`remember` and `hook` are candidates but not day one.** `remember` triggers a
   reindex through `_build_layers`; confirm that path stays stdlib-only before
   allowlisting it. `hook` writes a git hook and is probably safe, but it is rare
   enough that the speedup does not matter.

### Verification

`time 2brain query . "anything"` should drop from ~2.4 s to well under 0.5 s, print
`mode: host`, start no containers, and return byte-identical results to
`2brain --container query . "anything"`. That last equality is the test that matters.

---

## Part 2 — `EXECUTION.md` does not know this repo runs in a container

This is the same subject from the other end, and it is Layer 2's biggest gap.

`scripts/repo/execution.py` is the best cost/benefit layer in the stack — fully
deterministic, zero LLM. It scrapes `Makefile` targets, `package.json` scripts,
`pyproject.toml` entries and GitHub Actions `run:` lines.

It has **no `docker-compose.yml` reader**, so the generated `EXECUTION.md` for this
repository reads:

```
## Quick Commands
- `make test`
- `make lint`
- `make check`
```

and omits the single most important execution fact about the project — that
everything runs through `podman compose`, against services defined in
`docker-compose.yml` (and `docker-compose.windows.yml`), with an ollama service, GPU
wiring, bind mounts and a substantial `.env` contract.

An assistant handed that file would confidently tell you to `pip install` and run
`pytest` directly.

### Proposal

Teach `execution.py` to read compose files and emit:

- **Services** and what each is for (`scripts`, `ollama`).
- **The run pattern** — that commands execute via `compose run --rm <service>`,
  which is the actual entry point.
- **Bind mounts**, especially `/target-repo`, `/vault`, `/scripts`.
- **Required environment**, cross-referenced from `.env-example` (which is 8 KB and
  currently documented nowhere in the artifacts).
- **Platform variants** — that `docker-compose.windows.yml` exists and when it applies.

This is pure parsing, no LLM, and it converts a layer that currently restates the
Makefile into the one that answers "how do I actually run this thing".

It also directly serves Part 1: once host mode exists, `EXECUTION.md` is where the
host-vs-container rule should be documented for whoever reads the artifacts next.
