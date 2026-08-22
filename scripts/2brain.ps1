#!/usr/bin/env pwsh
# 2brain.ps1 - Windows/PowerShell wrapper for 2brain (create structured Obsidian
# notes via AI). Mirrors scripts/2brain.sh but targets docker-compose.windows.yml.
#
# Backend is preset-driven via .env (DEFAULT_PRESET / PRESET_*). On this machine
# only cloud presets work (no local GPU), so DEFAULT_PRESET=deep needs OPENAI_API_KEY.
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   .\scripts\2brain.ps1 "topic"
#   .\scripts\2brain.ps1 "topic" -f Guides --title "My Title"
#   .\scripts\2brain.ps1 --from-file .\notes.md -f Reference
#   .\scripts\2brain.ps1 "topic" --preset deep
#
# Optional: add to your PowerShell $PROFILE so `2brain` works anywhere:
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

# Remap --from-file paths to container paths, exactly like 2brain.sh:
#   files under vault/ or scripts/ are already mounted; anything else gets an
#   extra read-only /input bind-mount.
$extraVolumes = @()
$outArgs      = @()

$i = 0
while ($i -lt $args.Count) {
    $a = $args[$i]
    if ($a -eq '--from-file' -and $i + 1 -lt $args.Count) {
        $hostFileArg = $args[$i + 1]
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
