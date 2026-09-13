#!/usr/bin/env bash
# 2brain — second-brain CLI: quick Obsidian notes and repository intelligence
#
# Note mode (writes a structured Obsidian note):
#   2brain -q "topic"                    # generate a note from a topic string
#   2brain -q "topic" -f Folder --title "Title"
#   2brain -q --from-file ./notes.md -f Reference
#   2brain --quick "topic" --preset deep
#
# Repo mode (one subcommand per category):
#   2brain .                             # every layer: graph + wiki + arch (same as: 2brain all .)
#   2brain all . --force-all             # every layer, rebuilt from scratch
#   2brain graph .                       # graph layer only, for the current directory
#   2brain graph ~/Work/my-repo          # graph pipeline for a specific repo
#   2brain graph . --update              # incremental update (changed files only)
#   2brain graph . --preset smart        # override AI preset
#   2brain graph . --ai-target copilot   # generate only Copilot integration files
#   2brain check .                       # check if graph may be stale
#   2brain hook .                        # install stale-warning post-commit hook
#   2brain query . "how do I run tests?"
#   2brain remember . "Use make test" --kind runbook
#   2brain reindex .
#   2brain wiki .                        # incremental LLM wiki (changed files + graph neighbors)
#   2brain wiki . src/auth.ts src/db.ts  # target specific files (+ graph neighbors)
#   2brain wiki . --force-all            # full wiki rebuild
#   2brain wiki . --dry-run              # preview which pages would regenerate
#   2brain wiki . --no-mirror-vault      # skip the vault mirror (on by default when a vault exists)
#   2brain . --exclude '**/*.test.ts'    # set the documented scope (persists to <repo>/.2brainignore)
#   2brain . --include 'src/**,api/**'   # document only these paths
#   2brain . --rescope                   # re-ask the include/exclude prompt
#   2brain arch .                        # architecture layer: component pages + Mermaid diagrams (CodeBoarding)
#   2brain arch . --force-all            # full re-analysis (ignore CodeBoarding incremental baseline)
#   2brain arch . --dry-run              # report full-vs-incremental without calling the LLM
#
# -q / --quick is recognised only as the first argument — that's what switches
# into note mode. Anything else goes to repo mode, where a bare `2brain <repo>`
# runs all three layers in order. Its graph step is incremental whenever
# graphify output already exists, so re-running is cheap; --force-all rebuilds
# every layer from scratch.
#
# `query` and `check` are pure-stdlib local reads (no graphify, no LLM, no
# network), so by default they run directly on the host instead of paying for
# a container + GPU model server start to do a 50ms dot product or a git diff.
# Every other subcommand still runs in the container, exactly as before.
# Force either way with REPO_MODE=host|container (env, default: auto) or
# --host / --container on the command line. The chosen mode is always printed.
#
# The module tier (one note per directory) and the arch pages are mirrored into
# vault/Projects/<repo-name>/Generated/ automatically whenever a vault is found at
# VAULT_PATH. Per-file wiki pages are machine-tier and stay in the repo. Set
# REPO_MIRROR_VAULT=0 in .env, or pass --no-mirror-vault, to turn mirroring off.
#
# On the first run per repository, 2brain asks which paths to document and saves the
# answer to <repo>/.2brainignore (gitignore-style patterns, hand-editable).
#
# Register globally:
#   alias 2brain="$HOME/knowledge-hub/scripts/2brain.sh"
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

# ── -q / --quick : note mode ────────────────────────────────────────────────────
# Recognised only as the first argument, so a note topic or query string
# containing "-q" is never misread as a mode switch.
if [[ "${1:-}" == "-q" || "${1:-}" == "--quick" ]]; then
    shift

    # Remap --from-file paths to container paths.
    # Files under vault/ or scripts/ are already mounted; anything else gets a /input bind-mount.
    declare -a EXTRA_VOLUMES=()
    declare -a ARGS=()

    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--from-file" && $# -gt 1 ]]; then
            HOST_FILE="$(realpath "$2")"
            if [[ ! -f "$HOST_FILE" ]]; then
                echo "ERROR: file not found: $2" >&2
                exit 1
            fi
            if [[ "$HOST_FILE" == "$ROOT/vault/"* ]]; then
                CONTAINER_PATH="/vault/${HOST_FILE#"$ROOT/vault/"}"
            elif [[ "$HOST_FILE" == "$ROOT/scripts/"* ]]; then
                CONTAINER_PATH="/scripts/${HOST_FILE#"$ROOT/scripts/"}"
            else
                HOST_DIR="$(dirname "$HOST_FILE")"
                FILE_BASE="$(basename "$HOST_FILE")"
                EXTRA_VOLUMES+=(-v "${HOST_DIR}:/input:ro")
                CONTAINER_PATH="/input/${FILE_BASE}"
            fi
            ARGS+=("--from-file" "$CONTAINER_PATH")
            shift 2
        else
            ARGS+=("$1")
            shift
        fi
    done

    exec "$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
        "${EXTRA_VOLUMES[@]}" \
        scripts \
        python -u /scripts/main.py "${ARGS[@]}"
