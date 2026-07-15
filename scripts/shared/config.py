"""
All configuration comes from environment variables.
In Docker, docker-compose.yml injects them automatically.
Outside Docker (host runs), load_dotenv reads .env directly.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # inside Docker env vars are already present — dotenv not needed

# --- Presets -----------------------------------------------------------------

# Parse all PRESET_* env vars into a dict of (provider, model) tuples.
# e.g. PRESET_DEEP=openai:gpt-4o
#   → PRESETS["deep"] = ("openai", "gpt-4o")
PRESETS: dict[str, tuple[str, str]] = {}
for _k, _v in os.environ.items():
    if _k.startswith("PRESET_") and ":" in _v:
        # partition(":") splits on the FIRST colon only → ("anthropic", ":", "model")
        _prov, _, _mod = _v.partition(":")
        # _k[7:] strips the "PRESET_" prefix (7 chars)
        PRESETS[_k[7:].lower()] = (_prov.lower(), _mod)

# Which preset is active when no --preset flag is passed
DEFAULT_PRESET: str = os.getenv("DEFAULT_PRESET", "fast").lower()

# Resolve active provider and model from the default preset.
# Falls back to local Ollama with a small model if DEFAULT_PRESET isn't defined.
# The comma-assignment unpacks the (provider, model) tuple in one line.
PROVIDER: str
MODEL: str
PROVIDER, MODEL = PRESETS.get(DEFAULT_PRESET, ("ollama", "qwen3:8b"))

# --- Ollama connection -------------------------------------------------------
#
# OLLAMA_BASE_URL is shared by two consumers with incompatible URL expectations:
#
#   graphify (external library) — uses an OpenAI-compatible client internally,
#     which constructs endpoints by appending to the base URL, so it needs /v1:
#       http://ollama:11434/v1  →  .../v1/chat/completions  ✓
#
#   Our scripts (providers.py) — call Ollama's native REST API at /api/generate.
#     The /v1 prefix must NOT be present here:
#       http://ollama:11434      →  .../api/generate         ✓
#       http://ollama:11434/v1   →  .../v1/api/generate      ✗ (404)
#
# Solution: .env stores OLLAMA_BASE_URL with /v1 so graphify works, and we strip
# it here before our code uses it. rstrip("/") removes a trailing slash first so
# removesuffix("/v1") matches regardless of trailing slashes.
OLLAMA_URL     = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/").removesuffix("/v1")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))  # env vars are strings — int() converts
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

# --- Claude Code CLI ----------------------------------------------------------

# Seconds to wait for `claude -p` to return. Same default as OLLAMA_TIMEOUT.
CLAUDE_CODE_TIMEOUT = int(os.getenv("CLAUDE_CODE_TIMEOUT", "600"))

# --- Vault ------------------------------------------------------------------

VAULT_PATH = Path(
    os.getenv("VAULT_PATH", str(Path(__file__).resolve().parent.parent / "vault"))
)
FOLDERS = ["Inbox", "Guides", "Troubleshooting", "Projects", "Reference"]

# --- Model files (Whisper etc.) ---------------------------------------------

MODELS_PATH = Path(
    os.getenv("MODELS_PATH", str(Path.home() / ".models"))
)
# set not list — membership checks (ext in AUDIO_EXTENSIONS) are O(1) on sets, O(n) on lists
AUDIO_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".webm", ".ogg", ".flac"}

# --- Generated paths (2repo) ------------------------------------------------
#
# Single source of truth for "what 2repo generates". Everything that must ignore
# generated files derives from these two constants instead of hardcoding its own
# copy: the git staleness pathspecs, _is_generated_path(), and the wiki's
# documentable-file filter. Add a generated location once, here.
GENERATED_DIR_PREFIXES = ("graphify-out/", ".claude/", ".cursor/")
GENERATED_FILES = ("CLAUDE.md", ".github/copilot-instructions.md")
