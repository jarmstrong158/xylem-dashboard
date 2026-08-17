# The unattended half of the phone workbench.
#
# You rule on a proposal from your phone; that records an INTENT in the Worker's
# KV and nothing more. This is what notices and makes it real, so the loop
# closes without you being at the desk.
#
#   .\tools\watch_queue.ps1            drain, and republish only if something changed
#   .\tools\watch_queue.ps1 -DryRun    show what a drain would do, write nothing
#
# Polling, not push, on purpose: the phone cannot reach this machine, and you
# wanted it to work from your desk at work. A poll needs no inbound access, no
# port forward and no tunnel, and does not care which network the phone is on.
#
# Republish is CONDITIONAL. publish.ps1 is wrangler deploy plus a 15s gate
# verification -- about 45 seconds -- and on a five-minute timer the queue is
# empty almost every time. apply_queue.py exits 10 when it actually applied
# something, and that is the only thing that triggers a deploy.

param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$log  = Join-Path $env:USERPROFILE ".xylem\watch-queue.log"
$lock = Join-Path $env:USERPROFILE ".xylem\watch-queue.lock"

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log($msg) {
  $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Add-Content -Path $log -Value $line -Encoding utf8
  Write-Host $line
}

# A drain that overruns its interval must not start a second copy on top of
# itself: two processes superseding the same entry is not idempotent, and the
# second would back up a store the first had already rewritten -- destroying the
# very snapshot that made the first one recoverable.
if (Test-Path $lock) {
  $age = (Get-Date) - (Get-Item $lock).LastWriteTime
  if ($age.TotalMinutes -lt 30) { Log "skip: a drain has been running for $([int]$age.TotalMinutes)m"; exit 0 }
  Log "clearing a stale lock ($([int]$age.TotalMinutes)m old)"
}
New-Item -ItemType File -Path $lock -Force | Out-Null

# Both steps use exit 10 for "I changed something worth publishing". Returns
# that code so the caller can decide ONCE, after both have run, rather than
# deploying twice in a tick that both applied a link and wrote a verdict.
function Run-Step($script, $banner) {
  # Not $args -- that is an automatic variable in PowerShell and assigning to it
  # is a quiet way to get an argument list that is not the one you wrote.
  $pyArgs = @($script)
  if ($DryRun) { $pyArgs += "--dry-run" }

  Push-Location $root
  $out = & python @pyArgs 2>&1
  $code = $LASTEXITCODE
  Pop-Location

  if ($code -eq 10) {
    Log $banner
    $out | ForEach-Object { Log "  $_" }
  } elseif ($code -ne 0) {
    Log "$script error (exit $code):"
    $out | ForEach-Object { Log "  $_" }
  } elseif ($out -notmatch "queue is empty|no eval requests pending") {
    Log ($out -join " | ")   # otherwise stay quiet; most ticks do nothing
  }
  return $code
}

try {
  # Every step reachable from this timer is LOCAL and FREE: read the queue,
  # write to a store on disk, deploy static assets. Nothing here may call a
  # billed API.
  #
  # An automated audit step used to live here and was deleted, not disabled.
  # It made a metered model call per request on a five-minute timer, which is a
  # standing charge dressed up as a feature. Sending a pair "for eval" still
  # files a request; the reading happens in an interactive session that is
  # already paid for. Do not reintroduce a paid call on this path.
  $drain = Run-Step "tools\apply_queue.py" "APPLIED:"

  if ($drain -eq 10 -and -not $DryRun) {
    Log "republishing so the phone reflects it..."
    Push-Location $root
    $pub = & powershell -NoProfile -ExecutionPolicy Bypass -File "$root\publish.ps1" 2>&1
    $pubCode = $LASTEXITCODE
    Pop-Location
    if ($pubCode -ne 0) {
      # The gate check inside publish.ps1 is the entire security model. If it
      # fails the deploy is suspect, and that must be loud rather than a line
      # in a log nobody opens.
      Log "PUBLISH FAILED (exit $pubCode) -- the dashboard may be stale or the gate may be broken:"
      $pub | ForEach-Object { Log "  $_" }
    } else {
      Log "published."
    }
  }
} catch {
  Log "watch_queue failed: $($_.Exception.Message)"
} finally {
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
