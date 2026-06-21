#!/usr/bin/env python3
"""
2brain — create a structured Obsidian note via AI.

Entry point. Parses CLI arguments, applies the active preset, then calls the
right builder function and writes the note(s) to the vault.

The heavy logic lives in:
  config.py    — env vars and constants
  providers.py — LLM adapters (Ollama, Anthropic, OpenAI)
  readers.py   — file readers (text, PDF, audio, HTML)
  builder.py   — prompts and note construction
  utils.py     — die(), slugify()

Usage:
  python main.py "topic" [-f Folder] [--title "Title"]
  python main.py --from-file path/to/file.md [-f Guides] [--title "Title"]
  python main.py --from-file notes.md --prompt "focus on setup steps, skip theory"
  python main.py "topic" --explore -f Guides
  python main.py --from-file notes.md --split 4 -f Guides
  python main.py --rework vault/Guides/my-note.md
  python main.py "topic" --preset smart
  python main.py "topic" --preset local --explore
  python main.py "topic" --link                    # generate + add [[wikilinks]] to vault notes
  python main.py --relink vault/Reference/Ollama.md  # add [[wikilinks]] to one existing note
  python main.py --relink-all                      # add [[wikilinks]] to all notes in the vault
  python main.py --relink-all -f Reference         # limit to one folder

Supported file types: .md .txt .pdf .html .mp3 .mp4 .wav .m4a .webm .ogg .flac
Supported providers:  ollama | anthropic | openai  (set via presets in .env)
"""
import argparse
from datetime import date
from pathlib import Path

# Import the module object so we can mutate config.PROVIDER / config.MODEL at runtime.
# "from config import PROVIDER" would give us a copy that ignores later changes.
import config
from config import VAULT_PATH, FOLDERS  # these are never mutated at runtime
from utils import die, slugify
from readers import read_source
from builder import (
    generate_note,
    generate_note_with_context,
    digest_note,
    digest_subtopic,
    plan_notes,
    build_frontmatter,
    link_note,
)


# --- Helpers -----------------------------------------------------------------

def _parse_frontmatter(path: Path) -> dict[str, str]:
    """Return all key-value pairs from a note's YAML frontmatter as a dict."""
    result: dict[str, str] = {}
    in_frontmatter = False
    for line in path.read_text().splitlines():
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break  # second --- means frontmatter ended
        if in_frontmatter and ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _build_vault_index() -> dict:
    """Return {path: title} for every .md in the vault. Single rglob pass shared by all callers."""
    index = {}
    for md_file in sorted(VAULT_PATH.rglob("*.md")):
        fm = _parse_frontmatter(md_file)
        index[md_file] = fm.get("title") or md_file.stem.replace("-", " ").replace("_", " ")
    return index


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (raw_frontmatter_block, body). Frontmatter block includes both --- delimiters."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "".join(lines[: i + 1]), "".join(lines[i + 1:])
    return "", text


def _apply_preset(args: argparse.Namespace) -> None:
    """Switch to a non-default preset if --preset was passed."""
    if not args.preset:
        return
    name = args.preset.lower()
    if name not in config.PRESETS:
        die(f"preset '{name}' not defined — add PRESET_{name.upper()}=provider:model to .env")
    # tuple unpacking: PRESETS["smart"] = ("anthropic", "claude-sonnet-4-6")
    config.PROVIDER, config.MODEL = config.PRESETS[name]


