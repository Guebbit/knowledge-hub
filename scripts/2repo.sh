#!/usr/bin/env bash
# 2repo — repository intelligence for any codebase, one subcommand per category
#
# Usage:
#   2repo .                              # full run (same as: 2repo graph .)
#   2repo graph .                        # graph pipeline for the current directory
#   2repo graph ~/Work/my-repo           # graph pipeline for a specific repo
#   2repo graph . --update               # incremental update (changed files only)
#   2repo graph . --preset smart         # override AI preset
#   2repo graph . --ai-target copilot    # generate only Copilot integration files
#   2repo check .                        # check if graph may be stale
#   2repo hook .                         # install stale-warning post-commit hook
#   2repo query . "how do I run tests?"
#   2repo remember . "Use make test" --kind runbook
#   2repo reindex .
#   2repo wiki .                         # incremental LLM wiki (changed files + graph neighbors)
#   2repo wiki . src/auth.ts src/db.ts   # target specific files (+ graph neighbors)
#   2repo wiki . --force-all             # full wiki rebuild
#   2repo wiki . --dry-run               # preview which pages would regenerate
#   2repo wiki . --mirror-vault          # also copy wiki pages into the Obsidian vault
#
# Legacy flag syntax (2repo . --wiki, --check, --query, ...) still works but is deprecated.
#
# Register globally:
#   alias 2repo="$HOME/knowledge-hub/scripts/2repo.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env so CONTAINER_ENGINE and other host-level vars are available.
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

ENGINE="${CONTAINER_ENGINE:-docker}"

COMMANDS=" graph check hook reindex query remember wiki "

# Scan args: find the first argument that is a real directory — that's the repo.
# Replace it with /target-repo in the container args list. All other args pass through.
# A leading subcommand name is never treated as the repo path, even if a directory
# with the same name exists in the current working directory.
REPO_PATH=""
declare -a ARGS=()

INDEX=0
for arg in "$@"; do
    if [[ $INDEX -eq 0 && "$COMMANDS" == *" $arg "* ]]; then
        ARGS+=("$arg")
    elif [[ -z "$REPO_PATH" && -d "$arg" ]]; then
        REPO_PATH="$(realpath "$arg")"
        ARGS+=("/target-repo")
    else
        ARGS+=("$arg")
    fi
    INDEX=$((INDEX + 1))
done

if [[ -z "$REPO_PATH" ]]; then
    echo "ERROR: provide a path to the target repository (or '.' for current directory)" >&2
    echo "Usage: 2repo [<command>] <repo> [options]   (command defaults to 'graph' when omitted)" >&2
    echo "Commands: graph (default), check, hook, reindex, query, remember, wiki" >&2
    echo "Example: 2repo wiki . --dry-run" >&2
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
