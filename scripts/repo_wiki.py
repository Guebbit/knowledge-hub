"""
LLM wiki generator for 2repo.

Uses graphify's native export commands after extraction:
- graphify export wiki
- graphify export obsidian

Outputs:
- <repo>/graphify-out/wiki/      (graphify-native wiki artifacts)
- <repo>/graphify-out/obsidian/  (graphify-native Obsidian artifacts)
- <repo>/wiki/                   (repo-root wiki copy)
- <vault>/<folder>/<repo-name>/  (Obsidian copy for second-brain)
"""
from pathlib import Path
import shutil
import subprocess

import config


def generate(repo_path: str, folder: str = "Projects") -> None:
    """Generate wiki pages from graphify output and mirror them to repo root + vault."""
    repo = Path(repo_path)
    graph_json = repo / "graphify-out" / "graph.json"
    if not graph_json.exists():
        print(f"Wiki     : skipped -- graph not found: {graph_json}")
        return

    wiki_out = repo / "graphify-out" / "wiki"
    obsidian_out = repo / "graphify-out" / "obsidian"
    repo_wiki_out = repo / "wiki"
    vault_out = config.VAULT_PATH / folder / repo.name
    allowed_roots = (repo.resolve(), config.VAULT_PATH.resolve())

    print(f"Wiki     : graphify export wiki (default -> {wiki_out})")
    try:
        subprocess.run(
            ["graphify", "export", "wiki"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Wiki     : graphify export wiki failed with code {exc.returncode}")
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip())
        return

    print("Wiki     : graphify export obsidian")
    try:
        subprocess.run(
            ["graphify", "export", "obsidian", "--dir", str(obsidian_out)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Wiki     : graphify export obsidian failed with code {exc.returncode}")
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip())
        return

    if _mirror_dir(wiki_out, repo_wiki_out, allowed_roots):
        print(f"Wiki     : {wiki_out} -> {repo_wiki_out}")
    else:
        print(f"Wiki     : mirror failed for {repo_wiki_out}")
    # Keep this independent so a repo-local wiki is still available even if vault sync fails.
    if _mirror_dir(obsidian_out, vault_out, allowed_roots):
        print(f"Wiki     : {obsidian_out} -> {vault_out}")
    else:
        print(f"Wiki     : mirror failed for {vault_out}")


def _mirror_dir(src: Path, dst: Path, allowed_roots: tuple[Path, ...]) -> bool:
    """Replace dst with a full copy of src."""
    if not src.exists():
        print(f"Wiki     : source not found, skipping copy: {src}")
        return False
    resolved_dst = dst.resolve()
    if not any(resolved_dst == root or root in resolved_dst.parents for root in allowed_roots):
        print(f"Wiki     : refused to copy outside allowed roots: {dst}")
        return False
    if dst.exists():
        try:
            shutil.rmtree(dst)
        except OSError as exc:
            print(f"Wiki     : failed to remove existing directory {dst}: {exc}")
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, dst)
    except OSError as exc:
        print(f"Wiki     : failed to copy directory {src} -> {dst}: {exc}")
        return False
    return True
