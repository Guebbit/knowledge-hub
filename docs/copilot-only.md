# Running on a GitHub Copilot subscription only

**The situation this covers:** you have a **GitHub Copilot subscription** (for
example through the official Copilot plugin in VS Code / your IDE), but you have

- **no paid API key** (no OpenAI / Anthropic / Azure credit), and
- **no GPU / no machine that can run a local open model** at a usable speed.

This page explains exactly what knowledge-hub can and cannot do in that setup,
why, and how to configure `.env` for it.

---

## TL;DR

| Feature | Works Copilot-only? | Backend it uses |
|---|---|---|
| `2brain -q "topic"` | ✅ Yes | `copilot-cli` (the `call_llm` path) |
| `2brain wiki <repo>` | ✅ Yes | `copilot-cli` |
| `2brain query <repo> "..."` | ✅ Yes | `copilot-cli` |
| `2brain graph <repo>` | ❌ No | graphify — no Copilot backend |
| `2brain arch <repo>` | ❌ No | CodeBoarding — no Copilot backend |
| bare `2brain <repo>` (graph→wiki→arch) | ❌ No | starts with the graph layer |

**Bottom line:** `2brain`'s note capture, and its `wiki`/`query` subcommands, run
on your Copilot subscription with no API key and no local model. The `graph`
and `arch` layers cannot — not even in a reduced form — because they call model
**APIs directly**.

---

## Why graph and arch can't use Copilot

This is architectural, not a missing setting:

- **`2brain graph`** runs [graphify](https://pypi.org/project/graphifyy/) as a
  subprocess. Its only backends are `claude` (Anthropic API), `openai`,
  `ollama-json` (local Ollama), and `claude-cli`. There is **no Copilot
  backend**, and graphify has no generic "shell out to a CLI" path that Copilot
  could plug into. See the `_BACKEND_MAP` in [scripts/repo.py](../scripts/repo.py).
- **`2brain arch`** runs [CodeBoarding](https://github.com/CodeBoarding/CodeBoarding),
  which accepts **only** `openai`, `anthropic`, or `ollama`. It doesn't even
  support the `claude-code` CLI, let alone Copilot.

The `copilot-cli` provider works for `2brain`'s note capture, `wiki`, and
`query` precisely because those go through knowledge-hub's own `call_llm` path, which
*can* shell out to the `copilot` CLI. graphify and CodeBoarding are third-party
libraries that never touch that path.

> **The VS Code plugin is not the same login.** The `copilot-cli` provider uses
> the standalone `copilot` CLI (`@github/copilot`), which authenticates with its
> own token — it cannot reuse the session from the VS Code Copilot extension.
> Having the plugin proves you own a Copilot subscription (which is what pays for
> the requests), but you still have to mint a token for the CLI (below).

---

## Setup

### 1. Create the token the CLI needs

The `copilot` CLI authenticates with a **fine-grained** personal access token
(`github_pat_...`) that has the account-level **"Copilot Requests"** permission.
Classic `ghp_...` tokens are **rejected**.

- Create it at <https://github.com/settings/personal-access-tokens>.
- Grant the account permission **"Copilot Requests"**.

### 2. Configure `.env`

```bash
# Route everything that can use Copilot through the subscription.
DEFAULT_PRESET=copilot
PRESET_COPILOT=copilot-cli:auto      # "auto" lets Copilot pick the model
REPO_PRESET_WIKI=copilot             # 2brain wiki + query use Copilot too

# The only credential this setup needs:
COPILOT_GITHUB_TOKEN=github_pat_...   # fine-grained PAT, "Copilot Requests" scope
COPILOT_CLI_TIMEOUT=600               # seconds before `copilot -p` times out

# Generated bridge files target Copilot:
REPO_AI_TARGET=copilot

# Leave graph/arch UNSET — they can't use Copilot. Do not point them at `copilot`;
# 2brain fails fast with a "no graphify/CodeBoarding backend" error if you do.
#REPO_PRESET_GRAPH=deep
#REPO_PRESET_ARCH=deep
```

### 3. Build / rebuild the image

The `copilot` CLI is baked into the container image
([Dockerfile.scripts](../Dockerfile.scripts) runs
`npm install -g @github/copilot`), so nothing is installed on the host. Rebuild
if you haven't since it was added:

```bash
docker compose -f docker-compose.windows.yml build     # Windows / CPU
# or: docker compose build                              # Linux
```

---

## Usage

```bash
2brain -q "something I just learned"       # ✅ Copilot
2brain wiki  ~/Work/my-repo                 # ✅ Copilot
2brain query ~/Work/my-repo "how do I run tests?"   # ✅ Copilot
```

Avoid a **bare** `2brain ~/Work/my-repo`: it starts with the graph layer, which
has no Copilot backend and will stop with a clear error. Use the individual
subcommands instead.

### Cost note

Copilot-backed calls are not literally free — each one spends from your Copilot
plan's **request allowance** (premium requests count against premium models). It
just consumes no *paid API credit*.

---

## The one gotcha: wiki needs graph output

`2brain wiki` reads the semantic index that the **graph** layer produces
(`.2brain/repo-index.json`, `.2brain/graphify-out/graph.json`). On a **brand-new**
repo where graph has never run, the wiki step may have nothing to read.

If you hit that, you need a **one-time** graph pass from a non-Copilot backend.
Two options, both of which you can turn off again afterwards:

**Option A — free but slow: CPU-Ollama.** Despite what older `.env` comments may
say, the Windows compose file
([docker-compose.windows.yml](../docker-compose.windows.yml)) runs Ollama
**CPU-only** — no GPU required. A small model works; it's just slow on a big repo.

```bash
docker compose -f docker-compose.windows.yml up -d ollama
docker compose -f docker-compose.windows.yml exec ollama ollama pull qwen2.5:3b
# then, for the one-time pass:
#   set REPO_PRESET_GRAPH=fast   (PRESET_FAST=ollama:qwen2.5:3b) in .env
2brain graph ~/Work/my-repo
# afterwards, re-comment REPO_PRESET_GRAPH and go back to Copilot for wiki/query.
```

**Option B — a few cents: a cloud key.** Add `OPENAI_API_KEY` and set
`REPO_PRESET_GRAPH=deep` (`PRESET_DEEP=openai:gpt-4o-mini` is very cheap). Run
`2brain graph` once, then switch back.

`arch` is the heaviest and most optional layer; the copilot-only setup simply
skips it. Enable it (same two options, via `REPO_PRESET_ARCH`) only if you want
the component diagrams.

---

## See also

- [docs/presets.md](presets.md) — one-page overview of every preset/provider type
  (API vs CLI), with the same tables, if you want the full comparison.
- [docs/2brain-quick.md](2brain-quick.md#presets--mixing-local-and-paid-models) — the full
  provider/preset list and how `copilot-cli` fits in.
- [docs/2brain.md](2brain.md#2brain-configuration-env) — the layer model selection rules
  (`REPO_PRESET_GRAPH` / `REPO_PRESET_WIKI` / `REPO_PRESET_ARCH`).
- [docs/ollama.md](ollama.md) — running the local (CPU) model if you enable the
  graph fallback.
