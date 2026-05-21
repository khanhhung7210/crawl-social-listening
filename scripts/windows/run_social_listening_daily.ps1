param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "python",
    [string]$PowerShellPath = "powershell.exe",
    [string]$LogRoot = "",
    [switch]$StartChrome = $false,
    [string]$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
if (-not $LogRoot) {
    $LogRoot = Join-Path $RepoRoot "logs\windows-runs"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLogDir = Join-Path $LogRoot $timestamp
$lockDir = Join-Path $LogRoot ".locks"
$lockFile = Join-Path $lockDir "daily_runner.lock"
$pipelineScript = Join-Path $RepoRoot "scripts\windows\run_platform_pipeline.ps1"

New-Item -ItemType Directory -Path $runLogDir -Force | Out-Null
New-Item -ItemType Directory -Path $lockDir -Force | Out-Null

if (Test-Path $lockFile) {
    Write-Error "A daily social listening run is already in progress: $lockFile"
    exit 1
}

Set-Content -Path $lockFile -Value "$PID"

$env:THREADS_DEBUGGER_ADDRESS = "127.0.0.1:9222"
$env:TIKTOK_DEBUGGER_ADDRESS = "127.0.0.1:9223"
$env:INSTAGRAM_DEBUGGER_ADDRESS = "127.0.0.1:9224"
$env:YOUTUBE_DEBUGGER_ADDRESS = "127.0.0.1:9225"
$env:FACEBOOK_DEBUGGER_ADDRESS = "127.0.0.1:9226"
$env:GRABFOOD_REMOTE_DEBUGGING_PORT = "9229"

function Start-DebugChrome {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$ProfileName
    )

    if (-not (Test-Path $ChromePath)) {
        throw "Chrome not found at $ChromePath"
    }

    $profileDir = Join-Path $RepoRoot "runtime\chrome\$ProfileName"
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null

    Start-Process -FilePath $ChromePath -ArgumentList @(
        "--remote-debugging-port=$Port",
        "--user-data-dir=$profileDir"
    ) | Out-Null
}

try {
    if ($StartChrome) {
        Start-DebugChrome -Port 9222 -ProfileName "threads"
        Start-DebugChrome -Port 9223 -ProfileName "tiktok"
        Start-DebugChrome -Port 9224 -ProfileName "instagram"
        Start-DebugChrome -Port 9225 -ProfileName "youtube"
        Start-DebugChrome -Port 9226 -ProfileName "facebook"
        Start-Sleep -Seconds 10
    }

    $platforms = @("threads", "tiktok", "youtube", "instagram", "facebook")
    $jobs = @()

    foreach ($platform in $platforms) {
        $job = Start-Process `
            -FilePath $PowerShellPath `
            -ArgumentList @(
                "-ExecutionPolicy", "Bypass",
                "-File", $pipelineScript,
                "-Platform", $platform,
                "-RepoRoot", $RepoRoot,
                "-PythonPath", $PythonPath,
                "-LogDir", $runLogDir
            ) `
            -PassThru `
            -WindowStyle Hidden
        $jobs += [PSCustomObject]@{
            Platform = $platform
            Process = $job
        }
    }

    $exitCode = 0
    foreach ($job in $jobs) {
        $job.Process.WaitForExit()
        if ($job.Process.ExitCode -ne 0) {
            Write-Error "Platform failed: $($job.Platform) (exit=$($job.Process.ExitCode))"
            $exitCode = 1
        }
        else {
            Write-Host "Platform completed: $($job.Platform)"
        }
    }

    if ($exitCode -ne 0) {
        exit $exitCode
    }

    Write-Host "Daily social listening run completed. Logs: $runLogDir"
    exit 0
}
finally {
    Remove-Item -Path $lockFile -Force -ErrorAction SilentlyContinue
}
