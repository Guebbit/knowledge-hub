# 2brain — second brain (Obsidian + `2brain`)

**What it is:** a personal knowledge base that grows automatically as you learn things.

**How it works:** you type `2brain "what I just figured out"` → AI writes a clean, structured note → it appears in Obsidian instantly.

**Why it matters for ADHD:**
- Zero friction: one command, no decisions about format or where to save it
- Always the same structure: every note looks identical, so your brain doesn't have to re-learn how to read them
- Searchable forever: Obsidian's graph connects notes by topic — ideas you linked years ago resurface when relevant
- Offloads working memory: once it's written, you don't need to hold it in your head anymore

> Think of Obsidian as your external hard drive for knowledge. `2brain` is the "save" button.

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

### Chain mode — one note per topic

Pass multiple topics in one command — each gets its own AI call and its own note.

```bash
2brain "Docker networking" "Kubernetes pods" "Helm charts" -f Guides
2brain "JWT" "OAuth2" "PKCE" -f Reference
2brain "git rebase" "git stash" "git bisect"
```

Progress is printed as each note completes:

```
Chain    : 3 topics
[1/3] 'Docker networking' ...
Created  : vault/Guides/docker-networking.md
[2/3] 'Kubernetes pods' ...
Created  : vault/Guides/kubernetes-pods.md
[3/3] 'Helm charts' ...
Created  : vault/Guides/helm-charts.md
```

Combine with `--explore` to also split each topic into subtopic notes:

```bash
2brain "Networking" "Storage" "Security" --explore -f Guides
```

---

## Link notes together with `--link`, `--relink`, `--relink-all`

Obsidian has a **graph view** (`Ctrl+G`) that draws a map of your notes as dots connected by lines. For two notes to be connected, one note must contain a `[[wikilink]]` that references the other note by title. Without links, the graph is a bunch of isolated dots and Obsidian's search and navigation features are much weaker.

**The problem:** when the AI generates a note, it doesn't know what other notes you have. So by default, it can't add links to them.

**The solution:** the three link flags solve this in different ways.

---

### `--link` — add links while generating a new note

Before calling the AI, the script scans your entire vault and collects all note titles. It passes that list to the AI in the same prompt, so the AI can write `[[Ollama]]` or `[[model-quantization]]` inline where the content actually relates to those notes.

```bash
2brain "quantization formats for local LLMs" -f Reference --link
2brain --from-file ./my-notes.md -f Guides --link
2brain "Docker networking" --explore -f Guides --link
```

This is the flag to use every time you create a new note and want it to connect to your existing vault. The AI will only add a link when it genuinely makes sense — it won't force connections.

> **Note:** links are only as good as your vault. Early on when you have few notes, `--link` won't add much. As your vault grows, it becomes increasingly valuable.

---

### `--relink FILE` — add links to one existing note

Takes a note that already exists in the vault and asks the AI to add `[[wikilinks]]` to it — without changing anything else. The note content, structure, and frontmatter are preserved exactly; only links are injected.

```bash
2brain --relink vault/Reference/Ollama.md
2brain --relink vault/Guides/graphify.md
```

Use this to retrofit old notes that were created before `--link` existed, or any time you want to link a specific note.

> The original file is overwritten. Use `git diff` to review what was added.

---

### `--relink-all` — add links to every note in the vault

Runs `--relink` logic on every `.md` file in the vault, one by one. Use `-f` to limit it to a single folder.

```bash
2brain --relink-all                  # entire vault
2brain --relink-all -f Reference     # only the Reference folder
2brain --relink-all -f Guides
```

Each note is processed in a separate AI call, so this takes a while on a large vault. Run it once after you have a good collection of notes and connections start to emerge.

> All files are overwritten in place. Commit before running if you want a checkpoint.

---

## Rework an existing note with `--rework`

Rewrites a note already in the vault — same file, same path, overwritten in place. Title and folder are read from the note's frontmatter automatically.

```bash
2brain --rework vault/Guides/graphify.md
2brain --rework vault/Inbox/ollama.md --prompt "add a section on GPU memory management"
2brain --rework vault/Guides/vram-with-models-in-the-ollama-list.md --title "VRAM Guide"
```

> The original file is overwritten. Use `git diff` to review what changed.

---

## Merge existing notes with `--merge`

Combines two or more files into one clean, deduplicated note. Useful when you captured the same topic multiple times and ended up with duplicate or overlapping notes.

```bash
2brain --merge vault/Inbox/lora.md vault/Reference/lora.md -f Reference
2brain --merge vault/Inbox/lora.md vault/Reference/lora.md -f Reference --title "Low-rank Adaptation"
```

Folder and title default to the frontmatter of the first file if not specified. The AI deduplicates, reorganizes, and produces one clean output.

**Merge and immediately split into multiple notes:**

If the combined content is dense enough to split into focused subtopics, add `--explore` or `--split`:

```bash
2brain --merge notes1.md notes2.md notes3.md --explore -f Reference
2brain --merge notes1.md notes2.md --split 3 -f Guides
```

**Single file:** passing one path is equivalent to `--from-file` — it just digests and produces one note.

> The source files are not deleted automatically. Remove them manually once you are happy with the merged result.

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

---

See the main [README](../README.md) for setup, configuration, and troubleshooting shared with `2repo`.
