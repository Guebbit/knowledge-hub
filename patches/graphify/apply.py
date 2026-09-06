"""Apply 2repo's build-time patch to the pinned graphifyy package.

Run by Dockerfile.scripts with the scripts image's own interpreter right after
`pip install graphifyy==0.9.13`:

    python /opt/graphify-patches/apply.py

Same exact-text-replacement contract as patches/codeboarding/apply.py: fails
loudly if a future graphifyy release moves the anchor, and is a no-op on an
already-patched tree.

Patch (graphifyy 0.9.13):

dedup.py — stop dropping same-ID nodes extracted from different source files.

`deduplicate_entities()`'s pre-dedup step keeps the first node seen for a
given ID and silently discards any later node that shares the ID but has a
different `source_file`, printing a WARNING that recommends re-running
`graphify extract` per subfolder and merging with `graphify merge-graphs` to
avoid the "data loss".

That workaround is wrong for a single-repo pipeline: graphify's cross-file
edge detection only sees files within one `extract` invocation, so splitting
extraction per subfolder would silently drop every edge between files in
different subfolders — a much bigger loss than the handful of duplicate node
records this warning is actually about. See vault/Guides/graphify.md.

In every case observed here, the collision is two independent extractions of
the *same real entity* (e.g. a semantic node for a path mentioned in
README.md, and the AST/manifest node for that same file) landing on the same
normalized ID — collapsing them to one node is the correct outcome, not data
loss. Edges already reference the shared ID string regardless of which node
dict survives, so dropping the duplicate never removes an edge. The only
thing actually discarded is a few metadata fields (source_location,
source_url, captured_at, author, contributor) that might differ between the
two extractions. This patch carries those fields forward into the surviving
node when the survivor is missing them, and replaces the per-collision
WARNING (which recommends the harmful workaround) with a single summary note.
"""

from __future__ import annotations

import importlib
import py_compile
import sys
from pathlib import Path

_MARKER = "2repo patch"

_OLD = (
    "    # Pre-deduplicate: keep first occurrence of each id.\n"
    "    # Warn when two nodes share an ID but originate from different source files —\n"
    "    # this indicates a cross-chunk ID collision (#1504) where silent data loss occurs.\n"
    "    seen_ids: dict[str, dict] = {}\n"
    "    for node in nodes:\n"
    "        nid = node.get(\"id\", \"\")\n"
    "        if not nid:\n"
    "            continue\n"
    "        if nid not in seen_ids:\n"
    "            seen_ids[nid] = node\n"
    "        else:\n"
    "            existing_sf = seen_ids[nid].get(\"source_file\") or \"\"\n"
    "            new_sf = node.get(\"source_file\") or \"\"\n"
    "            if existing_sf != new_sf:\n"
    "                print(\n"
    "                    f\"[graphify] WARNING: node '{nid}' from '{new_sf}' collides with \"\n"
    "                    f\"node from '{existing_sf}' — the second node will be dropped. \"\n"
    "                    f\"This is a cross-chunk ID collision caused by two files with the \"\n"
    "                    f\"same name in different directories. To avoid data loss, run \"\n"
    "                    f\"'graphify extract' per subfolder and merge with \"\n"
    "                    f\"'graphify merge-graphs'.\",\n"
    "                    file=sys.stderr,\n"
    "                )\n"
    "    unique_nodes = list(seen_ids.values())\n"
)

_NEW = (
    "    # Pre-deduplicate: keep first occurrence of each id.\n"
    "    # 2repo patch (patches/graphify/apply.py): two nodes sharing an ID but\n"
    "    # different source files means the same real entity was independently\n"
    "    # extracted twice (e.g. a doc mentioning a path, and the file itself) —\n"
    "    # collapsing them to one node is correct. Edges already reference the\n"
    "    # shared id regardless of which node dict survives, so nothing but a few\n"
    "    # metadata fields is actually at risk; carry those forward instead of\n"
    "    # discarding them, and stop recommending a per-subfolder-extract\n"
    "    # workaround that would drop every cross-subfolder edge in the graph.\n"
    "    _carry_fields = (\"source_location\", \"source_url\", \"captured_at\", \"author\", \"contributor\")\n"
    "    seen_ids: dict[str, dict] = {}\n"
    "    _collision_count = 0\n"
    "    for node in nodes:\n"
    "        nid = node.get(\"id\", \"\")\n"
    "        if not nid:\n"
    "            continue\n"
    "        if nid not in seen_ids:\n"
    "            seen_ids[nid] = node\n"
    "        else:\n"
    "            existing = seen_ids[nid]\n"
    "            existing_sf = existing.get(\"source_file\") or \"\"\n"
    "            new_sf = node.get(\"source_file\") or \"\"\n"
    "            if existing_sf != new_sf:\n"
    "                _collision_count += 1\n"
    "                for _field in _carry_fields:\n"
    "                    if not existing.get(_field) and node.get(_field):\n"
    "                        existing[_field] = node[_field]\n"
    "    if _collision_count:\n"
    "        print(\n"
    "            f\"[graphify] note: collapsed {_collision_count} same-ID node(s) extracted \"\n"
    "            f\"from different source files into one entity (2repo dedup patch).\",\n"
    "            file=sys.stderr,\n"
    "        )\n"
    "    unique_nodes = list(seen_ids.values())\n"
)


def _site_packages() -> Path:
    graphify = importlib.import_module("graphify")
    return Path(graphify.__file__).resolve().parent.parent


def _patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if _MARKER in text:
        print(f"already patched: {path}")
        return
    count = text.count(_OLD)
    if count != 1:
        sys.exit(
            f"PATCH FAILED: anchor found {count} time(s) instead of once in {path}.\n"
            f"graphifyy changed; update patches/graphify/apply.py.\n--- anchor ---\n{_OLD}"
        )
    text = text.replace(_OLD, _NEW)
    if _MARKER not in text:
        sys.exit(f"PATCH FAILED: marker {_MARKER!r} missing after patching {path}")
    path.write_text(text, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    print(f"patched: {path}")


def main() -> None:
    site = _site_packages()
    _patch(site / "graphify" / "dedup.py")
    print("graphify patch applied")


if __name__ == "__main__":
    main()
