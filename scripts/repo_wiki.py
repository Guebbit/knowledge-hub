"""
LLM wiki generator — stub.

Planned: Karpathy-style wiki from graphify's graph.json into the Obsidian vault.

graphify's --wiki and --obsidian outputs are not exposed via the CLI (extract command).
They must be called through the Python API after extraction:

  from graphify.export import to_obsidian
  from graphify.wiki import to_wiki

  # Load graph.json produced by `graphify extract`
  # Build NetworkX graph via graphify.build.build_from_json()
  # Call to_obsidian(G, communities, obsidian_dest, ...) → one .md per node
  # Call to_wiki(G, communities, wiki_dest, ...)         → community overview articles

Two destinations:
  graphify-out/obsidian/ → vault/<folder>/<repo-name>/   (Obsidian-native, atomic pages)
  graphify-out/wiki/     → <repo>/wiki/                  (plain markdown overview)

Activate with: 2repo . --wiki
"""
from pathlib import Path


def generate(repo_path: str, folder: str = "Projects") -> None:
    """Generate wiki pages from graphify's graph.json into the vault."""
    repo = Path(repo_path)
    graph_json = repo / "graphify-out" / "graph.json"
    out_dir = f"vault/{folder}/{repo.name}/"
    print(f"Wiki     : [stub] {graph_json} → {out_dir} — not yet implemented")
