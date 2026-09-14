#!/usr/bin/env bash
# Reprocess mention sentiment on shared Postgres (10.10.17.18).
# Run on Mac (VPN on) or Windows crawl server — not from Cursor sandbox.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Load only PG* from .env (do not `source` whole file — KEYWORD etc. may contain spaces)
if [[ -f "$ROOT/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^PG[A-Z0-9_]*= ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    export "${key}=${val}"
  done < "$ROOT/.env"
fi

export SENTIMENT_PROVIDER="${SENTIMENT_PROVIDER:-phobert}"
export SENTIMENT_ALLOW_KEYWORD_FALLBACK="${SENTIMENT_ALLOW_KEYWORD_FALLBACK:-1}"
export PYTHONPATH="${PYTHONPATH:-src:.pip_packages}"

MODEL="${SENTIMENT_PHOBERT_MODEL:-wonrax/phobert-base-vietnamese-sentiment}"
if [[ -d "$ROOT/runtime/models/wonrax-phobert-base-vietnamese-sentiment" ]]; then
  export SENTIMENT_PHOBERT_MODEL="$ROOT/runtime/models/wonrax-phobert-base-vietnamese-sentiment"
else
  export SENTIMENT_PHOBERT_MODEL="$MODEL"
fi

PY="${ROOT}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

echo "PGHOST=${PGHOST:-?} PGDATABASE=${PGDATABASE:-?} SENTIMENT_PROVIDER=$SENTIMENT_PROVIDER"
echo "Model: $SENTIMENT_PHOBERT_MODEL"
echo "Args: $*"

exec "$PY" scripts/source_b/reprocess_sentiment.py --batch-size 32 "$@"
