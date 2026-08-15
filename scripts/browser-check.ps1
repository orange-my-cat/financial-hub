# Run the browser check.
#
#     .\scripts\browser-check.ps1 -Password '<the app password>'
#
# Starts a throwaway Vite instance, drives it with Chromium in a container, and
# writes a screenshot per screen to scripts/screenshots/.
#
# ---------------------------------------------------------------------------
# Why a second Vite instance
# ---------------------------------------------------------------------------
# The everyday dev server binds to localhost, which is the posture ADR-16 chose
# and which this script does not disturb. A container cannot reach localhost on
# the host, so the check needs a server bound to 0.0.0.0 — and that is exactly
# what ADR-16 rejected for the application: an unencrypted HTTP service exposed
# to every device on the network.
#
# So the exposure is made deliberate, narrow and brief instead: a separate port,
# started for the run and stopped at the end, never `npm run dev`. Nothing about
# the development or production topology changes.
#
# Requires Docker. Node runs on the host; only Chromium runs in the container.

param(
    [Parameter(Mandatory = $true)][string]$Password,
    [string]$Username = 'ivan',
    [int]$Port = 5174
)

$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$screenshots = Join-Path $PSScriptRoot 'screenshots'
$image = 'mcr.microsoft.com/playwright:v1.55.0-noble'

# A shell started before Node was installed inherits the old PATH.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')

New-Item -ItemType Directory -Force -Path $screenshots | Out-Null

# Refuse to start on an occupied port rather than working around it.
#
# A previous run that leaked its server would otherwise answer the readiness
# probe below, and the check would silently exercise a stale build with stale
# configuration — which is exactly what happened the first time this script was
# written, and cost a wrong diagnosis.
$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
    $owner = Get-Process -Id $occupied[0].OwningProcess -ErrorAction SilentlyContinue
    throw ("Port $Port is already in use by pid $($occupied[0].OwningProcess) " +
           "($($owner.ProcessName), started $($owner.StartTime)). Stop it, or pass -Port.")
}

Write-Host "Starting the check server on 0.0.0.0:$Port ..."
# Tells vite.config.ts to accept the `host.docker.internal` Host header. Scoped
# to this process, so the everyday dev server is unaffected.
$env:VITE_CHECK = '1'
$vite = Start-Process -FilePath 'npm.cmd' `
    -ArgumentList 'run', 'dev:check', '--', '--port', $Port `
    -WorkingDirectory (Join-Path $root 'frontend') `
    -PassThru -WindowStyle Hidden

try {
    $ready = $false
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 3 | Out-Null
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) { throw "The check server did not start on port $Port." }

    Write-Host 'Driving Chromium ...'
    docker run --rm `
        --add-host=host.docker.internal:host-gateway `
        -v "${root}:/repo" `
        -v "${screenshots}:/work/screenshots" `
        -w /repo/scripts `
        -e BASE_URL="http://host.docker.internal:$Port" `
        -e USERNAME=$Username `
        -e PASSWORD=$Password `
        -e OUT_DIR=/work/screenshots `
        $image `
        sh -c 'set -e; mkdir -p /tmp/pw; cd /tmp/pw; npm install playwright@1.55.0 --no-audit --no-fund >/dev/null 2>&1; cp /repo/scripts/browser-check.mjs .; node browser-check.mjs'

    $checkExit = $LASTEXITCODE
} finally {
    # /T kills the tree. `npm.cmd` spawns node as a child, so stopping only the
    # process this script launched leaves the actual server running — and the
    # next run then talks to that orphan instead of to itself.
    if ($vite) {
        Write-Host 'Stopping the check server.'
        & taskkill /PID $vite.Id /T /F 2>&1 | Out-Null
    }
    # Belt and braces: whatever still holds the port goes too.
    $leftover = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $leftover) {
        & taskkill /PID $connection.OwningProcess /T /F 2>&1 | Out-Null
    }
}

Write-Host "Screenshots in $screenshots"
exit $checkExit
