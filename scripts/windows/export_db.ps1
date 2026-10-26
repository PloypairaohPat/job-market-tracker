# Exports the laptop's Postgres database to one dump file, to move it to the
# server. See docs/deploy.md, "Cut-over".
#
#   .\scripts\windows\export_db.ps1
#   .\scripts\windows\export_db.ps1 -OutDir D:\exports
#
# What it does:
#   1. pg_dump -Fc -f <file> INSIDE the compose db container, so Postgres
#      writes the file itself and no binary data passes through PowerShell
#   2. docker compose cp copies the file out to -OutDir
#      (default: <your home folder>\jobmarket-export, outside the repo)
#   3. prints the file's size and SHA256, and the row counts to compare with
#      deploy/import_db.sh on the server
#
# Never save a dump with ">" in PowerShell: it re-encodes the bytes as text
# and the file can no longer be restored.
#
# Keep this file ASCII only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.

param(
    [string]$OutDir = (Join-Path $HOME "jobmarket-export"),
    [string]$Database = "jobmarket"
)

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if ($Database -notmatch '^[a-z0-9_]+$') {
    Fail "invalid database name: $Database"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -Path $repoRoot

docker compose exec -T db pg_isready -U postgres -d $Database | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "the db container isn't running. Start it with: docker compose up -d"
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'")
$name = "${Database}_$stamp.dump"
$tmp = "/tmp/$name"

Write-Host "Dumping $Database inside the db container ..."
docker compose exec -T db pg_dump -U postgres -Fc -f $tmp $Database
if ($LASTEXITCODE -ne 0) {
    Fail "pg_dump failed (exit code $LASTEXITCODE)"
}

New-Item -ItemType Directory -Force -Path $OutDir -ErrorAction Stop | Out-Null
$outFile = Join-Path (Resolve-Path $OutDir).Path $name
docker compose cp "db:$tmp" $outFile
$copyExit = $LASTEXITCODE
docker compose exec -T db rm -f $tmp | Out-Null
if ($copyExit -ne 0 -or -not (Test-Path $outFile)) {
    Fail "docker compose cp failed (exit code $copyExit)"
}

$sizeMb = [math]::Round((Get-Item $outFile).Length / 1MB, 1)
$hash = (Get-FileHash -Algorithm SHA256 -Path $outFile).Hash.ToLower()
Write-Host ""
Write-Host "Wrote  : $outFile ($sizeMb MB)"
Write-Host "SHA256 : $hash"

Write-Host ""
Write-Host "Row counts in $Database (compare with deploy/import_db.sh on the server):"
Get-Content -Raw -Path (Join-Path $repoRoot "deploy\row_counts.sql") |
    docker compose exec -T db psql -U postgres -d $Database -v ON_ERROR_STOP=1 -tA
if ($LASTEXITCODE -ne 0) {
    Fail "the row-count query failed (exit code $LASTEXITCODE)"
}

Write-Host ""
Write-Host "Next (docs/deploy.md, Cut-over):"
Write-Host "  scp `"$outFile`" deploy@<server>:~/"
Write-Host "  on the server:"
Write-Host "    sha256sum ~/$name                      # must match the SHA256 above"
Write-Host "    cd ~/job-market-tracker && deploy/import_db.sh ~/$name"
Write-Host "The dump holds your whole database: delete both copies once the import checks out."
