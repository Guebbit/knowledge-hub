"""
Shared helpers for mirroring 2repo-generated Markdown into the Obsidian vault.

Both the wiki layer (repo/wiki.py) and the architecture layer (repo/arch.py)
mirror their generated pages into vault/Projects/<repo-name>/Generated/...; this
module holds the logic they share: detecting whether a usable vault is present,
resolving a human-readable repo name, and copying + pruning a directory of
Markdown pages.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from shared.config import FOLDERS


def vault_available(vault_path: Path) -> bool:
    """Return True when vault_path looks like a real, usable Obsidian vault.

    Mirroring is on by default (see _resolve_mirror_vault in repo.py), so this
    has to distinguish "a vault lives here" from "the bind mount exists but is
    empty". Two markers count: `.obsidian/` (Obsidian has opened it) or any of
    the standard 2brain folders (a vault scaffolded but not yet opened).
    """
    if not vault_path.is_dir():
        return False
    if (vault_path / ".obsidian").is_dir():
        return True
    return any((vault_path / folder).is_dir() for folder in FOLDERS)


def repo_display_name(repo_path: str) -> str:
    """Best-effort repository name: git origin basename, else directory name."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        name = result.stdout.strip().rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if name:
            return name
    return Path(repo_path).resolve().name


def mirror_markdown_tree(source: Path, destination: Path) -> Path:
    """Copy every *.md from source into destination and prune stale destination pages.

    The destination becomes an exact reflection of the source's Markdown pages:
    files present in destination but no longer in source are removed. Returns the
    destination path.
    """
    destination.mkdir(parents=True, exist_ok=True)
    source_pages = {page.name for page in source.glob("*.md")}
    for page in source.glob("*.md"):
        shutil.copy2(page, destination / page.name)
    for existing in destination.glob("*.md"):
        if existing.name not in source_pages:
            existing.unlink()
    return destination
