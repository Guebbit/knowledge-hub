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
        print(f"Wiki     : skipped — graph not found: {graph_json}")
        return

    wiki_out = repo / "graphify-out" / "wiki"
    obsidian_out = repo / "graphify-out" / "obsidian"
    repo_wiki_out = repo / "wiki"
    vault_out = config.VAULT_PATH / folder / repo.name

    print("Wiki     : graphify export wiki")
    result = subprocess.run(["graphify", "export", "wiki"], cwd=repo)
    if result.returncode != 0:
        print(f"Wiki     : graphify export wiki failed with code {result.returncode}")
        return

    print("Wiki     : graphify export obsidian")
    result = subprocess.run(
        ["graphify", "export", "obsidian", "--dir", str(obsidian_out)],
        cwd=repo,
    )
    if result.returncode != 0:
        print(f"Wiki     : graphify export obsidian failed with code {result.returncode}")
        return

    _replace_dir(wiki_out, repo_wiki_out)
    _replace_dir(obsidian_out, vault_out)
    print(f"Wiki     : {wiki_out} -> {repo_wiki_out}")
    print(f"Wiki     : {obsidian_out} -> {vault_out}")


def _replace_dir(src: Path, dst: Path) -> None:
    """Replace dst with a full copy of src."""
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