def _write_note(content: str, tags: list[str], title: str, folder: str, folder_path: Path) -> None:
    """Write a single note to disk. Appends today's date to filename if it already exists."""
    filename = slugify(title) + ".md"
    filepath = folder_path / filename
    if filepath.exists():
        # avoid silently overwriting a note with the same slug
        filepath = folder_path / (slugify(title) + f"-{date.today().isoformat()}.md")
    filepath.write_text(build_frontmatter(title, tags, folder) + content)
    print(f"Created  : {filepath}")


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a structured Obsidian note via AI")

    # nargs="?" makes this positional argument optional (0 or 1 values allowed)
    parser.add_argument("topic", nargs="?", help="What to write a note about")

    # choices= restricts accepted values — argparse rejects anything not in the list
    # default=None so --relink-all can detect "no -f given" and scan the whole vault
    parser.add_argument("-f", "--folder", choices=FOLDERS, default=None,
                        help="Target vault folder (default: Inbox)")
    parser.add_argument("--title", help="Override the auto-generated note title")
    parser.add_argument("--from-file", metavar="FILE",
                        help="Digest an existing file instead of generating from scratch")
    parser.add_argument("--prompt", metavar="INSTRUCTIONS",
                        help="Extra instructions when digesting a file (e.g. 'focus on X, skip Y')")
    # action="store_true" — flag with no value; True if passed, False otherwise
    parser.add_argument("--explore", action="store_true",
                        help="Split into multiple notes; AI decides how many (usually 3-6)")
    parser.add_argument("--split", type=int, metavar="N",
                        help="Split into exactly N notes (implies explore mode)")
    # dest= renames the attribute — argparse turns --no-context into args.no_context (valid Python)
    parser.add_argument("--no-context", action="store_true", dest="no_context",
                        help="Generate each subtopic independently without source context")
    parser.add_argument("--rework", metavar="FILE",
                        help="Rework an existing vault note in place (overwrites the file)")
    parser.add_argument("--preset", metavar="NAME",
                        help="Use a named preset (overrides DEFAULT_PRESET from .env)")
    parser.add_argument("--link", action="store_true",
                        help="Scan the vault and pass all note titles to the AI so it can add [[wikilinks]] while generating")
    parser.add_argument("--relink", metavar="FILE",
                        help="Add [[wikilinks]] to a single existing note without regenerating its content")
    parser.add_argument("--relink-all", action="store_true", dest="relink_all",
                        help="Add [[wikilinks]] to all notes in the vault (use -f to limit to one folder)")
    parser.add_argument("--merge", nargs="+", metavar="FILE",
                        help="Merge two or more files into one note (combine with --explore to split the result)")

    args = parser.parse_args()

    if not args.rework and not args.relink and not args.relink_all and not args.from_file and not args.topic and not args.merge:
        parser.error("provide a topic, --from-file, --rework, --relink, --relink-all, or --merge")

    _apply_preset(args)
    print(f"Provider : {config.PROVIDER}  |  Model: {config.MODEL}")

    # --- Relink a single existing note ---------------------------------------

    if args.relink:
        src = Path(args.relink)
        if not src.exists():
            die(f"file not found: {src}")
        fm = _parse_frontmatter(src)
        current_title = fm.get("title") or src.stem
        vault_titles = [t for t in _build_vault_index().values() if t != current_title]
        fm_raw, body = _split_frontmatter(src.read_text())
        print(f"Relinking: {src} ({len(vault_titles)} notes in index) ...")
        new_body = link_note(body, vault_titles)
        src.write_text(fm_raw + "\n" + new_body.strip() + "\n")
        print(f"Done     : {src}")
        return

    # --- Relink all notes in the vault (or a folder) -------------------------

    if args.relink_all:
        vault_index = _build_vault_index()
        all_titles = list(vault_index.values())
        if args.folder:
            folder_path = VAULT_PATH / args.folder
            items = [(p, t) for p, t in vault_index.items() if p.parent == folder_path]
        else:
            items = list(vault_index.items())
        print(f"Relinking: {len(items)} notes ({len(all_titles)} in index) ...")
        for note, current_title in items:
            titles_without_self = [t for t in all_titles if t != current_title]
            fm_raw, body = _split_frontmatter(note.read_text())
            print(f"  → {note.name} ...")
            new_body = link_note(body, titles_without_self)
            note.write_text(fm_raw + "\n" + new_body.strip() + "\n")
        print(f"Done     : {len(items)} notes relinked")
        return

    # --- Merge multiple files into one note (or split with --explore) --------

    if args.merge:
        paths = [Path(p) for p in args.merge]
        for p in paths:
            if not p.exists():
                die(f"file not found: {p}")

        combined = "\n\n".join(
            f"--- SOURCE: {p.name} ---\n\n{read_source(p)}" for p in paths
        )

        title = args.title or paths[0].stem.replace("-", " ").replace("_", " ")

        if args.folder:
            folder = args.folder
        else:
            fm = _parse_frontmatter(paths[0])
            folder = fm.get("folder") if fm.get("folder") in FOLDERS else "Inbox"
        folder_path = VAULT_PATH / folder
        folder_path.mkdir(parents=True, exist_ok=True)

        if args.link:
            vault_titles = list(_build_vault_index().values())
            print(f"Linking  : vault index loaded ({len(vault_titles)} notes)")
        else:
            vault_titles = None

        print(f"Merging  : {len(paths)} file(s) → '{title}' ...")

        if args.explore or args.split is not None:
            subtopics = plan_notes(combined, n=args.split)
            print(f"Subtopics: {', '.join(subtopics)}")
            for subtopic in subtopics:
                print(f"Generating: '{subtopic}' ...")
                body, tags, _ = digest_subtopic(subtopic, combined, prompt=args.prompt, vault_titles=vault_titles)
                _write_note(body, tags, subtopic, folder, folder_path)
        else:
            body, tags, llm_title = digest_note(combined, prompt=args.prompt, vault_titles=vault_titles)
            _write_note(body, tags, args.title or llm_title or title, folder, folder_path)
        return

    # --- Rework an existing note in place ------------------------------------

    if args.rework:
        src = Path(args.rework)
        if not src.exists():
            die(f"file not found: {src}")
        fm = _parse_frontmatter(src)
        folder = fm.get("folder") if fm.get("folder") in FOLDERS else (args.folder or "Inbox")
        title = args.title or fm.get("title") or src.stem.replace("-", " ").replace("_", " ")
        print(f"Reworking: {src}")
        body, tags, llm_title = digest_note(read_source(src), prompt=args.prompt)
        src.write_text(build_frontmatter(args.title or llm_title or title, tags, folder) + body)
        print(f"Done     : {src}")
        return  # stop here — skip the normal note-creation flow below

    # --- Resolve source and title --------------------------------------------

    src = None
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            die(f"file not found: {src}")
        # .stem = filename without extension → "my-notes.md" becomes "my notes"
        title = args.title or src.stem.replace("-", " ").replace("_", " ")
    else:
        title = args.title or args.topic

    folder_path = VAULT_PATH / (args.folder or "Inbox")
    folder_path.mkdir(parents=True, exist_ok=True)  # create folder if it doesn't exist yet
    print(f"Target   : {folder_path}")

    if args.link:
        vault_titles = list(_build_vault_index().values())
        print(f"Linking  : vault index loaded ({len(vault_titles)} notes)")
    else:
        vault_titles = None

    # --- Explore / split mode (multiple notes) --------------------------------

    # "args.split is not None" not "args.split" — because --split 0 would be falsy but valid
    if args.explore or args.split is not None:
        plan_content = read_source(src) if src else args.topic
        print(f"Planning : subtopics for '{title}' ...")
        subtopics = plan_notes(plan_content, n=args.split)
        print(f"Subtopics: {', '.join(subtopics)}")
        for subtopic in subtopics:
            print(f"Generating: '{subtopic}' ...")
            if src and not args.no_context:
                body, tags, _ = digest_subtopic(subtopic, plan_content, prompt=args.prompt, vault_titles=vault_titles)
            elif not src and not args.no_context:
                body, tags, _ = generate_note_with_context(subtopic, args.topic, vault_titles=vault_titles)
            else:
                body, tags, _ = generate_note(subtopic, vault_titles=vault_titles)
            # _ discards llm_title — plan titles are already short
            _write_note(body, tags, subtopic, args.folder or "Inbox", folder_path)

    # --- Single note mode ----------------------------------------------------

    else:
        if src:
            print(f"Digesting: {src.name} ...")
            body, tags, llm_title = digest_note(read_source(src), prompt=args.prompt, vault_titles=vault_titles)
        else:
            print(f"Generating: '{title}' ...")
            body, tags, llm_title = generate_note(args.topic, vault_titles=vault_titles)
        # Priority: explicit --title > LLM suggestion > original topic/filename
        _write_note(body, tags, args.title or llm_title or title, args.folder or "Inbox", folder_path)


# Only runs when executed directly (python main.py ...), not when imported
if __name__ == "__main__":
    main()
