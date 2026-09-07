#!/usr/bin/env bash
# Giám sát crawl liên tục: restart job chết, chạy đến khi user dừng (pkill -f run_continuous_supervisor).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH=src
export SOCIAL_CONFIG_SOURCE=db
export CHROMEDRIVER_PATH="$ROOT/runtime/bin/chromedriver"

FILMS=(quy_tu_vuot_giau nghi_he_so_nghi_huu)
PLATFORMS=(facebook tiktok threads instagram youtube)
LOG_DIR="$ROOT/runtime/logs/continuous"
PID_DIR="$ROOT/runtime/logs/continuous/pids"
LOCK_DIR="$ROOT/logs/continuous-locks"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"
SLEEP_ROUNDS="${SLEEP_ROUNDS:-180}"

mkdir -p "$LOG_DIR" "$PID_DIR" "$LOCK_DIR"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_DIR/supervisor.log"; }

worker_running() {
  local film="$1" plat="$2"
  pgrep -f "run_continuous_distribution.py.*--film ${film}.*--platform ${plat}" >/dev/null 2>&1 && return 0
  pgrep -f "run_continuous_distribution.py.*--platform ${plat}.*--film ${film}" >/dev/null 2>&1 && return 0
  pgrep -f "run_distribution_pipeline.py.*--film ${film}.*--platform ${plat}" >/dev/null 2>&1 && return 0
  pgrep -f "run_distribution_pipeline.py.*--platform ${plat}.*--film ${film}" >/dev/null 2>&1 && return 0
  return 1
}

clear_stale_lock() {
  local film="$1" plat="$2"
  local lock="$LOCK_DIR/dis-${film}-${plat}.lock"
  [ -f "$lock" ] || return 0
  local lock_pid
  lock_pid="$(sed -n 's/^pid=//p' "$lock" 2>/dev/null | head -1)"
  if [ -z "$lock_pid" ] || ! kill -0 "$lock_pid" 2>/dev/null; then
    rm -f "$lock"
  fi
}

start_worker() {
  local film="$1" plat="$2"
  local key="${film}__${plat}"
  local pidfile="$PID_DIR/${key}.pid"
  local logfile="$LOG_DIR/${key}.log"

  if worker_running "$film" "$plat"; then
    return 0
  fi

  if [ -f "$pidfile" ]; then
    local oldpid
    oldpid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
      return 0
    fi
  fi

  rm -f "$LOCK_DIR/dis-${film}-${plat}.lock"
  clear_stale_lock "$film" "$plat"

  nohup env PYTHONPATH=src SOCIAL_CONFIG_SOURCE=db CHROMEDRIVER_PATH="$CHROMEDRIVER_PATH" \
    "$PY" -u scripts/distribution/run_continuous_distribution.py \
    --film "$film" --platform "$plat" --import-db --continue-on-error --skip-seed \
    --sleep "$SLEEP_ROUNDS" >>"$logfile" 2>&1 &
  local pid=$!
  echo "$pid" >"$pidfile"
  log "RESTART $key pid=$pid"
}

ensure_chrome() {
  "$PY" scripts/distribution/run_by_platform.py status >/dev/null 2>&1 || true
}

log "Supervisor start — films=${FILMS[*]} platforms=${PLATFORMS[*]}"
log "Seed once…"
"$PY" -u scripts/distribution/seed_films.py --apply-schema >>"$LOG_DIR/supervisor.log" 2>&1 || true
ensure_chrome

while true; do
  for film in "${FILMS[@]}"; do
    for plat in "${PLATFORMS[@]}"; do
      start_worker "$film" "$plat"
    done
  done
  sleep "$CHECK_INTERVAL"
done
