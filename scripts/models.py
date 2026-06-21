#!/usr/bin/env python3
"""
Model manager for non-Ollama models.

Usage:
  python models.py pull whisper/<size>   — download a Whisper model
  python models.py list                  — show downloaded models
  python models.py delete whisper/<size> — remove a Whisper model

Whisper sizes: tiny | base | small | medium | large-v2 | large-v3
Models are stored in MODELS_PATH/whisper/ (bind-mounted from ./models on the host).
"""
import shutil
import sys

from config import MODELS_PATH

WHISPER_SIZES = {"tiny", "base", "small", "medium", "large-v2", "large-v3"}


def cmd_pull(target: str) -> None:
    kind, _, size = target.partition("/")
    if kind != "whisper":
        _die(f"Unknown model type '{kind}'. Only 'whisper' is supported.")
    if size not in WHISPER_SIZES:
        _die(f"Unknown Whisper size '{size}'. Valid: {', '.join(sorted(WHISPER_SIZES))}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _die("faster-whisper not installed — run: pip install faster-whisper")

    whisper_dir = MODELS_PATH / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)
    print(f"Pulling whisper/{size} into {whisper_dir} ...")
    WhisperModel(size, device="cpu", download_root=str(whisper_dir))
    print(f"Done.")


def cmd_list() -> None:
    whisper_dir = MODELS_PATH / "whisper"
    if not whisper_dir.exists():
        print("No models downloaded yet.")
        return

    found = False
    for entry in sorted(whisper_dir.iterdir()):
        if entry.is_dir():
            size_mb = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file()) / 1024 / 1024
            print(f"  whisper/{entry.name}  ({size_mb:.0f} MB)")
            found = True
    if not found:
        print("No models downloaded yet.")


def cmd_delete(target: str) -> None:
    kind, _, size = target.partition("/")
    if kind != "whisper":
        _die(f"Unknown model type '{kind}'.")

    model_dir = MODELS_PATH / "whisper" / size
    if not model_dir.exists():
        _die(f"whisper/{size} not found in {MODELS_PATH / 'whisper'}")

    shutil.rmtree(model_dir)
    print(f"Deleted whisper/{size}.")


def _die(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _usage() -> None:
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        _usage()

    command = args[0]
    if command == "pull":
        if len(args) < 2:
            _die("Usage: models.py pull whisper/<size>")
        cmd_pull(args[1])
    elif command == "list":
        cmd_list()
    elif command == "delete":
        if len(args) < 2:
            _die("Usage: models.py delete whisper/<size>")
        cmd_delete(args[1])
    else:
        _die(f"Unknown command '{command}'. Valid: pull | list | delete")
