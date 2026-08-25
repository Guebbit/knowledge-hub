"""
Path scope for 2repo — which files the pipeline is allowed to document.

Backed by a hand-editable `.2repoignore` at the target repo root, so the scope
is inspectable and version-controllable alongside the code it describes rather
than hidden in 2repo's generated output.

The file holds two gitignore-syntax sections:

    [include]   restricts the documented set. Empty = every file.
    [exclude]   removes files from that set. Empty = nothing.

Both are evaluated against repo-relative POSIX paths via `pathspec`, so the
full gitignore vocabulary works — `src/**`, `**/*.test.ts`, `!keep/this.ts`.
Include is applied first, then exclude, so exclude always wins.

Scope is a *documentation* filter: it decides which files get a wiki page (and
therefore what reaches the vault and the Obsidian graph). It deliberately does
not touch graphify extraction — the dependency graph stays complete so neighbor
expansion and the module tier still see the real topology.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import pathspec
    import pathspec.util
except ImportError:  # pragma: no cover - pathspec is a declared dependency
    pathspec = None

SCOPE_FILENAME = ".2repoignore"

_INCLUDE_SECTION = "[include]"
_EXCLUDE_SECTION = "[exclude]"

_HEADER = f"""\
# 2repo scope — which files 2repo documents.
#
# Gitignore-style patterns, one per line, matched against repo-relative paths:
#   src/**            every file under src/
#   **/*.test.ts      every .test.ts file, anywhere
#   docs/**           the whole docs tree
#
# {_INCLUDE_SECTION} restricts the documented set. Empty = every file.
# {_EXCLUDE_SECTION} removes files from that set. Empty = nothing. Exclude wins.
#
# Regenerate the prompt that wrote this with: 2repo <repo> --rescope
"""


@dataclass(frozen=True)
class Scope:
    """An include/exclude pattern pair, evaluated against repo-relative paths."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.include and not self.exclude

    def matches(self, rel_path: str) -> bool:
        """True when rel_path is inside the scope.

        Written as three explicit branches rather than one boolean expression
        because the branches *are* the specification: restrict by include, then
        subtract exclude, then default to allow. Collapsing them (ruff's SIM103)
        would save a line and hide the precedence.
        """
        if self.include and not _spec(self.include).match_file(rel_path):
            return False
        if self.exclude and _spec(self.exclude).match_file(rel_path):  # noqa: SIM103
            return False
        return True

    def describe(self) -> str:
        if self.is_empty:
            return "everything (no include/exclude patterns)"
        parts = []
        if self.include:
            parts.append(f"include={', '.join(self.include)}")
        if self.exclude:
            parts.append(f"exclude={', '.join(self.exclude)}")
        return "  ".join(parts)


_SPEC_CACHE: dict[tuple[str, ...], object] = {}


def _spec(patterns: tuple[str, ...]):
    """Compile (and memoize) a pathspec matcher for a pattern tuple.

    Memoized because matches() is called once per candidate file — recompiling
    the same handful of patterns a thousand times per run is pure waste.
    """
    cached = _SPEC_CACHE.get(patterns)
    if cached is None:
        if pathspec is None:
            raise RuntimeError(
                "pathspec is not installed — required for .2repoignore pattern matching"
            )
        cached = pathspec.PathSpec.from_lines(_pattern_factory(), patterns)
        _SPEC_CACHE[patterns] = cached
    return cached


def _pattern_factory() -> str:
    """Return the gitignore pattern factory this pathspec version prefers.

    pathspec renamed `gitwildmatch` to `gitignore`; the old name still works but
    emits a DeprecationWarning on newer releases, and the container and the host
    do not always carry the same version. Pick whichever is registered so neither
    environment prints noise. The scope tests assert the matching semantics, so a
    behavioural difference between the two would surface there rather than here.
    """
    try:
        pathspec.util.lookup_pattern("gitignore")
    except (AttributeError, LookupError):
        return "gitwildmatch"
    return "gitignore"


def scope_file(repo_path: str) -> Path:
    return Path(repo_path) / SCOPE_FILENAME


