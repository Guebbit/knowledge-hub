"""
File content readers.

read_source() is the only public function — it takes a Path and returns the
file's content as a plain string, regardless of file format.

To add a new file type: write a _read_X(path) function below, then add one
entry to _READERS at the bottom of this file. read_source() never needs to change.
"""
import os
import re
from pathlib import Path
from typing import Callable

from shared.config import AUDIO_EXTENSIONS, MODELS_PATH
from shared.utils import die


def read_source(path: Path) -> str:
    """Read a file and return its content as plain text."""
    # _READERS.get() looks up the reader for this extension.
    # Falls back to _read_text for .md, .txt, and anything not explicitly listed.
    reader = _READERS.get(path.suffix.lower(), _read_text)
    return reader(path)


# --- Format readers ----------------------------------------------------------
# All functions are private (_underscore) — call read_source(), not these directly.

def _read_text(path: Path) -> str:
    # errors="replace" turns unreadable bytes into ? instead of crashing
    return path.read_text(errors="replace")


def _read_audio(path: Path) -> str:
    """Transcribe audio/video to text using Whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper not installed — run: pip install faster-whisper")

    model_size = os.getenv("WHISPER_MODEL", "base")
    print(f"Transcribing '{path.name}' with Whisper ({model_size}) ...")

    whisper_dir = MODELS_PATH / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)  # create dir if it doesn't exist

    # device="auto" — Whisper picks GPU if available, falls back to CPU
    # compute_type="auto" — uses float16 on GPU, int8 on CPU (best speed/quality trade-off per device)
    # download_root — where to look for (and cache) the model weights
    model = WhisperModel(model_size, device="auto", compute_type="auto", download_root=str(whisper_dir))
    # transcribe() returns (segments_generator, transcription_info); we only need the segments
    segments, _ = model.transcribe(str(path))

    # transcribe() returns timed chunks — join them into one string with spaces between
    return " ".join(seg.text.strip() for seg in segments)


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF page by page."""
    try:
        import pypdf
    except ImportError:
        die("pypdf not installed — run: pip install pypdf")

    reader = pypdf.PdfReader(str(path))
    # extract_text() returns None for image-only pages — "or ''" turns None into an empty string
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_html(path: Path) -> str:
    """Strip HTML tags and return the readable text."""
    text = path.read_text(errors="replace")
    try:
        from bs4 import BeautifulSoup
        # "html.parser" is Python's built-in parser — no extra C library needed
        return BeautifulSoup(text, "html.parser").get_text()
    except ImportError:
        # Fallback if BeautifulSoup isn't installed: regex that removes anything inside < >
        return re.sub(r"<[^>]+>", " ", text)


# Dispatch table — maps file extensions to their reader functions.
# Defined here (after the functions) so all names are already in scope.
# Add a new type by adding one entry here + a _read_X function above.
_READERS: dict[str, Callable[[Path], str]] = {
    # Expand AUDIO_EXTENSIONS set into individual entries, all pointing to _read_audio
    **{ext: _read_audio for ext in AUDIO_EXTENSIONS},
    ".pdf":  _read_pdf,
    ".html": _read_html,
}
