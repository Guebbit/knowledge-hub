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
    # Security allowlist: _mirror_dir refuses to write outside these two roots
    allowed_roots = (repo.resolve(), config.VAULT_PATH.resolve())

    print(f"Wiki     : graphify export wiki (default -> {wiki_out})")
    if not _run_graphify_export(["graphify", "export", "wiki"], repo, "wiki"):
        return

    print("Wiki     : graphify export obsidian")
    if not _run_graphify_export(
        ["graphify", "export", "obsidian", "--dir", str(obsidian_out)],
        repo,
        "obsidian",
    ):
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
    # resolve() turns relative paths and symlinks into an absolute real path
    # is_relative_to() checks that dst lives inside an allowed root — prevents writing to arbitrary paths
    resolved_dst = dst.resolve()
    if not any(resolved_dst.is_relative_to(root) for root in allowed_roots):
        print(f"Wiki     : refused to copy outside allowed roots: {dst}")
        return False
    if dst.exists():
        try:
            # shutil.rmtree() removes a directory and all its contents recursively (like rm -rf)
            shutil.rmtree(dst)
        except OSError as exc:
            print(f"Wiki     : failed to remove existing directory {dst}: {exc}")
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        # shutil.copytree() copies an entire directory tree from src to dst
        shutil.copytree(src, dst)
    except OSError as exc:
        print(f"Wiki     : failed to copy directory {src} -> {dst}: {exc}")
        return False
    return True


def _run_graphify_export(command: list[str], repo: Path, export_kind: str) -> bool:
    """Run a graphify export command and print failures consistently."""
    try:
        # check=True makes subprocess raise CalledProcessError if the exit code is non-zero,
        # instead of silently returning a result with returncode != 0
        # capture_output=True captures stdout/stderr as strings so we can print them on failure
        # text=True decodes byte output to str automatically
        subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # exc.returncode — the non-zero exit code from graphify
        # exc.stdout / exc.stderr — the captured output we can surface to the user
        print(f"Wiki     : graphify export {export_kind} failed with code {exc.returncode}")
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip())
        return False
    return True
