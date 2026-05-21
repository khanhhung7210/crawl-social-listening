import { execFileSync } from 'child_process';
import { unlinkSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

export const SCHEMA = process.env.PGSCHEMA || 'meili_dashboard';
export const PGDATABASE = process.env.PGDATABASE || 'meili_dashboard';
export const PSQL_BIN = process.env.PSQL_BIN || 'psql';
export const BRAND_SLUG = process.env.BRAND_SLUG || 'meili-mi-bo-dai-loan';

export function runPsqlText(sql) {
  if (Buffer.byteLength(sql, 'utf8') < 100_000) {
    return execFileSync(PSQL_BIN, [PGDATABASE, '-Atqc', sql], {
      cwd: process.cwd(),
      env: process.env,
      encoding: 'utf8',
    });
  }
  const tempPath = join(tmpdir(), `dashboard-local-${process.pid}-${Date.now()}.sql`);
  writeFileSync(tempPath, sql, 'utf8');
  try {
    return execFileSync(PSQL_BIN, [PGDATABASE, '-Atqf', tempPath], {
      cwd: process.cwd(),
      env: process.env,
      encoding: 'utf8',
    });
  } finally {
    try {
      unlinkSync(tempPath);
    } catch {
      // Ignore temp cleanup failures.
    }
  }
}

export function queryJson(sql) {
  const text = runPsqlText(sql).trim();
  if (!text) return [];
  return JSON.parse(text);
}

export function sqlStr(value) {
  if (value == null) return 'NULL';
  return `'${String(value).replace(/'/g, "''")}'`;
}

export function sqlNum(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : '0';
}

export function sqlBool(value) {
  return value ? 'TRUE' : 'FALSE';
}

export function sqlJson(value) {
  return sqlStr(JSON.stringify(value ?? null));
}

export function normalizeText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

export function compactWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

export function includesAny(text, patterns) {
  return patterns.some((pattern) => text.includes(pattern));
}

export function countMatches(text, patterns) {
  return patterns.reduce((sum, pattern) => sum + (text.includes(pattern) ? 1 : 0), 0);
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function titleCase(value) {
  return String(value || '')
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}
