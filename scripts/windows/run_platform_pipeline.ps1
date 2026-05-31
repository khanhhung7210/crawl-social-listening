param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("threads", "tiktok", "youtube", "instagram", "facebook", "google_maps", "shopeefood", "grabfood", "grabfood_web")]
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
        "scripts/threads/threads_crawl_runner.py",
        "scripts/threads/threads_search_filter_job.py",
        "scripts/threads/threads_replies_runner.py",
        "scripts/threads/threads_format_job.py",
        "scripts/threads/threads_keyword_filter_job.py",
        "scripts/threads/threads_mongodb_sync.py"
    )
    "tiktok" = @(
        "scripts/tiktok/tiktok_search_runner.py",
        "scripts/tiktok/tiktok_search_filter_job.py",
        "scripts/tiktok/tiktok_video_runner.py",
        "scripts/tiktok/tiktok_format_job.py",
        "scripts/tiktok/tiktok_keyword_filter_job.py",
        "scripts/tiktok/tiktok_mongodb_sync.py"
    )
    "youtube" = @(
        "scripts/youtube/youtube_search_runner.py",
        "scripts/youtube/youtube_search_filter_job.py",
        "scripts/youtube/youtube_video_runner.py",
        "scripts/youtube/youtube_format_job.py",
        "scripts/youtube/youtube_keyword_filter_job.py",
        "scripts/youtube/youtube_mongodb_sync.py"
    )
    "instagram" = @(
        "scripts/instagram/instagram_search_runner.py",
        "scripts/instagram/instagram_post_runner.py",
        "scripts/instagram/instagram_format_job.py",
        "scripts/instagram/instagram_keyword_filter_job.py",
        "scripts/instagram/instagram_mongodb_sync.py"
    )
    "facebook" = @(
        "scripts/facebook/facebook_raw_runner.py",
        "scripts/facebook/facebook_keyword_filter_job.py",
        "scripts/facebook/facebook_format_job.py",
        "scripts/facebook/facebook_mongodb_sync.py"
    )
    "google_maps" = @(
        "scripts/google_maps/google_maps_search_runner.py",
        "scripts/google_maps/google_maps_review_runner.py",
        "scripts/google_maps/google_maps_format_job.py",
        "scripts/google_maps/google_maps_keyword_filter_job.py",
        "scripts/google_maps/google_maps_mongodb_sync.py"
    )
    "shopeefood" = @(
        "scripts/shopeefood/shopeefood_simulator_full_runner.py",
        "scripts/shopeefood/shopeefood_format_job.py",
        "scripts/shopeefood/shopeefood_keyword_filter_job.py",
        "scripts/shopeefood/shopeefood_mongodb_sync.py"
    )
    "grabfood" = @(
        "scripts/grabfood/grabfood_app_explore_reviews.py"
    )
    "grabfood_web" = @(
        "scripts/grabfood/grabfood_search_runner.py",
        "scripts/grabfood/grabfood_search_filter.py",
        "scripts/grabfood/grabfood_detail_runner.py",
        "scripts/grabfood/grabfood_format_job.py",
        "scripts/grabfood/grabfood_keyword_filter_job.py",
        "scripts/grabfood/grabfood_mongodb_sync.py"
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
