"""
Semantic index for 2brain artifacts.

Builds a lightweight TF-IDF vector index from <OUT_DIR> artifacts and durable
repo memory, then serves cosine-similarity retrieval for `2brain query`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from repo import llm_wiki as repo_llm_wiki
from repo import memory as repo_memory
from repo import scope as repo_scope
from shared import config
from shared.utils import now_iso

_OUT = Path(config.OUT_DIR)
_INDEX_SUBPATH = _OUT / "repo-index.json"
_REQUIRED_ARTIFACTS = (
    _OUT / "EXECUTION.md",
    _OUT / "REPO_MEMORY.md",
)
# Explicit allowlist for the semantic corpus. modules/ (the human-facing
# per-directory tier) is deliberately NOT here: it is written *from*
# llm-wiki/'s per-file pages (modules.py's read_pages()), so indexing both tiers
# means ~79% of the corpus is the same facts twice, which depresses IDF on
# exactly the terms that should discriminate a query. A new artifact tier
# must be added here explicitly rather than silently joining by virtue of
# living under OUT_DIR.
#
# GRAPH_REPORT.md is deliberately NOT here either, for the same reason in a
# worse form. It is a concatenation of every community label, identifier and
# truncated docstring fragment in the repository, so it overlaps the vocabulary
# of any question about the repo — maximum recall, near-zero precision. Each
# chunk is an index of names, not an explanation, so it ranks high and answers
# nothing: asked "how do I run the test suite" it returned a cluster label plus
# three docstrings cut mid-sentence, while EXECUTION.md — which contains the
# literal line `make test` — did not make the top ten. Its actual job is
# first-contact orientation, which REPO_CONTEXT.md routes to by telling a reader
# to open the file. That is a read-the-file job and is unaffected; the report is
# still generated, committed and linked, just not retrievable in fragments.
_ALLOWLISTED_ARTIFACT_FILES = (
    _OUT / "EXECUTION.md",
    _OUT / "REPO_MEMORY.md",
    _OUT / "REPO_CONTEXT.md",
)
_ALLOWLISTED_MD_DIRS = (
    _OUT / "llm-wiki",
    _OUT / "arch",
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
_MAX_CHUNK_CHARS = 1200
# Below this, a chunk is a fragment rather than an answer — a markdown heading,
# a one-line note — and scores on too few terms to be trusted. See
# _chunk_plain_text for why splitting on blank lines alone produces them.
_MIN_CHUNK_CHARS = 120
_QUERY_EXPANSION_TERMS = 8
_QUERY_EXPANSION_WEIGHT = 0.35
_BASE_SCORE_WEIGHT = 0.65
_EXPANDED_SCORE_WEIGHT = 0.35
_EXPANSION_SEED_TERMS_PER_CHUNK = 25
# A long artifact chunks into dozens of records that all answer to the same
# source. Without a cap one document can take most of the result set — and,
# worse, most of the expansion seed, which then injects its vocabulary into the
# query and makes it win the second round harder. GRAPH_REPORT.md (an index of
# every identifier in the repo, so it matches everything) took both of the top
# two slots on a query whose answer was in a source file it never mentions.
#
# One per source, not two: a caller asking a question wants to know which files
# to open, so a second excerpt of a page already listed spends a slot that
# could have named a different file. The best chunk still decides its rank.
_MAX_CHUNKS_PER_SOURCE = 1


def _index_file(repo: Path) -> Path:
    """Return index file path for a repository."""
    return repo / _INDEX_SUBPATH


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase terms with a light plural-normalization step."""
    tokens: list[str] = []
    for token in _TOKEN_PATTERN.findall(text.lower()):
        tokens.append(token)
        # Lightweight plural normalization for retrieval recall (not a full stemmer).
        if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            tokens.append(token[:-1])
    return tokens