def _clean(lines: list[str]) -> tuple[str, ...]:
    """Drop comments and blank lines from one section's raw lines."""
    return tuple(
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def load(repo_path: str) -> Scope:
    """Read the scope from `.2repoignore`, or an empty scope when absent/unreadable."""
    path = scope_file(repo_path)
    if not path.is_file():
        return Scope()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Scope()

    section: str | None = None
    buckets: dict[str, list[str]] = {_INCLUDE_SECTION: [], _EXCLUDE_SECTION: []}
    for line in text.splitlines():
        marker = line.strip().lower()
        if marker in (_INCLUDE_SECTION, _EXCLUDE_SECTION):
            section = marker
            continue
        if section:
            buckets[section].append(line)
    return Scope(include=_clean(buckets[_INCLUDE_SECTION]), exclude=_clean(buckets[_EXCLUDE_SECTION]))


def save(repo_path: str, scope: Scope) -> Path:
    """Write the scope back to `.2repoignore`, preserving the explanatory header."""
    path = scope_file(repo_path)
    body = [_HEADER, _INCLUDE_SECTION]
    body.extend(scope.include)
    body.append("")
    body.append(_EXCLUDE_SECTION)
    body.extend(scope.exclude)
    path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return path


def _split_patterns(raw: str) -> tuple[str, ...]:
    """Parse a comma- or whitespace-separated pattern list from CLI/env input."""
    return tuple(part for chunk in raw.split(",") for part in chunk.split() if part)


def _prompt_patterns(label: str, examples: str) -> tuple[str, ...]:
    """Ask for one pattern list, treating an unreadable stdin as 'no patterns'.

    isatty() is not enough on its own: a container runtime can hand the process a
    pty with nothing attached to it (podman-compose allocates one by default),
    which turns a bare input() into a silent hang. Failing open to the permissive
    answer keeps an unattended run moving instead of blocking forever.
    """
    print(f"  {label}")
    print(f"    examples: {examples}", flush=True)
    try:
        return _split_patterns(input("    > ").strip())
    except (EOFError, KeyboardInterrupt):
        print("\n    (no input available — leaving this blank)")
        return ()


def resolve(
    repo_path: str,
    *,
    cli_include: str | None = None,
    cli_exclude: str | None = None,
    rescope: bool = False,
    interactive: bool = True,
) -> Scope:
    """Resolve the active scope and persist it.

    Precedence: --include/--exclude > REPO_INCLUDE/REPO_EXCLUDE > .2repoignore >
    interactive prompt (first run on a repo, or --rescope) > everything.
    """
    if cli_include is not None or cli_exclude is not None:
        # Merge onto what is already on disk: passing only --exclude must not
        # silently wipe the include list (and vice versa). Pass an empty string
        # to clear one side deliberately.
        current = load(repo_path)
        scope = Scope(
            include=_split_patterns(cli_include) if cli_include is not None else current.include,
            exclude=_split_patterns(cli_exclude) if cli_exclude is not None else current.exclude,
        )
        save(repo_path, scope)
        return scope

    env_include = os.getenv("REPO_INCLUDE")
    env_exclude = os.getenv("REPO_EXCLUDE")
    if env_include or env_exclude:
        return Scope(
            include=_split_patterns(env_include or ""),
            exclude=_split_patterns(env_exclude or ""),
        )

    existing = scope_file(repo_path).is_file()
    if existing and not rescope:
        return load(repo_path)

    if not interactive or not sys.stdin.isatty():
        # Non-interactive first run: document everything and leave no file behind,
        # so a later interactive run still gets the prompt.
        return load(repo_path) if existing else Scope()

    print(f"Scope    : which files should 2repo document?  (written to {SCOPE_FILENAME})")
    print("           Gitignore-style patterns, comma- or space-separated. Enter to accept the default.")
    include = _prompt_patterns(
        "Include paths (blank = everything):",
        "src/**, api/**",
    )
    exclude = _prompt_patterns(
        "Exclude paths (blank = nothing):",
        "**/*.test.ts, tests/**, docs/**",
    )
    scope = Scope(include=include, exclude=exclude)
    path = save(repo_path, scope)
    print(f"Scope    : {scope.describe()}  →  {path}")
    return scope
