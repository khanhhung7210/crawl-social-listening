"""Regression tests for daily_brand_metrics prune + upsert recompute."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "marketing" / "metrics" / "recompute_daily_brand_metrics.py"


def _load_module():
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("recompute_daily_brand_metrics", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["recompute_daily_brand_metrics"] = mod
    spec.loader.exec_module(mod)
    return mod


m = _load_module()

D1 = date(2026, 9, 1)
D2 = date(2026, 9, 2)
D3 = date(2026, 8, 15)  # outside typical scoped window
GLX = "brand-glx"
CGV = "brand-cgv"


def _row(buzz: int) -> dict:
    return {"buzz_count": buzz}


class OrphanPruneSemanticsTest(unittest.TestCase):
    def test_removed_brand_link_deletes_metric_key(self) -> None:
        """If mention/brand link removed, corresponding metric key is pruned."""
        existing = {
            (D1, GLX, "all"): _row(8),
            (D1, GLX, "facebook"): _row(8),
            (D1, CGV, "all"): _row(10),
        }
        fresh = {
            (D1, CGV, "all"): _row(10),
            (D1, CGV, "facebook"): _row(10),
        }
        out = m.apply_prune_and_upsert(existing, fresh)
        self.assertNotIn((D1, GLX, "all"), out)
        self.assertNotIn((D1, GLX, "facebook"), out)
        self.assertEqual(out[(D1, CGV, "all")]["buzz_count"], 10)
        orphans = m.orphan_keys_to_delete(existing.keys(), fresh.keys())
        self.assertEqual(orphans, {(D1, GLX, "all"), (D1, GLX, "facebook")})

    def test_no_orphans_when_existing_equals_fresh(self) -> None:
        keys = {(D1, GLX, "all"), (D1, CGV, "all")}
        self.assertEqual(m.orphan_keys_to_delete(keys, keys), set())

    def test_scoped_prune_does_not_touch_outside_range(self) -> None:
        existing = {
            (D3, GLX, "all"): _row(19),
            (D1, GLX, "all"): _row(8),
            (D1, CGV, "all"): _row(5),
        }
        fresh = {
            (D1, CGV, "all"): _row(5),
        }
        out = m.apply_prune_and_upsert(
            existing, fresh, from_date=D1, to_date=D2
        )
        self.assertIn((D3, GLX, "all"), out)
        self.assertEqual(out[(D3, GLX, "all")]["buzz_count"], 19)
        self.assertNotIn((D1, GLX, "all"), out)
        self.assertEqual(out[(D1, CGV, "all")]["buzz_count"], 5)

    def test_idempotent_rerun(self) -> None:
        existing = {
            (D1, GLX, "all"): _row(99),
            (D1, CGV, "all"): _row(10),
        }
        fresh = {
            (D1, CGV, "all"): _row(10),
            (D2, CGV, "all"): _row(3),
        }
        once = m.apply_prune_and_upsert(existing, fresh)
        twice = m.apply_prune_and_upsert(once, fresh)
        self.assertEqual(once, twice)
        self.assertEqual(set(twice.keys()), set(fresh.keys()))

    def test_upsert_updates_buzz_for_surviving_keys(self) -> None:
        existing = {(D1, CGV, "all"): _row(100)}
        fresh = {(D1, CGV, "all"): _row(77)}
        out = m.apply_prune_and_upsert(existing, fresh)
        self.assertEqual(out[(D1, CGV, "all")]["buzz_count"], 77)


class SqlContractTest(unittest.TestCase):
    def test_prune_sql_targets_pk_and_temp_fresh(self) -> None:
        sql, params = m.build_prune_sql()
        self.assertIn("DELETE FROM daily_brand_metrics", sql)
        self.assertIn("_fresh_daily_brand_metrics", sql)
        self.assertIn("f.metric_date = d.metric_date", sql)
        self.assertIn("f.brand_id = d.brand_id", sql)
        self.assertIn("f.platform_code = d.platform_code", sql)
        self.assertEqual(params, [])

    def test_prune_sql_scoped_params(self) -> None:
        sql, params = m.build_prune_sql(from_date=D1, to_date=D2)
        self.assertIn("d.metric_date >= %s::date", sql)
        self.assertIn("d.metric_date <= %s::date", sql)
        self.assertEqual(params, [D1, D2])

    def test_fresh_sql_joins_mention_brands_only(self) -> None:
        sql, params = m.build_fresh_select_sql()
        self.assertIn("JOIN mention_brands mb", sql)
        self.assertIn("is_spam = FALSE", sql)
        self.assertNotIn("COMPETITIVE_KEYWORD_SQL", sql)
        self.assertEqual(params, [])

    def test_fresh_sql_date_filter_params(self) -> None:
        sql, params = m.build_fresh_select_sql(from_date=D1, to_date=D2)
        self.assertIn(">= %s::date", sql)
        self.assertIn("<= %s::date", sql)
        self.assertEqual(params, [D1, D2])

    def test_upsert_on_conflict_pk(self) -> None:
        self.assertIn("ON CONFLICT (metric_date, brand_id, platform_code)", m.UPSERT_SQL)
        self.assertIn("FROM _fresh_daily_brand_metrics", m.UPSERT_SQL)


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.rowcount = 0
        self._fresh_count = 2
        self._total_count = 5

    def execute(self, sql: str, params=None) -> None:
        self.statements.append((sql, params))
        s = " ".join(sql.split()).lower()
        if s.startswith("delete from daily_brand_metrics"):
            self.rowcount = 3
        elif s.startswith("insert into daily_brand_metrics"):
            self.rowcount = 2
        else:
            self.rowcount = 0

    def fetchone(self):
        last = self.statements[-1][0].lower()
        if "from _fresh_daily_brand_metrics" in last and "count" in last:
            return (self._fresh_count,)
        if "from daily_brand_metrics" in last and "count" in last:
            return (self._total_count,)
        return (0,)


class RecomputeDriverTest(unittest.TestCase):
    def test_driver_creates_temp_then_prune_then_upsert(self) -> None:
        cur = FakeCursor()
        stats = m.recompute_daily_brand_metrics(cur, from_date=D1, to_date=D2)
        joined = "\n".join(sql for sql, _ in cur.statements)
        self.assertIn("CREATE TEMP TABLE _fresh_daily_brand_metrics", joined)
        self.assertIn("DELETE FROM daily_brand_metrics", joined)
        self.assertIn("INSERT INTO daily_brand_metrics", joined)
        create_i = next(
            i for i, (s, _) in enumerate(cur.statements) if "CREATE TEMP TABLE" in s
        )
        delete_i = next(
            i for i, (s, _) in enumerate(cur.statements) if s.strip().startswith("DELETE")
        )
        insert_i = next(
            i for i, (s, _) in enumerate(cur.statements) if s.strip().startswith("INSERT")
        )
        self.assertLess(create_i, delete_i)
        self.assertLess(delete_i, insert_i)
        self.assertEqual(stats["deleted_orphans"], 3)
        self.assertEqual(stats["fresh_rows"], 2)
        self.assertEqual(stats["upserted"], 2)
        self.assertEqual(stats["total_rows"], 5)

    def test_rejects_inverted_range(self) -> None:
        with self.assertRaises(ValueError):
            m.recompute_daily_brand_metrics(FakeCursor(), from_date=D2, to_date=D1)


class ParseArgsSmokeTest(unittest.TestCase):
    def test_parse_iso_date(self) -> None:
        self.assertEqual(m.parse_iso_date("2026-09-01"), D1)


if __name__ == "__main__":
    unittest.main()
