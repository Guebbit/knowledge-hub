# Presets & providers — the whole picture on one page

A **preset** is just a named `provider:model` pair you define in `.env`. That's
the entire concept. Everything else on this page is about the *providers* a
preset can point at — because they don't all work the same way, and that's the
part that trips people up.

If you only remember one thing: **the preset is the label, the provider is the
machinery.** Two presets can share plumbing and still behave completely
differently depending on which provider they name.

---

## How a preset becomes a call

```
.env:   PRESET_DEEP=openai:gpt-4o
                     └─prov─┘ └model┘

          ▼ parsed at startup (config.py)
PRESETS["deep"] = ("openai", "gpt-4o")

          ▼ selected by DEFAULT_PRESET or --preset
config.PROVIDER = "openai" ,  config.MODEL = "gpt-4o"

          ▼ looked up in _ADAPTERS (providers.py)
_call_openai(prompt)  →  the actual work
```

Steps:

1. **Define** — any `PRESET_<NAME>=provider:model` env var. Split on the **first**
   colon only, so `ollama:qwen3:8b` → provider `ollama`, model `qwen3:8b`.
2. **Select** — `DEFAULT_PRESET` picks one when you pass no flag; `--preset <name>`
   overrides it for a single command.
3. **Dispatch** — the provider name is looked up in the `_ADAPTERS` table and the
   matching `_call_X` function runs.

The parsing lives in [scripts/shared/config.py](../scripts/shared/config.py);
the adapters and the dispatch table live in
[scripts/shared/providers.py](../scripts/shared/providers.py).

---

## The two families of provider

This is the mental model that matters. Every provider is one of two kinds:

**API adapters** — talk HTTP to a REST endpoint, authenticated with a key/URL.
They're fast (one HTTP request) and the credential is an API key.

**CLI adapters** — there is **no API to hit**. They spawn a locally-installed CLI
binary as a subprocess and parse its stdout. Slower (a fresh process per call),
but they ride on a *subscription/login you already have* instead of metered API
credit. `copilot-cli` and `claude-code` are these.

> **Why `copilot-cli` is not an API.** GitHub deliberately does not expose Copilot
> as an OpenAI-compatible API. Shelling out to the `copilot` CLI is the *only* way
> to reach a Copilot subscription programmatically — which is the whole reason the
> [Copilot-only setup](copilot-only.md) exists.

---

## Every provider at a glance

| Provider | Family | Auth / credential | Model examples | Notes |
|---|---|---|---|---|
| `ollama` | API (local) | none — runs on your machine | `qwen3:8b`, `qwen2.5:3b` | Default fallback. Free but needs the Ollama container (and ideally a GPU). |
| `openai` | API (cloud) | `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`) | `gpt-4o`, `gpt-4o-mini` | Metered. `OPENAI_BASE_URL` also targets Azure / any OpenAI-compatible server. |
| `anthropic` | API (cloud) | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-...` | Metered. Direct Anthropic API. |
| `claude-code` | **CLI** | your active Claude Code login (no token env var) | whatever your CLI allows | Spawns the `claude` CLI. No API billing; uses your Claude subscription. |
| `copilot-cli` | **CLI** | `COPILOT_GITHUB_TOKEN` (fine-grained PAT, "Copilot Requests" scope) | `auto`, or a specific Copilot model | Spawns the `copilot` CLI. Draws on your Copilot plan's request allowance, no paid API credit. |

---

## The two CLI providers side by side

`copilot-cli` and `claude-code` are the **same idea** — spawn a CLI, use a
subscription, no API key — but the details differ, and `copilot-cli` is the more
hardened of the two:

| | `claude-code` | `copilot-cli` |
|---|---|---|
| Runs | `claude -p …` | `copilot -p …` |
| Auth | whatever Claude Code login is active on the machine | token from `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN` — must be a **fine-grained** PAT with "Copilot Requests"; classic `ghp_` tokens rejected |
| Output parsing | `--output-format json` → read `result` | `--silent --no-color`, then strip ANSI escapes |
| Sandboxing | none | tools disabled (`--available-tools none`), `--disable-builtin-mcps`, `--no-custom-instructions`, runs in a temp cwd so it can't scan the target repo |
| Auth-failure behaviour | dies | detects auth errors and offers a local Ollama fallback |

Why the extra hardening on `copilot-cli`? Because `2repo` feeds **untrusted
repository content** into prompts, so that adapter forces a hermetic, text-only
completion with every tool switched off. See the security note in
[providers.py](../scripts/shared/providers.py).

> **The CLI login is not the VS Code plugin login.** The `copilot` CLI
> (`@github/copilot`) authenticates with its own PAT and cannot reuse the VS Code
> Copilot extension's session. Having the plugin just proves you own a
> subscription; the CLI still needs its own token.

---

## What works where

Not every layer can use every provider. The CLI providers only back the
`call_llm` path:

| Command | API providers | `copilot-cli` / `claude-code` | Why |
|---|---|---|---|
| `2brain "…"` | ✅ | ✅ | Goes through `call_llm`. |
| `2repo wiki` | ✅ | ✅ | Goes through `call_llm`. |
| `2repo query` | ✅ | ✅ | Goes through `call_llm`. |
| `2repo graph` | ✅ | ❌ | Drives **graphify**, which calls provider APIs directly — no CLI backend. |
| `2repo arch` | ✅ | ❌ | Drives **CodeBoarding**, which accepts only `openai` / `anthropic` / `ollama`. |

`graphify` and `CodeBoarding` are third-party libraries that never touch
knowledge-hub's `call_llm` path, so they can't be pointed at a CLI provider.

---

## Fallback behaviour

Every cloud/CLI adapter shares one safety net: if the credential is missing (or a
Copilot auth error occurs), it warns and offers to fall back to the local `fast`
preset (Ollama). In non-interactive runs (piped / CI) it falls back
automatically; interactively it asks first. So a missing key degrades to "slow
but free local model", not a hard crash — provided Ollama is running.

---

## Minimal `.env` recipes

```bash
# Everyday local, free:
DEFAULT_PRESET=fast
PRESET_FAST=ollama:qwen3:8b

# Add a cloud "deep" preset for dense/important work:
PRESET_DEEP=openai:gpt-4o          # needs OPENAI_API_KEY

# Copilot-subscription-only (no API key, no GPU):
DEFAULT_PRESET=copilot
PRESET_COPILOT=copilot-cli:auto    # needs COPILOT_GITHUB_TOKEN
```

Switch per call with `--preset <name>` regardless of `DEFAULT_PRESET`.

---

## See also

- [docs/copilot-only.md](copilot-only.md) — full setup for running on a Copilot
  subscription with no API key and no GPU, including the one graph/arch gotcha.
- [docs/2brain.md](2brain.md#presets--mixing-local-and-paid-models) — presets in
  the context of note capture.
- [docs/2repo.md](2repo.md) — the per-layer preset selection rules
  (`REPO_PRESET_GRAPH` / `REPO_PRESET_WIKI` / `REPO_PRESET_ARCH`).
- [docs/ollama.md](ollama.md) — running the local model behind the `ollama`
  provider.
