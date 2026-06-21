# knowledge-hub

You hit a problem. You type `2brain "what I just learned"`. A structured note appears in Obsidian. Done.

```
problem  →  2brain "topic"  →  note in Obsidian  →  never forget it again
```

No cloud. No subscriptions. Runs locally.

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

## How it works

| Who | Does what |
|---|---|
| **You** | Type one command |
| **`2brain`** (host shell script) | Parses args, spins up the scripts container |
| **scripts container** (ephemeral) | Reads `.env` vars, calls Ollama or paid API, writes the note |
| **Ollama** (container) | Runs the AI model on your GPU |
| **Obsidian** (host app) | Watches the vault folder, shows the note instantly |

```
2brain "how to fix GPU OOM in Ollama" -f Troubleshooting
    │
    ├── reads .env  (model, provider, etc.)
    │
    ├── HTTP POST → http://localhost:11434  →  Ollama container
    │                                              │
    │                                         AI generates content
    │                                              │
    ◄──────────────────────────────────────────────┘
    │
    └── writes vault/Troubleshooting/how-to-fix-gpu-oom-in-ollama.md
                │
                └── Obsidian picks it up instantly
```

Every note always looks like this — same structure, every time, no exceptions:

```markdown
---
title: "how to fix GPU OOM in Ollama"
tags:
  - ollama
  - gpu
  - troubleshooting
created: 2026-06-21
folder: Troubleshooting
---

## Summary
Short explanation in plain language.

## Key Points
- bullet
- bullet

## Steps
1. step one
2. step two
```

---

## Obsidian

Obsidian is a desktop app that runs on your host. It has no idea Docker exists.

- Open Obsidian → **Open folder as vault** → point it at `vault/`
- Every note `2brain` creates appears there instantly (Obsidian watches the folder)
- **Search by title:** `Ctrl+O`
- **Full-text search:** `Ctrl+Shift+F`
- **Graph view:** `Ctrl+G` — shows connections between notes via `[[wikilinks]]`

The graph starts sparse. As notes accumulate and link to each other, it fills up.

Notes include visual elements when useful:

- **Mermaid diagrams** — flowcharts, timelines, sequence diagrams, mindmaps (rendered natively by Obsidian)
- **Callouts** — `> [!TIP]`, `> [!WARNING]`, `> [!NOTE]`, `> [!IMPORTANT]` highlight key info at a glance
- **Excalidraw placeholders** — appear when a concept benefits from a hand-drawn diagram (requires the Excalidraw Obsidian plugin)

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

### 2. Register `2brain` as a global command

Add this to your `nano ~/.zshrc` or `nano ~/.bashrc` (use `echo $SHELL` to know which one), and add this line in the end:

```bash
export KNOWLEDGE_HUB="$HOME/knowledge-hub"   # WARNING: adjust path if different
alias 2brain="$KNOWLEDGE_HUB/scripts/2brain.sh"
```


Then reload:

```bash
source ~/.zshrc
```

Now `2brain` works from any directory on this machine.

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

Done. From now on: type `2brain`, note appears in Obsidian.

---

## Daily usage

### Generate a note from a topic

```bash
2brain "topic"
```

```bash
2brain "what is VRAM and why does it matter for LLMs"
2brain "docker compose cheat sheet"
2brain "how to use git stash"
```

Lands in `vault/Inbox/` by default.

### Route to the right folder with `-f`

```bash
2brain "topic" -f Folder
```

| Folder | What goes there |
|---|---|
| `Inbox` | Default. Capture first, sort later |
| `Guides` | Step-by-step, how-tos |
| `Troubleshooting` | Problem → cause → fix |
| `Projects` | Project-specific notes |
| `Reference` | Stable facts, tables, cheat sheets |

```bash
2brain "how to debug CUDA OOM errors" -f Troubleshooting
2brain "ollama model selection guide" -f Reference
2brain "how to set up a Python venv" -f Guides
2brain "knowledge-hub architecture decisions" -f Projects
```

### Custom title

```bash
2brain "explain quantization in simple terms" --title "Quantization explained"
```

### Digest an existing file with `--from-file`

Feed any file to the AI — it restructures the content into a proper note.

```bash
# markdown or text
2brain --from-file ./my-notes.md -f Guides
2brain --from-file ./my-notes.md -f Reference --title "Ollama reference"

# PDF (requires: pip install pypdf)
2brain --from-file ./paper.pdf -f Reference

# audio/video — AI transcribes then writes the note (requires: pip install faster-whisper)
2brain --from-file ./meeting-recording.mp3 -f Projects
2brain --from-file ./tutorial.mp4 -f Guides --title "Docker networking tutorial"
2brain --from-file ./voice-memo.m4a -f Inbox
```

Supported audio/video: `.mp3` `.mp4` `.wav` `.m4a` `.webm` `.ogg` `.flac`

