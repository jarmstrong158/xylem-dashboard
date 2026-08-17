@echo off
REM Conductor entry point. Conductor runs a task_path directly (worker "Job
REM Rankings Email" runs a .bat the same way), and a .bat shim avoids depending
REM on the execution policy it happens to launch PowerShell with.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch_queue.ps1"
