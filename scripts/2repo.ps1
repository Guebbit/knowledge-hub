#!/usr/bin/env pwsh
# 2repo.ps1 - Windows/PowerShell wrapper for 2repo (CPU / cloud, no GPU).
#
# Mirrors scripts/2repo.sh but targets docker-compose.windows.yml. Everything is
# preset-driven via .env (PRESET_* / REPO_PRESET_*); pass --preset NAME to override.
#
# ── First-time setup (run once, from the repo root) ──────────────────────────
#   docker compose -f docker-compose.windows.yml build scripts
#   # Only needed for local ollama presets (fast / local):
#   docker compose -f docker-compose.windows.yml up -d ollama
#   docker compose -f docker-compose.windows.yml exec ollama ollama pull qwen2.5:3b
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   .\scripts\2repo.ps1 graph  C:\path\to\repo
#   .\scripts\2repo.ps1 graph  C:\path\to\repo --preset deep     # cloud (needs OPENAI_API_KEY)
#   .\scripts\2repo.ps1 graph  C:\path\to\repo --ai-target copilot
#   .\scripts\2repo.ps1 wiki   C:\path\to\repo
#   .\scripts\2repo.ps1 query  C:\path\to\repo "how do I run tests?"
#   .\scripts\2repo.ps1        C:\path\to\repo                    # shorthand for `graph`
#
# Optional: add a shell function to your PowerShell $PROFILE so `2repo` works anywhere:
#   function 2repo { & "$HOME\Documents\knowledge-hub\scripts\2repo.ps1" @args }

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir
$Compose   = Join-Path $Root 'docker-compose.windows.yml'

if (-not (Test-Path -LiteralPath $Compose)) {
    Write-Error "compose file not found: $Compose"
    exit 1
}

$commands = @('graph', 'check', 'hook', 'reindex', 'query', 'remember', 'wiki')

# Scan args: the first argument that is a real directory is the target repo; it is
# replaced with /target-repo (the in-container mount point). A leading subcommand
# name is never treated as the repo path. All other args pass through unchanged.
$repoPath = $null
$outArgs  = @()
$index    = 0
foreach ($arg in $args) {
    if ($index -eq 0 -and $commands -contains $arg) {
        $outArgs += $arg
    }
    elseif (-not $repoPath -and (Test-Path -LiteralPath $arg -PathType Container)) {
        $repoPath = (Resolve-Path -LiteralPath $arg).Path
        $outArgs += '/target-repo'
    }
    else {
        $outArgs += $arg
    }
    $index++
}

# No directory argument (e.g. bare `2repo` or `2repo wiki --dry-run`) -> current dir.
if (-not $repoPath) {
    $repoPath = (Resolve-Path -LiteralPath '.').Path
}
if (-not (Test-Path -LiteralPath $repoPath -PathType Container)) {
    Write-Error "not a directory: $repoPath"
    exit 1
}

# --no-deps: do NOT auto-start the ollama service. This machine uses a cloud preset
# (no local inference), so the scripts container talks straight to the cloud API.
# If you ever switch to a local ollama preset, start it first:
#   docker compose -f docker-compose.windows.yml up -d ollama
#
# docker compose run resolves the host path; Docker Desktop maps Windows paths itself.
& docker compose -f $Compose run --rm --no-deps `
    -v "${repoPath}:/target-repo:rw" `
    scripts `
    python -u /scripts/repo.py @outArgs

exit $LASTEXITCODE