fi
# ────────────────────────────────────────────────────────────────────────────────

COMMANDS=" all graph check hook reindex query remember wiki arch "

# Commands that are pure-stdlib local reads: no graphify, no CodeBoarding, no
# LLM, no network — everything else needs the container.
LOCAL_SAFE=" query check "

# --host / --container force the mode for this invocation; strip them out
# before the arg scan below so they never get passed through to repo.py.
FORCE_MODE=""
declare -a FILTERED=()
for arg in "$@"; do
    case "$arg" in
        --host) FORCE_MODE="host" ;;
        --container) FORCE_MODE="container" ;;
        *) FILTERED+=("$arg") ;;
    esac
done
set -- "${FILTERED[@]}"

# Scan args: find the first argument that is a real directory — that's the repo.
# Its slot in ARGS is a placeholder, resolved once the mode (host vs container)
# is known below. All other args pass through. A leading subcommand name is
# never treated as the repo path, even if a directory with the same name
# exists in the current working directory.
REPO_PATH=""
SUBCOMMAND=""
declare -a ARGS=()

INDEX=0
for arg in "$@"; do
    if [[ $INDEX -eq 0 && "$COMMANDS" == *" $arg "* ]]; then
        ARGS+=("$arg")
        SUBCOMMAND="$arg"
    elif [[ -z "$REPO_PATH" && -d "$arg" ]]; then
        REPO_PATH="$(realpath "$arg")"
        ARGS+=("__REPO_PATH__")
    else
        ARGS+=("$arg")
    fi
    INDEX=$((INDEX + 1))
done

# No directory argument given (e.g. bare '2brain' or '2brain wiki --dry-run') —
# default to the current directory, same as explicitly passing '.'.
if [[ -z "$REPO_PATH" ]]; then
    REPO_PATH="$(realpath .)"
fi
# No recognised subcommand at position 0 (e.g. bare '2brain <repo>') means the
# implicit full pipeline — never local-safe, so this only affects the message.
SUBCOMMAND="${SUBCOMMAND:-all}"

if [[ ! -d "$REPO_PATH" ]]; then
    echo "ERROR: not a directory: $REPO_PATH" >&2
    exit 1
fi

# Preferred host interpreter, in order; the first one that can actually import
# the `repo` package wins. Never autodetected the other way (container never
# falls back to host) — the allowlist above is the only source of truth for
# which commands are eligible.
_host_python() {
    local candidate
    for candidate in "$ROOT/.venv/bin/python" python3; do
        if { [[ -x "$candidate" ]] || command -v "$candidate" >/dev/null 2>&1; } \
            && PYTHONPATH="$ROOT/scripts" "$candidate" -c "import repo" >/dev/null 2>&1; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

MODE="${FORCE_MODE:-${REPO_MODE:-auto}}"
if [[ "$MODE" != "auto" && "$MODE" != "host" && "$MODE" != "container" ]]; then
    echo "ERROR: invalid mode '$MODE' (expected: auto, host, container)" >&2
    exit 1
fi
if [[ "$MODE" == "auto" ]]; then
    if [[ "$LOCAL_SAFE" == *" $SUBCOMMAND "* ]]; then
        MODE="host"
    else
        MODE="container"
    fi
fi

if [[ "$MODE" == "host" ]]; then
    if HOST_PY="$(_host_python)"; then
        echo "mode: host (${SUBCOMMAND} is local-safe)"
        RESOLVED_ARGS=("${ARGS[@]/__REPO_PATH__/$REPO_PATH}")
        exec env PYTHONPATH="$ROOT/scripts" "$HOST_PY" -u "$ROOT/scripts/repo.py" "${RESOLVED_ARGS[@]}"
    fi
    echo "mode: container (no usable host interpreter found — falling back)"
    MODE="container"
else
    echo "mode: container"
fi

RESOLVED_ARGS=("${ARGS[@]/__REPO_PATH__//target-repo}")
"$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
    -v "${REPO_PATH}:/target-repo:rw" \
    scripts \
    python -u /scripts/repo.py "${RESOLVED_ARGS[@]}"
