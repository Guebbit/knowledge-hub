# knowledge-hub

You hit a problem. You type `2brain "what I just learned"`. A structured note appears in Obsidian. Done.

```
problem  →  2brain "topic"  →  note in Obsidian  →  never forget it again
```

No cloud. No subscriptions. Runs locally.

---

## The idea

This system has two commands. Each one solves a specific memory problem.

### The problem: ADHD + code + knowledge = context loss

Working memory is limited. With ADHD it's even more limited. Two things keep happening:

- **You learn something** → don't write it down → forget it in a week → learn it again
- **You open a repo** → spend 30 minutes reading files just to remember what it does → then your attention is gone

This system externalizes both problems.

### [`2brain`](docs/2brain.md) — second brain

Type `2brain "what I just figured out"` and an AI writes a clean, structured note straight into your Obsidian vault. Zero friction, always the same format, searchable forever via Obsidian's graph view.

→ Full usage, flags (`--link`, `--relink`, `--rework`, `--merge`, `--explore`, chain mode, etc.): **[docs/2brain.md](docs/2brain.md)**

### [`2repo`](docs/2repo.md) — repository intelligence for AI coding sessions

Run `2repo ~/Work/my-repo` and it generates deterministic repo artifacts (`graphify-out/*`: graph report, execution knowledge, durable memory, semantic index, canonical context) plus one editor bridge file for Claude, Copilot, or Cursor. Your AI assistant starts every session already knowing the repo instead of burning context re-reading it. It also supports semantic queries (`2repo --query`) and durable repo memory (`2repo --remember`).

→ Full pipeline, generated artifacts, commands, configuration: **[docs/2repo.md](docs/2repo.md)**

### How the two fit together

```
YOUR BRAIN (ADHD)
│
│  learns something  →  2brain "what I learned"
│                              │
│                              └── vault/Inbox/what-i-learned.md
│                                          │
│                                   Obsidian graph view
│                                   connects it to everything else
│
│  opens a repo      →  2repo ~/Work/my-repo
│                              │
│                              ├── graphify-out/
│                              │    ├── GRAPH_REPORT.md
│                              │    ├── EXECUTION.md
│                              │    ├── REPO_MEMORY.md
│                              │    ├── repo-index.json
│                              │    └── REPO_CONTEXT.md  ← AI assistant starts here
│                              │
│                              └── selected AI bridge file
│                                   (.claude/KNOWLEDGE.md, CLAUDE.md,
│                                   .github/copilot-instructions.md,
│                                   or .cursor/rules/2repo.mdc)
```

**One rule:** every time you learn something or start working on a repo, run the command. Never decide what to write or how to format it. The AI does that. You just capture and move on.

---

## What lives where

This is important to understand once, then you never have to think about it again.

```
Your machine (Manjaro)
│
├── vault/                ← your notes live HERE, on your disk
│     ├── Inbox/
│     ├── Guides/
│     ├── Troubleshooting/
│     ├── Projects/
│     ├── Reference/
│
├── Obsidian (desktop app) ← opens vault/ directly, no container involved
│
├── scripts/2brain.sh      ← thin bash wrapper, calls Docker (no Python on host)
│
└── Docker/Podman
      ├── ollama container  ← AI engine, GPU passthrough
      │     └── ~/.ollama/  ← model files, mounted from host so they survive rebuilds
      └── scripts container ← runs main.py (Python + all deps, ephemeral per call)
```

**The vault is not inside any container.** Docker/Podman mount it read-write so the scripts container can write notes there. Obsidian opens the vault folder directly like any other folder. No Python needed on the host.

---

## Prerequisites

- Docker or Podman
- NVIDIA GPU + drivers
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for GPU passthrough
- Obsidian installed on the host

No Python on the host. Everything runs in containers.

```bash
nvidia-smi   # verify GPU is visible before anything else
```

---

## Warning: shared model cache

The Ollama container mounts `~/.ollama` directly from your host:

```yaml
- /home/${LINUX_USERNAME}/.ollama:/root/.ollama:rw
```

- Models are **shared across all Ollama containers** — pull once, available everywhere
- Models **survive `docker compose down`** — they live on your disk, not in the container
- **Do not delete `~/.ollama`** — models are 4–20 GB each
- **Do not run two Ollama containers at the same time** pointing at the same folder — they conflict

---

## Setup (do this once)

### 1. Clone and configure

```bash
git clone <this-repo> ~/knowledge-hub
cd ~/knowledge-hub
cp .env-example .env
```

Edit `.env` — at minimum set this:

```bash
LINUX_USERNAME=yourname   # your Linux username, for ~/.ollama mount
```

