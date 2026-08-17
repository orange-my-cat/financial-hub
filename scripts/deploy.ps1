# Build the image and (re)create `financial-hub` as a standalone container.
#
# Deliberately a standalone container rather than a compose stack, matching
# every other tenant of this platform. `vibe-city` is a Docker network and a
# naming theme, not a compose project: central-station, control-tower,
# data-center and data-center-test are each their own container and share
# nothing but the network. An application that arrived as a stack would be the
# odd one out in `docker ps`, in Portainer, and in the restart story.
#
# This script exists so the run arguments live in version control instead of
# only inside the Docker daemon. That is the whole job a compose file was doing
# here, and it is the same reason d:\Repositories\vibe-city\start.ps1 exists.
#
#     .\scripts\deploy.ps1              build, recreate, wait for healthy
#     .\scripts\deploy.ps1 -NoBuild     recreate from the image already built
#
# Recreating is safe. The container holds no state: the database is in
# data-center and the dumps are on a bind mount, both outside it.
#
# ASCII only, deliberately. Windows PowerShell 5.1 reads a .ps1 with no BOM as
# ANSI, which turns a UTF-8 em dash into a smart quote and breaks parsing.

[CmdletBinding()]
param(
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'

$repo    = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo '.env'
$image   = 'financial-hub:1.0.0'
$name    = 'financial-hub'

if (-not (Test-Path $envFile)) {
    throw "Missing $envFile - copy .env.example and fill in the production profile."
}

# ---------------------------------------------------------------------------
# Read the .env, and refuse to deploy the wrong profile
# ---------------------------------------------------------------------------
# Only uncommented assignments count. Both profiles live in this file with one
# of them commented out, so a regex that ignored the leading '#' would read the
# inactive block as well as the active one.

$settings = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        $settings[$Matches[1]] = $Matches[2].Trim()
    }
}

# P-04, enforced rather than trusted. `data-center` (production) and
# `data-center-test` (development) differ by one digit, and this container runs
# migrations against whatever it is pointed at. A .env left on the development
# profile would put a DEBUG-on production image on the development database,
# or - with the host's ports in play - somewhere worse.
if ($settings['DJANGO_SETTINGS_MODULE'] -ne 'config.settings.prod') {
    throw "DJANGO_SETTINGS_MODULE is '$($settings['DJANGO_SETTINGS_MODULE'])'. Switch .env to the production profile before deploying."
}
if ($settings['POSTGRES_HOST'] -ne 'data-center' -or $settings['POSTGRES_PORT'] -ne '5432') {
    throw "Production must reach data-center:5432 over the vibe-city network, not '$($settings['POSTGRES_HOST']):$($settings['POSTGRES_PORT'])'."
}
if ($settings['POSTGRES_DB'] -ne 'financial_hub') {
    throw "POSTGRES_DB is '$($settings['POSTGRES_DB'])', not 'financial_hub'. Refusing to migrate the wrong database."
}

$backupHostDir = $settings['BACKUP_HOST_DIR']
if (-not $backupHostDir) {
    throw "BACKUP_HOST_DIR is not set in .env. The dump is the only backstop against another tenant's teardown (P-02); it is not optional."
}
if (-not (Test-Path $backupHostDir)) {
    throw "BACKUP_HOST_DIR '$backupHostDir' does not exist. Create it before deploying - Docker would otherwise invent it, owned by no one."
}

# ---------------------------------------------------------------------------
# Platform preconditions
# ---------------------------------------------------------------------------
# The network predates this repository and is never created from here. Fail
# loudly rather than silently making a second one.

if (-not (docker network ls -q -f name='^vibe-city$')) {
    throw "Docker network 'vibe-city' does not exist. Create it deliberately, not from this script."
}

# data-center sits on the default bridge network, where Docker's embedded DNS
# does not resolve container names. Attaching it is non-destructive and needed
# once per machine, but it does not survive the container being recreated by
# whoever owns it - so it is checked on every deploy rather than assumed.
$attached = docker network inspect vibe-city --format '{{range .Containers}}{{.Name}} {{end}}'
if ($attached -notmatch '\bdata-center\b') {
    Write-Host "Attaching data-center to vibe-city (non-destructive; no downtime)."
    docker network connect vibe-city data-center
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

if (-not $NoBuild) {
    Write-Host "Building $image ..."
    docker build --file (Join-Path $repo 'docker\Dockerfile') --tag $image $repo
    if ($LASTEXITCODE -ne 0) { throw "docker build failed." }
}

# ---------------------------------------------------------------------------
# Recreate
# ---------------------------------------------------------------------------
# No -p, deliberately. The application is unreachable except through
# central-station at http://financial-hub.localhost, which is a stronger
# posture than ADR-10's 127.0.0.1:8000, not a weaker one (BUILD_PLAN 2.1).
#
# --mount rather than -v for the bind: the host path carries both a drive
# letter and a space - D:/Backups/Financial Hub - and -v is split on colons,
# so a drive letter is one ambiguity too many to leave to a parser.
#
# --env-file rather than compose's env_file has one welcome difference: the
# Docker CLI passes values through literally, with no variable interpolation,
# so a '$' inside a secret key survives instead of being read as an unset
# variable and blanked.

if (docker ps -aq -f name="^$name$") {
    Write-Host "Removing the existing container ..."
    docker rm -f $name | Out-Null
}

Write-Host "Starting $name ..."
docker run -d `
    --name $name `
    --restart unless-stopped `
    --network vibe-city `
    --env-file $envFile `
    --mount "type=bind,source=$backupHostDir,target=/backups" `
    --log-driver json-file `
    --log-opt max-size=10m `
    --log-opt max-file=3 `
    $image | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed." }

# ---------------------------------------------------------------------------
# Wait for the entrypoint to finish: dump -> prune -> migrate -> Gunicorn
# ---------------------------------------------------------------------------
# The healthcheck is baked into the image, so the daemon is already polling.
# A dump of a decade of data plus a long migration is the slow case; two
# minutes is generous for it and still bounded.

Write-Host -NoNewline "Waiting for the container to report healthy "
$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 3
    Write-Host -NoNewline '.'
    $state = docker inspect --format '{{.State.Health.Status}}' $name 2>$null
    if ($state -eq 'healthy') {
        Write-Host " healthy."
        Write-Host ""
        docker exec $name python manage.py smoke_test
        exit $LASTEXITCODE
    }
    $running = docker inspect --format '{{.State.Running}}' $name 2>$null
    if ($running -ne 'true') {
        Write-Host ""
        docker logs --tail 40 $name
        throw "Container stopped before becoming healthy. A failed dump or migration stops it deliberately - the log above says which."
    }
} while ((Get-Date) -lt $deadline)

Write-Host ""
docker logs --tail 40 $name
throw "Timed out waiting for health. The container is still running; the log above is the place to start."
