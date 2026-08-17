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

try {
  Push-Location $root
  # Not $args -- that is an automatic variable in PowerShell and assigning to it
  # is a quiet way to get an argument list that is not the one you wrote.
  $pyArgs = @("tools\apply_queue.py")
  if ($DryRun) { $pyArgs += "--dry-run" }

  $out = & python @pyArgs 2>&1
  $code = $LASTEXITCODE
  Pop-Location

  switch ($code) {
    0  { if ($out -notmatch "queue is empty") { Log ($out -join " | ") } }   # quiet when idle
    10 {
      Log "APPLIED:"
      $out | ForEach-Object { Log "  $_" }
      if ($DryRun) { break }
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
    default {
      Log "drain error (exit $code):"
      $out | ForEach-Object { Log "  $_" }
    }
  }
} catch {
  Log "watch_queue failed: $($_.Exception.Message)"
} finally {
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
