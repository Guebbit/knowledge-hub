"""
Prompts and note construction.

This module only knows what a finished note should look like — it doesn't know
which provider is used or where the source content comes from.

To change note structure or style: edit the prompts and build_frontmatter() here.
"""
import json
import re
from datetime import date

from providers import call_llm


# --- Prompts -----------------------------------------------------------------
#
# HOW THE TWO-STAGE PROMPT SYSTEM WORKS:
#
# These strings are built in two passes:
#
#   Pass 1 (at import time) — Python's f-string fills in {_RULES} immediately.
#              Single braces like {_RULES} are replaced right now.
#
#   Pass 2 (at call time) — .format(topic=...) fills in the remaining placeholders.
#              Double braces {{topic}} become {topic} after pass 1,
#              so they're still available for .format() in pass 2.

_RULES = """RULES:
- Output ONLY the note body — no frontmatter, no H1 title at the top
- Use ## for section headers
- Prefer bullet points over long paragraphs
- First section must always be ## Summary (2-3 sentences max, plain language)
- ADHD friendly
- Second to last line: TITLE: Clean Short Title
  (2-5 words, Title Case, no filler like "Introduction to", "How to", "Understanding")
- Last line: TAGS: tag1, tag2, tag3
  (2-5 lowercase tags, comma-separated)

VISUALS — use when they genuinely aid understanding, not decoratively:
- Mermaid (```mermaid blocks):
    flowchart TD/LR  → processes, pipelines, decision trees
      Color nodes via classDef: green(#90EE90/#228B22)=success, red(#FFB6C1/#DC143C)=danger,
      yellow(#FFD700/#B8860B)=warning, blue(#ADD8E6/#00008B)=neutral
    sequenceDiagram  → request/response flows, API call sequences
    erDiagram        → data models and entity relationships
    timeline         → chronological events
    mindmap          → concept hierarchies and topic maps
- Callouts:
    > [!TIP] best practices    > [!WARNING] gotchas    > [!DANGER] critical issues
    > [!NOTE] extra context    > [!IMPORTANT] key takeaways
- Excalidraw placeholder when a freehand sketch fits better than a structured diagram:
    > [!NOTE] Excalidraw: [one-line description of what to sketch]
- Tables for comparisons (vs, pros/cons, options, specs)"""

# {_RULES} expands now (pass 1). {{topic}} stays as {topic} for .format() later (pass 2).
_GENERATE_PROMPT = f"""You are writing notes for an Obsidian second-brain vault.

{{topic}}

{_RULES}
{{vault_context}}
Topic: {{topic}}
"""

_DIGEST_PROMPT = f"""You are restructuring raw content into a clean Obsidian second-brain note.

SOURCE CONTENT:
{{source}}

{_RULES}
- Reorganize and deduplicate — remove noise, keep the useful parts
{{vault_context}}{{extra}}"""

# Not an f-string — no _RULES to embed, placeholders filled with .format() directly
_PLAN_PROMPT = """You are planning an Obsidian second-brain vault.

CONTENT:
{content}

List {n_instruction} focused, non-overlapping subtopics to turn into individual notes.
Use short, 2-4 word titles in Title Case. No filler words ("Introduction to", "How to", "What is").
Return ONLY a valid JSON array of title strings, nothing else.
Example: ["Bridge Networks", "Overlay Networking", "DNS Resolution", "Port Mapping"]"""

_GENERATE_WITH_CONTEXT_PROMPT = f"""You are writing notes for an Obsidian second-brain vault.
This note is one of several covering the broader topic: {{context}}

{_RULES}
{{vault_context}}
Topic: {{subtopic}}
"""

_DIGEST_SUBTOPIC_PROMPT = f"""You are extracting and expanding a focused subtopic from source content into an Obsidian second-brain note.

SOURCE CONTENT:
{{source}}

FOCUS FOR THIS NOTE: {{subtopic}}

{_RULES}
- Extract only what's relevant to the focus topic — ignore unrelated parts
- Expand with relevant knowledge beyond what's in the source
- Reorganize and deduplicate — remove noise
{{vault_context}}{{extra}}"""

# Not an f-string — placeholders filled with .format() directly
_LINK_PROMPT = """You are adding [[wikilinks]] to an existing Obsidian note.

EXISTING NOTE BODY:
{body}

NOTES IN THIS VAULT:
{titles}

Insert [[Note Title]] links inline where the text genuinely relates to an existing note.
Rules:
- Link on first mention only, not every occurrence
- Only ADD links — do NOT change any other text, structure, or formatting
- Skip a link if the connection is weak or forced
- Return ONLY the updated note body — no explanation, no frontmatter"""


# --- Public API --------------------------------------------------------------
# All generation functions return a 3-tuple: (body, tags, suggested_title).
# str | None means the value is either a string or None (Python 3.10+ union syntax).