The default preset (`PRESET_LOCAL=ollama:qwen3:8b`) works out of the box once you pull the model in step 5. Add or change presets in the `PRESETS` section if needed.

### 2. Register `2brain` and `2repo` as global commands

Add this to your `nano ~/.zshrc` or `nano ~/.bashrc` (use `echo $SHELL` to know which one), and add this line in the end:

```bash
export KNOWLEDGE_HUB="$HOME/knowledge-hub"   # WARNING: adjust path if different
alias 2brain="$KNOWLEDGE_HUB/scripts/2brain.sh"
alias 2repo="$KNOWLEDGE_HUB/scripts/2repo.sh"
```

Then reload:

```bash
source ~/.zshrc
```

Now `2brain` and `2repo` work from any directory on this machine.

### 3. Build the container images

```bash
docker compose build
```

This installs all Python dependencies (anthropic, openai, faster-whisper, pypdf, etc.) inside the image. Nothing touches your host Python. Do this once; repeat only after updating the repo.

### 4. Start Ollama

```bash
docker compose up -d
```

First start pulls the Ollama image — takes a minute.

### 5. Pull a model

```bash
docker compose exec ollama ollama pull qwen3:8b
```

> 24 GB VRAM → `qwen3:14b` or `qwen3.6:27B` for better quality
> 8 GB VRAM → stick with `qwen3:8b`

```bash
docker compose exec ollama ollama list   # verify
```

### 6. Open the vault in Obsidian

Obsidian → **Open folder as vault** → select `vault/` inside this repo.

Done. From now on: type `2brain`, note appears in Obsidian. Type `2repo /path/to/repo` to generate repository intelligence for any codebase.

---

## Using a paid AI provider

Add the API key to `.env`, define a preset for it, and either set it as your default or pass `--preset` when you want to use it. This applies to both `2brain` and `2repo`.

**Claude (Anthropic):**
```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
PRESET_SMART=anthropic:claude-sonnet-4-6

# use once:
2brain "topic" --preset smart

# make it the default:
DEFAULT_PRESET=smart
```

**OpenAI:**
```bash
# .env
OPENAI_API_KEY=sk-...
PRESET_CHEAP=openai:gpt-4o-mini

# use once:
2brain "topic" --preset cheap
```

---

## Configuration reference

All config lives in `.env`. Never edit `docker-compose.yml` directly.

| Variable | Default | What it does |
|---|---|---|
| `LINUX_USERNAME` | — | Your Linux username (for `~/.ollama` mount) |
| `CONTAINER_ENGINE` | `docker` | Container runtime: `docker` or `podman` |
| `DEFAULT_PRESET` | `local` | Preset used when no `--preset` flag is passed |
| `PRESET_<NAME>` | — | Define a preset: `provider:model` (e.g. `ollama:qwen3:8b`) |
| `ANTHROPIC_API_KEY` | — | Required for any preset using the `anthropic` provider |
| `OPENAI_API_KEY` | — | Required for any preset using the `openai` provider |
| `OLLAMA_PORT` | `11434` | Port Ollama listens on |
| `WHISPER_MODEL` | `base` | Whisper size: `tiny` `base` `small` `medium` `large-v3` |
| `OLLAMA_KEEP_ALIVE` | `5m` | How long model stays loaded in VRAM when idle |
| `OLLAMA_NUM_CTX` | `32000` | Context window (max tokens per request) |
| `OLLAMA_NUM_THREAD` | `1` | CPU threads for Ollama (keep low to leave headroom) |
| `OLLAMA_MEM_LIMIT` | `16g` | RAM limit for the Ollama container |

See [docs/2repo.md](docs/2repo.md#2repo-configuration-env) for `2repo`-specific variables (`REPO_PRESET_GRAPH`, `REPO_AI_TARGET`, `REPO_STALE_THRESHOLD`).

---

## Stopping and starting

Replace `docker` with `podman` if `CONTAINER_ENGINE=podman` in your `.env`.

```bash
docker compose up -d       # start Ollama
docker compose down        # stop (models stay downloaded)
docker compose restart     # restart
```

---

## Troubleshooting

**`2brain` command not found**
```bash
source ~/.zshrc   # reload shell after adding the alias
```

**Cannot reach Ollama**
```bash
docker compose ps           # check it's running
docker compose logs ollama  # check for errors
```

**GPU not being used**
```bash
nvidia-smi                           # host
docker compose exec ollama nvidia-smi  # inside container
```

**Model not found**
```bash
docker compose exec ollama ollama list
docker compose exec ollama ollama pull qwen3:8b
```

**Note created but not visible in Obsidian**

The command prints the full path. If Obsidian doesn't pick it up automatically, press the vault refresh button inside Obsidian.
