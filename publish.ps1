# One command: refresh the data, assemble the publishable bundle, deploy it.
#
#   .\publish.ps1
#
# Everything technical about this setup lives here so using it does not require
# remembering any of it. Run it whenever you want the phone to see new data.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$cambium = "C:\Users\jarms\repos\cambium"

# The projects whose memory is included. Explicit: a store travels because it is
# named here, never because nothing excluded it.
$map = @{}
Get-ChildItem C:\Users\jarms\repos -Directory |
  Where-Object { Test-Path (Join-Path $_.FullName '.context\decisions.json') } |
  ForEach-Object { $map[$_.Name] = $_.FullName }

$env:CAMBIUM_PROJECTS       = ($map | ConvertTo-Json -Compress)
$env:CAMBIUM_REPO           = $cambium
$env:CAMBIUM_AGENT_ID       = "jonny-desktop"
$env:CAMBIUM_ORG_REPO       = "C:\Users\jarms\repos\knowledge"
$env:CAMBIUM_CONTEXT_KEEPER = "C:\Users\jarms\repos\context-keeper\server.py"

Write-Host "1/3  refreshing snapshot ($($map.Count) projects)..." -ForegroundColor Cyan
Push-Location $cambium
python cambium_server.py export-snapshot --out "$root\snapshot.json" --bodies | Out-Null
Pop-Location

Write-Host "2/3  assembling dist/ (allowlist; vault excluded)..." -ForegroundColor Cyan
python "$root\tools\build_dist.py"
if ($LASTEXITCODE -ne 0) { throw "build_dist failed" }

Write-Host "3/3  deploying to Cloudflare..." -ForegroundColor Cyan
Push-Location "$root\worker"
npx --yes wrangler deploy
Pop-Location

# Never announce success without checking. The gate is the entire security model
# here, and the first deploy of this Worker served the snapshot to the open
# internet because static assets are returned BEFORE the Worker unless
# run_worker_first is set. A deploy that silently loses that setting must fail
# loudly, not quietly go public.
Write-Host ""
Write-Host "verifying the gate..." -ForegroundColor Cyan
Start-Sleep -Seconds 15
# Read from disk, not hard-coded: this repo is public. The token is what gates
# the data and has never been committed, but shipping the address too means an
# attacker needs one secret instead of two.
$baseFile = "$env:USERPROFILE\.xylem-dashboard-base"
if (-not (Test-Path $baseFile)) {
  throw "no Worker origin configured. Write it to $baseFile (one line, https://...workers.dev)"
}
$base = (Get-Content $baseFile -Raw).Trim().TrimEnd('/')
$tok  = (Get-Content "$env:USERPROFILE\.xylem-dashboard-token" -Raw).Trim()
$bad = 0
foreach ($p in @("snapshot.json", "app.js", "")) {
  try { Invoke-WebRequest -Uri "$base/$p" -TimeoutSec 25 -UseBasicParsing -MaximumRedirection 0 | Out-Null
        Write-Host "  EXPOSED without token: /$p" -ForegroundColor Red; $bad++ }
  catch { if ($_.Exception.Response.StatusCode.value__ -ne 404) { Write-Host "  unexpected: /$p" -ForegroundColor Yellow } }
}
try { $r = Invoke-WebRequest -Uri "$base/$tok/snapshot.json" -TimeoutSec 25 -UseBasicParsing
      if ($r.StatusCode -ne 200) { $bad++ } }
catch { Write-Host "  token path is NOT serving - the dashboard is down" -ForegroundColor Red; $bad++ }

if ($bad) { throw "GATE CHECK FAILED - see above. Fix before using this URL." }
Write-Host "gate verified: nothing served without the token." -ForegroundColor Green
Write-Host ""
Write-Host "Done. The phone will see the new data on next open." -ForegroundColor Green