Paths can be relative to wherever you are — `./filename`, `../other/file.md`, absolute paths all work.

### Add extra instructions with `--prompt`

Guide the AI when digesting a file — focus on specific aspects, exclude sections, change the output style.

```bash
2brain --from-file ./raw-notes.md --prompt "focus on setup steps only, skip theory" -f Guides
2brain --from-file ./meeting.mp3 --prompt "extract action items only" -f Projects
2brain --from-file ./paper.pdf --prompt "explain for a non-expert audience" -f Reference
```

### Explore mode — split into multiple notes

Instead of one note, the AI plans a set of focused subtopics and generates a note for each. Useful for broad topics or dense files.

```bash
# AI decides how many notes (usually 3-6)
2brain "Docker networking" --explore -f Guides
2brain --from-file ./raw-notes.md --explore -f Guides

# Force exactly N notes
2brain "Docker networking" --split 4 -f Guides
2brain --from-file ./raw-notes.md --split 3 -f Reference

# Generate each note independently (no shared context between notes)
2brain "Docker networking" --explore --no-context -f Guides

# Combine with --prompt
2brain --from-file notes.md --explore --prompt "focus on practical usage, skip history" -f Guides
```

Each note lands in the same target folder. The subtopic plan is printed before generation starts so you can see what's coming.

### Link notes together with `--link`, `--relink`, `--relink-all`

Obsidian has a **graph view** (`Ctrl+G`) that draws a map of your notes as dots connected by lines. For two notes to be connected, one note must contain a `[[wikilink]]` that references the other note by title. Without links, the graph is a bunch of isolated dots and Obsidian's search and navigation features are much weaker.

**The problem:** when the AI generates a note, it doesn't know what other notes you have. So by default, it can't add links to them.

**The solution:** the three link flags solve this in different ways.

---

#### `--link` — add links while generating a new note

Before calling the AI, the script scans your entire vault and collects all note titles. It passes that list to the AI in the same prompt, so the AI can write `[[Ollama]]` or `[[model-quantization]]` inline where the content actually relates to those notes.

```bash
2brain "quantization formats for local LLMs" -f Reference --link
2brain --from-file ./my-notes.md -f Guides --link
2brain "Docker networking" --explore -f Guides --link
```

This is the flag to use every time you create a new note and want it to connect to your existing vault. The AI will only add a link when it genuinely makes sense — it won't force connections.

> **Note:** links are only as good as your vault. Early on when you have few notes, `--link` won't add much. As your vault grows, it becomes increasingly valuable.

---

#### `--relink FILE` — add links to one existing note

Takes a note that already exists in the vault and asks the AI to add `[[wikilinks]]` to it — without changing anything else. The note content, structure, and frontmatter are preserved exactly; only links are injected.

```bash
2brain --relink vault/Reference/Ollama.md
2brain --relink vault/Guides/graphify.md
```

Use this to retrofit old notes that were created before `--link` existed, or any time you want to link a specific note.

> The original file is overwritten. Use `git diff` to review what was added.

---

#### `--relink-all` — add links to every note in the vault

Runs `--relink` logic on every `.md` file in the vault, one by one. Use `-f` to limit it to a single folder.

```bash
2brain --relink-all                  # entire vault
2brain --relink-all -f Reference     # only the Reference folder
2brain --relink-all -f Guides
```

Each note is processed in a separate AI call, so this takes a while on a large vault. Run it once after you have a good collection of notes and connections start to emerge.

> All files are overwritten in place. Commit before running if you want a checkpoint.

---

### Rework an existing note with `--rework`

Rewrites a note already in the vault — same file, same path, overwritten in place. Title and folder are read from the note's frontmatter automatically.

```bash
2brain --rework vault/Guides/graphify.md
2brain --rework vault/Inbox/ollama.md --prompt "add a section on GPU memory management"
2brain --rework vault/Guides/vram-with-models-in-the-ollama-list.md --title "VRAM Guide"
```

> The original file is overwritten. Use `git diff` to review what changed.

---

## Practical examples

**You just spent 2 hours debugging something:**
```bash
2brain "podman GPU passthrough failing with CUDA error 35" -f Troubleshooting
```

**You watched a tutorial and want to keep the key points:**
```bash
2brain --from-file ./tutorial-notes.mp4 -f Guides
```

**You read something useful:**
```bash
2brain "RAG vs fine-tuning — when to use which" -f Reference
```

**You set up a new tool:**
```bash
2brain "how to set up Ollama with Docker Compose on Manjaro" -f Guides
```

**Quick references you'll look up constantly:**
```bash
2brain "git commands I always forget" -f Reference
2brain "docker compose cheat sheet" -f Reference
```

## Using a paid AI provider

Add the API key to `.env`, define a preset for it, and either set it as your default or pass `--preset` when you want to use it.

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