def generate_note(topic: str, vault_titles: list[str] | None = None) -> tuple[str, list[str], str | None]:
    """Ask the LLM to write a note about a topic from scratch."""
    vault_context = _build_vault_context(vault_titles)
    return _generate(_GENERATE_PROMPT.format(topic=topic, vault_context=vault_context))


def digest_note(source: str, prompt: str | None = None, vault_titles: list[str] | None = None) -> tuple[str, list[str], str | None]:
    """Ask the LLM to restructure existing content (from a file) into a note."""
    vault_context = _build_vault_context(vault_titles)
    return _generate(_DIGEST_PROMPT.format(source=source, extra=_build_extra(prompt), vault_context=vault_context))


def plan_notes(content: str, n: int | None = None) -> list[str]:
    """Ask the LLM to return a JSON list of subtopic titles."""
    n_instruction = f"exactly {n}" if n else "3 to 6"
    raw = call_llm(_PLAN_PROMPT.format(content=content, n_instruction=n_instruction))
    raw = raw.strip()
    # The model sometimes wraps JSON in ```json ... ``` — strip those fences before parsing
    raw = re.sub(r"^```[^\n]*\n?", "", raw)   # remove opening fence
    raw = re.sub(r"\n?```\s*$", "", raw)       # remove closing fence
    return json.loads(raw.strip())             # json.loads turns a JSON string into a Python list


def generate_note_with_context(subtopic: str, context: str, vault_titles: list[str] | None = None) -> tuple[str, list[str], str | None]:
    """Generate a subtopic note that knows it belongs to a broader topic."""
    vault_context = _build_vault_context(vault_titles)
    return _generate(_GENERATE_WITH_CONTEXT_PROMPT.format(subtopic=subtopic, context=context, vault_context=vault_context))


def digest_subtopic(subtopic: str, source: str, prompt: str | None = None, vault_titles: list[str] | None = None) -> tuple[str, list[str], str | None]:
    """Extract and expand a focused subtopic from existing source content."""
    vault_context = _build_vault_context(vault_titles)
    return _generate(_DIGEST_SUBTOPIC_PROMPT.format(source=source, subtopic=subtopic, extra=_build_extra(prompt), vault_context=vault_context))


def link_note(body: str, vault_titles: list[str]) -> str:
    """Ask the LLM to inject [[wikilinks]] into an existing note body."""
    titles = "\n".join(f"- {t}" for t in vault_titles)
    return call_llm(_LINK_PROMPT.format(body=body, titles=titles))


def build_frontmatter(title: str, tags: list[str], folder: str) -> str:
    """Build the YAML frontmatter block prepended to every Obsidian note."""
    # join() builds "  - tag1\n  - tag2\n  - tag3" from a list
    tag_lines = "\n".join(f"  - {t}" for t in tags) if tags else "  - general"
    return (
        f"---\n"
        f"title: \"{title}\"\n"
        f"tags:\n{tag_lines}\n"
        f"created: {date.today().isoformat()}\n"  # isoformat() → "2026-06-21"
        f"folder: {folder}\n"
        f"---\n\n"
    )


# --- Internal helpers --------------------------------------------------------

def _build_extra(prompt: str | None) -> str:
    """Format an optional --prompt value into an instruction block for the LLM."""
    return f"\nADDITIONAL INSTRUCTIONS:\n{prompt}" if prompt else ""


def _build_vault_context(titles: list[str] | None) -> str:
    """Build the vault-index block injected into generation prompts when --link is set."""
    if not titles:
        return ""
    title_list = "\n".join(f"- {t}" for t in titles)
    return f"\nEXISTING NOTES — use [[Note Title]] to link where genuinely relevant (first mention only):\n{title_list}\n"


def _generate(prompt: str) -> tuple[str, list[str], str | None]:
    """Call the LLM and parse its response. Shared by all generation functions."""
    return _parse_response(call_llm(prompt))


def _strip_field(raw: str, field: str) -> tuple[str, str | None]:
    """Find and remove a FIELD: value line from the end of the text.

    Returns (remaining_text, field_value) or (original_text, None) if not found.
    Used to extract TAGS and TITLE from the LLM response.
    """
    # rf"..." = raw f-string: {field} is filled in, \n and $ are kept as regex tokens
    match = re.search(rf"\n{field}:\s*(.+)$", raw, re.IGNORECASE)
    if not match:
        return raw, None
    # raw[: match.start()] slices everything BEFORE the matched line
    return raw[: match.start()].strip(), match.group(1).strip()


def _parse_response(raw: str) -> tuple[str, list[str], str | None]:
    """Extract TITLE and TAGS from the end of the LLM response, return the cleaned body.

    The model is instructed to end its response with:
      TITLE: Short Title
      TAGS: tag1, tag2

    Strip TAGS first (last line), then TITLE (now last line). Order matters.
    """
    raw, tags_str = _strip_field(raw, "TAGS")
    # split(",") turns "tag1, tag2" into ["tag1", " tag2"] — strip() cleans each one
    tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()] if tags_str else []

    raw, llm_title = _strip_field(raw, "TITLE")
    return raw, tags, llm_title
