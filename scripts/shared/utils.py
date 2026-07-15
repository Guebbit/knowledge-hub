"""
Tiny helpers used across all modules.
Kept here so there's one place to change them, not one copy per file.
"""
import re
import sys
from datetime import datetime, timezone
from typing import NoReturn


def die(msg: str) -> NoReturn:
    """Print an error and exit immediately.

    Return type is NoReturn so type checkers know execution stops here — code
    after a die() call is unreachable, and callers annotated `-> str` etc. don't
    appear to fall through returning None.
    """
    # file=sys.stderr — errors go to the error stream, not stdout
    # This keeps error messages separate from normal output when piping commands
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)  # any non-zero exit code signals failure to the calling shell


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    """Turn any string into a safe lowercase filename with hyphens.

    Example: "How to fix GPU OOM!" → "how-to-fix-gpu-oom"
    """
    text = text.lower().strip()
    # [^\w\s-] matches anything that is NOT a word char, whitespace, or hyphen — delete it
    text = re.sub(r"[^\w\s-]", "", text)
    # Collapse runs of spaces/underscores/hyphens into a single hyphen
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60]  # cap at 60 chars so filenames stay readable
