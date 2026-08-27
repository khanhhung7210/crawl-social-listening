#!/bin/bash
# Setup local Postgres (Homebrew) for Galaxy Social Listening — no Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB_NAME="${PGDATABASE:-galaxy_social_listening}"
SCHEMA_FILE="$ROOT/sql/galaxy_mkt_schema.sql"

echo "==> Checking Postgres..."
if ! pg_isready -q; then
  echo "Postgres not accepting connections. Try:"
  echo "  brew services start postgresql@14"
  echo "  # or: pg_ctl -D /opt/homebrew/var/postgresql@14 start"
  exit 1
fi

echo "==> Ensuring database $DB_NAME exists..."
if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  createdb "$DB_NAME"
  echo "Created $DB_NAME"
else
  echo "Database $DB_NAME already exists"
fi

echo "==> Applying schema $SCHEMA_FILE ..."
psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"

echo "==> Done. Example:"
echo "  psql -d $DB_NAME -c \"SET search_path TO galaxy_sl; SELECT brand_slug FROM brands;\""