def _hash_text(text: str) -> str:
    """Return SHA-256 hex digest for text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_text(path: Path) -> str:
    """Read UTF-8 text with replacement for invalid bytes."""
    return path.read_text(encoding="utf-8", errors="replace")


def _chunk_plain_text(text: str) -> list[str]:
    """Split text into paragraph-like chunks bounded by max character size.

    A blank line ends a chunk only once there is enough text to be an answer.
    Markdown puts a blank line after every heading, so splitting on blank lines
    alone turns each heading into its own chunk — and a four-token chunk that
    matches two query terms outscores a full paragraph that matches eight,
    because cosine similarity normalizes away the difference in substance. The
    query "how does the wiki cache decide to skip a page" was answered with
    "## What 2brain does". Carrying a short block forward instead attaches the
    heading to the section it introduces, which is where it belongs anyway.
    """
    chunks: list[str] = []
    block: list[str] = []
    current_len = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if block and current_len >= _MIN_CHUNK_CHARS:
                candidate = "\n".join(block).strip()
                if candidate:
                    chunks.append(candidate)
                block = []
                current_len = 0
            continue

        line_len = len(line)
        if current_len + line_len + 1 > _MAX_CHUNK_CHARS and block:
            candidate = "\n".join(block).strip()
            if candidate:
                chunks.append(candidate)
            block = [line]
            current_len = line_len
        else:
            block.append(line)
            current_len += line_len + 1

    if block:
        candidate = "\n".join(block).strip()
        if candidate:
            # A trailing scrap (a closing heading, a one-line footer) joins the
            # previous chunk rather than standing as a chunk of its own.
            if len(candidate) < _MIN_CHUNK_CHARS and chunks:
                chunks[-1] = f"{chunks[-1]}\n{candidate}"
            else:
                chunks.append(candidate)
    return chunks


def _artifact_files(repo: Path) -> list[Path]:
    """Return indexable <OUT_DIR> artifact files: an explicit allowlist.

    Only the top-level generated reports plus llm-wiki/ and arch/ (both
    per-file/per-topic docs) are indexed — see _ALLOWLISTED_MD_DIRS above for
    why modules/ is excluded. Everything else generated under OUT_DIR (raw
    graphify dumps, repo-index.json/repo-memory.json/.2brain-state.json) was
    never prose and is skipped by construction: it would have to be named in an
    allowlist entry to be indexed at all.
    """
    out_dir = repo / config.OUT_DIR
    if not out_dir.exists():
        return []

    files: list[Path] = [repo / rel for rel in _ALLOWLISTED_ARTIFACT_FILES if (repo / rel).is_file()]
    for rel_dir in _ALLOWLISTED_MD_DIRS:
        directory = repo / rel_dir
        if directory.is_dir():
            files.extend(
                p for p in sorted(directory.rglob("*.md")) if p.is_file() and not _is_stale_prose_page(repo, p)
            )
    return files


def _is_stale_prose_page(repo: Path, page: Path) -> bool:
    """True for a leftover llm-wiki page describing a file that is now indexed directly.

    llm_wiki no longer generates pages for prose and prunes the old ones, but
    pruning only happens on a wiki run — and the graph layer rebuilds the index
    before the wiki layer runs. Without this, that window indexes a document and
    its obsolete summary at the same time, which is the duplication the corpus
    allowlist exists to prevent. Page paths are source paths plus '.md', so the
    source is recoverable by stripping one suffix.
    """
    llm_wiki_root = repo / _OUT / "llm-wiki"
    if not page.is_relative_to(llm_wiki_root):
        return False
    source_rel = str(page.relative_to(llm_wiki_root).with_suffix(""))
    return repo_llm_wiki.is_prose(source_rel)


def _source_prose_files(repo: Path) -> list[Path]:
    """Return in-scope prose sources (README.md, docs/**.md, ...) to index directly.

    These have no generated page — llm_wiki skips them, because summarising
    prose produces something longer and less accurate than its input. They are
    indexed as themselves instead, which is both cheaper and more faithful, and
    makes `2brain query` return a path the caller can actually open rather than
    a `<path>.md` page they have to translate back.

    The candidate set comes from graph.json rather than a filesystem walk, so it
    inherits exactly the filtering llm_wiki uses — graphify's .gitignore and
    .graphifyignore handling, plus the scope file — instead of re-deriving it
    here and drifting. A missing graph yields an empty list: `2brain reindex`
    before any graph run then indexes artifacts only, rather than failing.
    """
    try:
        graph_files, adjacency = repo_llm_wiki.load_graph(str(repo))
    except FileNotFoundError:
        return []
    graph_files.update(adjacency)

    scope = repo_scope.load(str(repo))
    return [
        repo / rel
        for rel in sorted(graph_files)
        if repo_llm_wiki.is_prose(rel) and repo_llm_wiki.is_documentable(repo, rel, scope)
    ]


def _build_chunk_records(
    repo: Path,
    *,
    artifact_files: list[Path],
    prose_files: list[Path],
    runtime_metadata: dict[str, str],
) -> list[dict[str, str]]:
    """Create indexable chunks from runtime metadata, artifacts, prose sources and memory."""
    chunks: list[dict[str, str]] = []

    runtime_lines = [f"{k}: {v}" for k, v in sorted(runtime_metadata.items()) if v]
    if runtime_lines:
        runtime_text = "\n".join(runtime_lines)
        chunks.append(
            {
                "id": "runtime:0",
                "kind": "runtime",
                "source": "runtime-metadata",
                "text": runtime_text,
            }
        )

    for path in artifact_files:
        rel = str(path.relative_to(repo))
        fields, text = repo_llm_wiki.split_frontmatter(_load_text(path))
        # Two things fall out of splitting the header off an llm-wiki page.
        #
        # It stays out of the corpus: every page would otherwise contribute the
        # literal tokens "source", "sha256", "generated_at" and "model" — words
        # common enough to be worth querying, present in *every* page, so their
        # IDF collapses and a real question about the model layer ranks against
        # noise — plus one unique 64-character digest token apiece, which is
        # pure vocabulary growth.
        #
        # And the page can say what it documents. `source` is the file a caller
        # actually wants back from a query; the page path is that path plus
        # ".md", so returning the source loses nothing and saves the translation.
        # A page with no header (OVERVIEW.md, arch/, the top-level reports)
        # falls back to naming itself.
        documented = fields.get("source")
        for idx, chunk_text in enumerate(_chunk_plain_text(text)):
            chunks.append(
                {
                    "id": f"artifact:{rel}:{idx}",
                    "kind": "wiki" if documented else "artifact",
                    "source": documented or rel,
                    "text": chunk_text,
                }
            )

    for path in prose_files:
        rel = str(path.relative_to(repo))
        for idx, chunk_text in enumerate(_chunk_plain_text(_load_text(path))):
            chunks.append(
                {
                    # kind "source" rather than "artifact": this is the author's
                    # own file, not something 2brain generated, and `source` is a
                    # path the caller can open directly.
                    "id": f"source:{rel}:{idx}",
                    "kind": "source",
                    "source": rel,
                    "text": chunk_text,
                }
            )

    memory_entries = repo_memory.load_entries(str(repo))
    for idx, entry in enumerate(memory_entries):
        chunks.append(
            {
                "id": f"memory:{entry['id']}:{idx}",
                "kind": "memory",
                "source": f"repo-memory:{entry['id']}",
                "text": entry["text"],
            }
        )
    return chunks


def _compute_idf(chunk_token_sets: list[set[str]]) -> dict[str, float]:
    """Compute smoothed inverse document frequency weights for all seen tokens."""
    docs = len(chunk_token_sets)
    df: Counter[str] = Counter()
    for tokens in chunk_token_sets:
        df.update(tokens)
    # Inner (+1) terms smooth df/docs to avoid division-by-zero and undefined log values.
    # Outer (+1.0) keeps weights positive for ranking stability when terms are very common.
    return {
        token: round(math.log((1.0 + docs) / (1.0 + count)) + 1.0, _STORED_PRECISION)
        for token, count in df.items()
    }


_STORED_PRECISION = 6


def _vectorize(tokens: list[str], idf: dict[str, float]) -> tuple[dict[str, float], float]:
    """Build a normalized TF-IDF-like sparse vector and its L2 norm.

    Weights are rounded before returning: json.dumps writes Python floats at full
    double precision (~17 significant digits), which does nothing for cosine-
    similarity ranking but roughly doubles the serialized size of every vector —
    multiplied by 18k+ chunks, that's several extra megabytes of digits no query
    ever needs.
    """
    tf = Counter(tokens)
    if not tf:
        return {}, 0.0
    max_tf = max(tf.values())
    vector: dict[str, float] = {}
    for token, count in tf.items():
        weight = (count / max_tf) * idf.get(token, 0.0)
        if weight > 0:
            vector[token] = weight
    norm = math.sqrt(sum(value * value for value in vector.values()))
    vector = {token: round(weight, _STORED_PRECISION) for token, weight in vector.items()}
    return vector, round(norm, _STORED_PRECISION)


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    """Compute sparse dot product between two vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(token, 0.0) for token, weight in a.items())


def _cosine(q_vector: dict[str, float], q_norm: float, d_vector: dict[str, float], d_norm: float) -> float:
    """Return cosine similarity between two normalized sparse vectors."""
    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0
    return _dot(q_vector, d_vector) / (q_norm * d_norm)


def _artifact_digest(repo: Path, files: list[Path]) -> str:
    """Hash artifact paths and bytes to detect content changes."""
    hasher = hashlib.sha256()
    for path in files:
        rel = str(path.relative_to(repo))
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _memory_count(repo_path: str) -> int:
    """Return number of durable repository memory entries."""
    return len(repo_memory.load_entries(repo_path))


def build_index(repo_path: str, *, runtime_metadata: dict[str, str]) -> dict[str, str | int]:
    """Build and persist repo-index.json, returning summary metadata."""
    repo = Path(repo_path)
    for rel in _REQUIRED_ARTIFACTS:
        if not (repo / rel).exists():
            raise FileNotFoundError(f"required artifact missing: {repo / rel}")

    artifacts = _artifact_files(repo)
    if not artifacts:
        raise ValueError(f"no indexable artifacts found in {config.OUT_DIR}/")

    prose = _source_prose_files(repo)
    chunks = _build_chunk_records(
        repo,
        artifact_files=artifacts,
        prose_files=prose,
        runtime_metadata=runtime_metadata,
    )
    if not chunks:
        raise ValueError("no index chunks were produced")

    tokenized = [_tokenize(chunk["text"]) for chunk in chunks]
    token_sets = [set(tokens) for tokens in tokenized]
    idf = _compute_idf(token_sets)

    index_chunks: list[dict[str, object]] = []
    for chunk, tokens in zip(chunks, tokenized, strict=True):
        vector, norm = _vectorize(tokens, idf)
        if not vector:
            continue
        index_chunks.append(
            {
                "id": chunk["id"],
                "kind": chunk["kind"],
                "source": chunk["source"],
                "text": chunk["text"],
                "vector": vector,
                "norm": norm,
            }
        )

    if not index_chunks:
        raise ValueError("all chunks were empty after tokenization")

    # Prose sources are hashed alongside the artifacts: they are part of the
    # corpus now, so editing a README must move the index revision.
    artifact_digest = _artifact_digest(repo, artifacts + prose)
    runtime_digest = _hash_text(json.dumps(runtime_metadata, sort_keys=True))
    memory_digest = repo_memory.memory_digest(repo_path)
    revision = _hash_text(f"{artifact_digest}:{runtime_digest}:{memory_digest}")

    payload = {
        "version": 1,
        "generated_at": now_iso(),
        "revision": revision,
        "artifact_digest": artifact_digest,
        "runtime_digest": runtime_digest,
        "memory_digest": memory_digest,
        "memory_count": _memory_count(repo_path),
        "artifact_files": [str(path.relative_to(repo)) for path in artifacts + prose],
        "runtime_metadata": runtime_metadata,
        "idf": idf,
        "chunks": index_chunks,
    }

    output = _index_file(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return {
        "revision": revision,
        "chunk_count": len(index_chunks),
        "artifact_count": len(artifacts) + len(prose),
        "memory_count": payload["memory_count"],
        "index_path": str(output),
        "artifact_digest": artifact_digest,
        "memory_digest": memory_digest,
    }


def load_index(repo_path: str) -> dict[str, object]:
    """Load and validate the on-disk semantic index payload."""
    path = _index_file(Path(repo_path))
    if not path.exists():
        raise FileNotFoundError(f"index not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid index file: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid index structure: {path}")
    return data


def _cap_per_source(
    items: list[dict[str, object]],
    *,
    limit: int,
    source_of: Callable[[dict[str, object]], str] = lambda item: str(item.get("source") or ""),
) -> list[dict[str, object]]:
    """Take the best `limit` items, at most _MAX_CHUNKS_PER_SOURCE from each source.

    `items` must already be sorted best-first, since the first chunk kept for a
    source is the one that fixes its rank. Returns fewer than `limit` when the
    candidates do not hold that many distinct sources — deliberately: padding
    the tail with more chunks of a source already listed is the behaviour this
    exists to prevent.
    """
    seen: Counter[str] = Counter()
    kept: list[dict[str, object]] = []
    for item in items:
        source = source_of(item)
        if seen[source] >= _MAX_CHUNKS_PER_SOURCE:
            continue
        seen[source] += 1
        kept.append(item)
        if len(kept) >= limit:
            break
    return kept


def semantic_query(repo_path: str, *, text: str, top_k: int = 5) -> list[dict[str, object]]:
    """Run semantic retrieval against the index and return top ranked chunks."""
    query_text = text.strip()
    if not query_text:
        raise ValueError("query text cannot be empty or contain only whitespace")

    data = load_index(repo_path)
    idf = data.get("idf")
    chunks = data.get("chunks")
    if not isinstance(idf, dict) or not isinstance(chunks, list):
        raise ValueError("index missing idf/chunks")

    query_tokens = _tokenize(query_text)
    q_vector, q_norm = _vectorize(query_tokens, idf)
    if not q_vector:
        return []

    scored: list[dict[str, object]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        vector = chunk.get("vector")
        norm = chunk.get("norm")
        if not isinstance(vector, dict) or not isinstance(norm, (float, int)):
            continue
        base_score = _cosine(q_vector, q_norm, vector, float(norm))
        if base_score <= 0.0:
            continue
        scored.append({"chunk": chunk, "base_score": base_score})

    if not scored:
        return []

    scored.sort(key=lambda item: float(item["base_score"]), reverse=True)
    top_seed = _cap_per_source(
        scored,
        limit=min(len(scored), max(top_k * 2, 6)),
        source_of=lambda item: str(item["chunk"].get("source") or ""),
    )

    expansion: Counter[str] = Counter()
    query_set = set(query_tokens)
    for item in top_seed:
        chunk = item["chunk"]
        vector = chunk["vector"]
        ranked_terms = sorted(vector.items(), key=lambda kv: kv[1], reverse=True)
        for token, weight in ranked_terms[:_EXPANSION_SEED_TERMS_PER_CHUNK]:
            if token in query_set:
                continue
            expansion[token] += float(weight)

    expanded_q = dict(q_vector)
    for token, score in expansion.most_common(_QUERY_EXPANSION_TERMS):
        expanded_q[token] = expanded_q.get(token, 0.0) + score * _QUERY_EXPANSION_WEIGHT
    expanded_norm = math.sqrt(sum(value * value for value in expanded_q.values()))

    results: list[dict[str, object]] = []
    for item in scored:
        chunk = item["chunk"]
        vector = chunk["vector"]
        norm = float(chunk["norm"])
        base_score = float(item["base_score"])
        expanded_score = _cosine(expanded_q, expanded_norm, vector, norm)
        final_score = (_BASE_SCORE_WEIGHT * base_score) + (_EXPANDED_SCORE_WEIGHT * expanded_score)
        results.append(
            {
                "score": round(final_score, 6),
                "base_score": round(base_score, 6),
                "kind": chunk.get("kind"),
                "source": chunk.get("source"),
                "text": chunk.get("text"),
            }
        )

    results.sort(key=lambda item: float(item["score"]), reverse=True)
    return _cap_per_source(results, limit=max(1, top_k))
