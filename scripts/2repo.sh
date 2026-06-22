#!/usr/bin/env bash
# 2repo — generate a knowledge graph for any codebase using graphify
#
# Usage:
#   2repo .                              # graph for the current directory
#   2repo ~/Work/my-repo                 # graph for a specific repo
#   2repo . --update                     # incremental update (changed files only)
#   2repo . --wiki                       # also generate LLM wiki in vault/Projects/
#   2repo . --wiki -f Reference          # wiki in vault/Reference/
#   2repo . --check                      # check if graph may be stale
#   2repo . --install-hook               # install stale-warning post-commit hook
#   2repo . --preset smart               # override AI preset
#
# Register globally:
#   alias 2repo="$HOME/knowledge-hub/scripts/2repo.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env so CONTAINER_ENGINE and other host-level vars are available.
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

ENGINE="${CONTAINER_ENGINE:-docker}"

# Scan args: find the first argument that is a real directory — that's the repo.
# Replace it with /target-repo in the container args list. All other args pass through.
REPO_PATH=""
declare -a ARGS=()

for arg in "$@"; do
    if [[ -z "$REPO_PATH" && -d "$arg" ]]; then
        REPO_PATH="$(realpath "$arg")"
        ARGS+=("/target-repo")
    else
        ARGS+=("$arg")
    fi
done

if [[ -z "$REPO_PATH" ]]; then
    echo "ERROR: provide a path to the target repository (or '.' for current directory)" >&2
    echo "Usage: 2repo . [--update] [--wiki] [--check] [--install-hook] [--preset NAME]" >&2
    exit 1
fi

if [[ ! -d "$REPO_PATH" ]]; then
    echo "ERROR: not a directory: $REPO_PATH" >&2
    exit 1
fi

"$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
    -v "${REPO_PATH}:/target-repo:rw" \
    scripts \
    python -u /scripts/repo.py "${ARGS[@]}"
