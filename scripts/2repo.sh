#!/usr/bin/env bash
# 2repo — repository intelligence for any codebase, one subcommand per category
#
# Usage:
#   2repo .                              # every layer: graph + wiki + arch (same as: 2repo all .)
#   2repo all . --force-all              # every layer, rebuilt from scratch
#   2repo graph .                        # graph layer only, for the current directory
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
#   2repo wiki . --no-mirror-vault       # skip the vault mirror (on by default when a vault exists)
#   2repo . --exclude '**/*.test.ts'     # set the documented scope (persists to <repo>/.2repoignore)
#   2repo . --include 'src/**,api/**'    # document only these paths
#   2repo . --rescope                    # re-ask the include/exclude prompt
#   2repo arch .                         # architecture layer: component pages + Mermaid diagrams (CodeBoarding)
#   2repo arch . --force-all             # full re-analysis (ignore CodeBoarding incremental baseline)
#   2repo arch . --dry-run               # report full-vs-incremental without calling the LLM
#
# A bare `2repo <repo>` runs all three layers in order. Its graph step is
# incremental whenever graphify output already exists, so re-running is cheap;
# --force-all rebuilds every layer from scratch.
#
# The module tier (one note per directory) and the arch pages are mirrored into
# vault/Projects/<repo-name>/Generated/ automatically whenever a vault is found at
# VAULT_PATH. Per-file wiki pages are machine-tier and stay in the repo. Set
# REPO_MIRROR_VAULT=0 in .env, or pass --no-mirror-vault, to turn mirroring off.
#
# On the first run per repository, 2repo asks which paths to document and saves the
# answer to <repo>/.2repoignore (gitignore-style patterns, hand-editable).
#
# Register globally:
#   alias 2repo="$HOME/knowledge-hub/scripts/2repo.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── --version / -v ──────────────────────────────────────────────────────────────
for arg in "$@"; do
    if [[ "$arg" == "--version" || "$arg" == "-v" ]]; then
        VERSION="$(grep -m1 '^version' "$ROOT/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
        echo "knowledge-hub $VERSION"
        exit 0
    fi
done
# ────────────────────────────────────────────────────────────────────────────────

# Load .env so CONTAINER_ENGINE and other host-level vars are available.
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

ENGINE="${CONTAINER_ENGINE:-docker}"

COMMANDS=" all graph check hook reindex query remember wiki arch "

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

# No directory argument given (e.g. bare '2repo' or '2repo wiki --dry-run') —
# default to the current directory, same as explicitly passing '.'.
if [[ -z "$REPO_PATH" ]]; then
    REPO_PATH="$(realpath .)"
fi

if [[ ! -d "$REPO_PATH" ]]; then
    echo "ERROR: not a directory: $REPO_PATH" >&2
    exit 1
fi

"$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
    -v "${REPO_PATH}:/target-repo:rw" \
    scripts \
    python -u /scripts/repo.py "${ARGS[@]}"
