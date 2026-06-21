#!/usr/bin/env bash
# 2brain — create structured Obsidian notes via AI (runs entirely in Docker, no host Python required)
# Usage:  2brain "topic" [-f Folder] [--title "Title"]
#         2brain --from-file ./notes.md [-f Folder]
# Register globally: alias 2brain="$HOME/knowledge-hub/scripts/2brain.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env so host-level settings (CONTAINER_ENGINE, etc.) are available here.
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

# Which container runtime to use. Set CONTAINER_ENGINE=podman in .env to switch.
ENGINE="${CONTAINER_ENGINE:-docker}"

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

"$ENGINE" compose -f "$ROOT/docker-compose.yml" run --rm \
    "${EXTRA_VOLUMES[@]}" \
    scripts \
    python -u /scripts/main.py "${ARGS[@]}"
