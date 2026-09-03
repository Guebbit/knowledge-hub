#!/usr/bin/env pwsh
# 2brain.ps1 - Windows/PowerShell wrapper for 2brain (CPU / cloud, no GPU): quick
# Obsidian notes and repository intelligence.
#
# Mirrors scripts/2brain.sh but targets docker-compose.windows.yml. Everything is
# preset-driven via .env (PRESET_* / REPO_PRESET_*); pass --preset NAME to override.
#
# ── First-time setup (run once, from the repo root) ──────────────────────────
#   docker compose -f docker-compose.windows.yml build scripts
#   # Only needed for local ollama presets (fast / local):
#   docker compose -f docker-compose.windows.yml up -d ollama
#   docker compose -f docker-compose.windows.yml exec ollama ollama pull qwen2.5:3b
#
# ── Usage: note mode (writes a structured Obsidian note) ─────────────────────
#   .\scripts\2brain.ps1 -q "topic"
#   .\scripts\2brain.ps1 -q "topic" -f Guides --title "My Title"
#   .\scripts\2brain.ps1 -q --from-file .\notes.md -f Reference
#   .\scripts\2brain.ps1 -q "topic" --preset deep
#
# ── Usage: repo mode (one subcommand per category) ────────────────────────────
#   .\scripts\2brain.ps1 graph  C:\path\to\repo
#   .\scripts\2brain.ps1 graph  C:\path\to\repo --preset deep     # cloud (needs OPENAI_API_KEY)
#   .\scripts\2brain.ps1 graph  C:\path\to\repo --ai-target copilot
#   .\scripts\2brain.ps1 wiki   C:\path\to\repo
#   .\scripts\2brain.ps1 arch   C:\path\to\repo                    # architecture pages + Mermaid diagrams
#   .\scripts\2brain.ps1 query  C:\path\to\repo "how do I run tests?"
#   .\scripts\2brain.ps1 all    C:\path\to\repo                    # every layer: graph + wiki + arch
#   .\scripts\2brain.ps1        C:\path\to\repo                    # shorthand for `all`
#
# -q / --quick is recognised only as the first argument — that's what switches
# into note mode. Anything else goes to repo mode, where a bare `2brain <repo>`
# runs all three layers in order. Its graph step is incremental whenever
# graphify output already exists, so re-running is cheap; --force-all rebuilds
# every layer from scratch.
#
# Wiki and arch pages are mirrored into vault/Projects/<repo-name>/Generated/
# automatically whenever a vault is found at VAULT_PATH. Set REPO_MIRROR_VAULT=0
# in .env, or pass --no-mirror-vault, to turn that off.
#
# Optional: add a shell function to your PowerShell $PROFILE so `2brain` works anywhere:
#   function 2brain { & "$HOME\Documents\knowledge-hub\scripts\2brain.ps1" @args }

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir
$Compose   = Join-Path $Root 'docker-compose.windows.yml'

# ── --version / -v ──────────────────────────────────────────────────────────────
if ($args -contains '--version' -or $args -contains '-v') {
    $pyproject = Join-Path $Root 'pyproject.toml'
    $match     = (Select-String -Path $pyproject -Pattern '^\s*version\s*=\s*"(.+?)"' | Select-Object -First 1).Matches[0].Groups[1].Value
    Write-Host "knowledge-hub $match"
    exit 0
}
# ────────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path -LiteralPath $Compose)) {
    Write-Error "compose file not found: $Compose"
    exit 1
}

# ── -q / --quick : note mode ────────────────────────────────────────────────────
# Recognised only as the first argument, so a note topic or query string
# containing "-q" is never misread as a mode switch.
if ($args.Count -gt 0 -and ($args[0] -eq '-q' -or $args[0] -eq '--quick')) {
    $noteArgs = $args[1..($args.Count - 1)]

    # Remap --from-file paths to container paths, exactly like 2brain.sh:
    #   files under vault/ or scripts/ are already mounted; anything else gets an
    #   extra read-only /input bind-mount.
    $extraVolumes = @()
    $outArgs      = @()

    $i = 0
    while ($i -lt $noteArgs.Count) {
        $a = $noteArgs[$i]
        if ($a -eq '--from-file' -and $i + 1 -lt $noteArgs.Count) {
            $hostFileArg = $noteArgs[$i + 1]
            if (-not (Test-Path -LiteralPath $hostFileArg -PathType Leaf)) {
                Write-Error "file not found: $hostFileArg"
                exit 1
            }
            $hostFile = (Resolve-Path -LiteralPath $hostFileArg).Path
            $vaultRoot   = (Join-Path $Root 'vault')
            $scriptsRoot = (Join-Path $Root 'scripts')

            if ($hostFile.StartsWith($vaultRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                $rel = $hostFile.Substring($vaultRoot.Length).TrimStart('\', '/').Replace('\', '/')
                $containerPath = "/vault/$rel"
            }
            elseif ($hostFile.StartsWith($scriptsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                $rel = $hostFile.Substring($scriptsRoot.Length).TrimStart('\', '/').Replace('\', '/')
                $containerPath = "/scripts/$rel"
            }
            else {
                $hostDir  = Split-Path -Parent $hostFile
                $fileBase = Split-Path -Leaf $hostFile
                $extraVolumes += @('-v', "${hostDir}:/input:ro")
                $containerPath = "/input/$fileBase"
            }
            $outArgs += @('--from-file', $containerPath)
            $i += 2
        }
        else {
            $outArgs += $a
            $i++
        }
    }

    # --no-deps: don't auto-start ollama (cloud preset in use on this machine).
    & docker compose -f $Compose run --rm --no-deps `
        @extraVolumes `
        scripts `
        python -u /scripts/main.py @outArgs

    exit $LASTEXITCODE
}
# ────────────────────────────────────────────────────────────────────────────────

$commands = @('all', 'graph', 'check', 'hook', 'reindex', 'query', 'remember', 'wiki', 'arch')

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

# No directory argument (e.g. bare `2brain` or `2brain wiki --dry-run`) -> current dir.
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
