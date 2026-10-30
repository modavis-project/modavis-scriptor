# Read-only preflight for a user-selected Windows/WSL2 Docker development host.
$ErrorActionPreference = 'Stop'
$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$OK, [string]$Detail) {
  $checks.Add([pscustomobject]@{ check = $Name; ok = $OK; detail = $Detail })
}
if ($env:OS -ne 'Windows_NT') { throw 'Run this preflight on the Windows host. Native Linux/macOS validation has a separate workflow.' }
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
  $kernel = (& wsl.exe --exec uname -r 2>&1 | Out-String).Trim()
  Add-Check 'WSL2 default distribution' ($LASTEXITCODE -eq 0 -and $kernel -match '(?i)microsoft.*WSL2') $kernel
} else { Add-Check 'WSL2 default distribution' $false 'Install WSL2 and a Linux distribution first.' }
if (Get-Command docker -ErrorAction SilentlyContinue) {
  $engine = (& docker info --format '{{.OSType}}' 2>&1 | Out-String).Trim()
  Add-Check 'Linux Docker engine' ($LASTEXITCODE -eq 0 -and $engine -eq 'linux') $engine
  $compose = (& docker compose version --short 2>&1 | Out-String).Trim()
  Add-Check 'Docker Compose' ($LASTEXITCODE -eq 0) $compose
  Push-Location (Join-Path $PSScriptRoot '../..')
  try {
    $configuration = (& docker compose config --quiet 2>&1 | Out-String).Trim()
    Add-Check 'Compose configuration' ($LASTEXITCODE -eq 0) $(if ($configuration) { $configuration } else { 'Validated' })
  } finally { Pop-Location }
} else { Add-Check 'Linux Docker engine' $false 'Start Docker Desktop with WSL2 integration enabled.' }
$ok = @($checks | Where-Object { -not $_.ok }).Count -eq 0
[pscustomobject]@{
  ok = $ok
  checks = $checks
  next = 'From a checkout inside the WSL Linux filesystem, use Node from .nvmrc and run npm run test:integration. Preflight alone is not an executed WSL integration test.'
} | ConvertTo-Json -Depth 5
if (-not $ok) { exit 1 }
