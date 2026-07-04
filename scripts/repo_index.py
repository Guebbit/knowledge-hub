from __future__ import annotations

"""
Semantic index for 2repo artifacts.

Builds a lightweight TF-IDF vector index from graphify-out artifacts and durable
repo memory, then serves cosine-similarity retrieval for `2repo --query`.
"""

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import repo_memory

_INDEX_SUBPATH = Path("graphify-out/repo-index.json")
_REQUIRED_ARTIFACTS = (
    Path("graphify-out/GRAPH_REPORT.md"),
    Path("graphify-out/EXECUTION.md"),
    Path("graphify-out/REPO_MEMORY.md"),
)
_SKIP_INDEX_PATHS = {
    "graphify-out/.2repo-state.json",
    "graphify-out/repo-index.json",
    "graphify-out/repo-memory.json",
    "graphify-out/wiki/.wiki-cache.json",
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
_MAX_CHUNK_CHARS = 1200
_QUERY_EXPANSION_TERMS = 8
_QUERY_EXPANSION_WEIGHT = 0.35
_BASE_SCORE_WEIGHT = 0.65
_EXPANDED_SCORE_WEIGHT = 0.35
_EXPANSION_SEED_TERMS_PER_CHUNK = 25


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


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
    """Split text into paragraph-like chunks bounded by max character size."""
    chunks: list[str] = []
    block: list[str] = []
    current_len = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if block:
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
            chunks.append(candidate)
    return chunks


def _artifact_files(repo: Path) -> list[Path]:
    """Return indexable graphify-out artifact files, skipping generated index/state."""
    graphify_out = repo / "graphify-out"
    if not graphify_out.exists():
        return []

    files: list[Path] = []
    for path in sorted(graphify_out.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(repo))
        if rel in _SKIP_INDEX_PATHS:
            continue
        if path.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        files.append(path)
    return files


def _build_chunk_records(
    repo: Path,
    *,
    artifact_files: list[Path],
    runtime_metadata: dict[str, str],
) -> list[dict[str, str]]:
    """Create indexable chunk records from runtime metadata, artifacts, and memory."""
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
        text = _load_text(path)
        for idx, chunk_text in enumerate(_chunk_plain_text(text)):
            chunks.append(
                {
                    "id": f"artifact:{rel}:{idx}",
                    "kind": "artifact",
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
    return {token: math.log((1.0 + docs) / (1.0 + count)) + 1.0 for token, count in df.items()}


def _vectorize(tokens: list[str], idf: dict[str, float]) -> tuple[dict[str, float], float]:
    """Build a normalized TF-IDF-like sparse vector and its L2 norm."""
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
    return vector, norm


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
        raise ValueError("no indexable artifacts found in graphify-out")

    chunks = _build_chunk_records(repo, artifact_files=artifacts, runtime_metadata=runtime_metadata)
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

    artifact_digest = _artifact_digest(repo, artifacts)
    runtime_digest = _hash_text(json.dumps(runtime_metadata, sort_keys=True))
    memory_digest = repo_memory.memory_digest(repo_path)
    revision = _hash_text(f"{artifact_digest}:{runtime_digest}:{memory_digest}")

    payload = {
        "version": 1,
        "generated_at": _now_iso(),
        "revision": revision,
        "artifact_digest": artifact_digest,
        "runtime_digest": runtime_digest,
        "memory_digest": memory_digest,
        "memory_count": _memory_count(repo_path),
        "artifact_files": [str(path.relative_to(repo)) for path in artifacts],
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
        "artifact_count": len(artifacts),
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
    top_seed = scored[: min(len(scored), max(top_k * 2, 6))]

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
    return results[: max(1, top_k)]
