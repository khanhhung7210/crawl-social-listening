param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("threads", "tiktok", "youtube", "instagram", "facebook", "google_maps")]
    [string]$Platform,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [string]$PythonPath = "python",

    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    Write-Host "[$Platform] running $Command"
    Push-Location $RepoRoot
    try {
        & $PythonPath $Command
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code $LASTEXITCODE: $Command"
        }
    }
    finally {
        Pop-Location
    }
}

$stepsByPlatform = @{
    "threads" = @(
        "scripts/mkt/crawl/threads/threads_crawl_runner.py",
        "scripts/mkt/crawl/threads/threads_search_filter_job.py",
        "scripts/mkt/crawl/threads/threads_replies_runner.py",
        "scripts/mkt/crawl/threads/threads_format_job.py",
        "scripts/mkt/crawl/threads/threads_keyword_filter_job.py"
    )
    "tiktok" = @(
        "scripts/mkt/crawl/tiktok/tiktok_search_runner.py",
        "scripts/mkt/crawl/tiktok/tiktok_search_filter_job.py",
        "scripts/mkt/crawl/tiktok/tiktok_video_runner.py",
        "scripts/mkt/crawl/tiktok/tiktok_format_job.py",
        "scripts/mkt/crawl/tiktok/tiktok_keyword_filter_job.py"
    )
    "youtube" = @(
        "scripts/mkt/crawl/youtube/youtube_search_runner.py",
        "scripts/mkt/crawl/youtube/youtube_search_filter_job.py",
        "scripts/mkt/crawl/youtube/youtube_video_runner.py",
        "scripts/mkt/crawl/youtube/youtube_format_job.py",
        "scripts/mkt/crawl/youtube/youtube_keyword_filter_job.py"
    )
    "instagram" = @(
        "scripts/mkt/crawl/instagram/instagram_search_runner.py",
        "scripts/mkt/crawl/instagram/instagram_post_runner.py",
        "scripts/mkt/crawl/instagram/instagram_format_job.py",
        "scripts/mkt/crawl/instagram/instagram_keyword_filter_job.py"
    )
    "facebook" = @(
        "scripts/mkt/crawl/facebook/facebook_raw_runner.py",
        "scripts/mkt/crawl/facebook/facebook_keyword_filter_job.py",
        "scripts/mkt/crawl/facebook/facebook_format_job.py"
    )
    "google_maps" = @(
        "scripts/mkt/crawl/reviews/google_maps/google_maps_search_runner.py",
        "scripts/mkt/crawl/reviews/google_maps/google_maps_review_runner.py",
        "scripts/mkt/crawl/reviews/google_maps/google_maps_format_job.py",
        "scripts/mkt/crawl/reviews/google_maps/google_maps_keyword_filter_job.py"
    )
}

if (-not $stepsByPlatform.ContainsKey($Platform)) {
    throw "Unsupported platform: $Platform"
}

if ($LogDir) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logFile = Join-Path $LogDir "$Platform-$timestamp.log"
    Start-Transcript -Path $logFile -Append | Out-Null
}

try {
    foreach ($step in $stepsByPlatform[$Platform]) {
        Invoke-Step -Command $step
    }
    Write-Host "[$Platform] completed successfully"
    exit 0
}
catch {
    Write-Error "[$Platform] failed: $_"
    exit 1
}
finally {
    if ($LogDir) {
        Stop-Transcript | Out-Null
    }
}
