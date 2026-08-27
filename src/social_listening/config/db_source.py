"""Load crawl keyword config from Postgres (shared DB between dashboard + crawl servers)."""

from __future__ import annotations

import json
import os
from typing import Any

from social_listening.pg import get_connection


def _term_values(items: Any, *, include_match: bool = True) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            val = str(item.get("value") or item.get("keyword") or item.get("term") or "").strip()
        else:
            val = str(item or "").strip()
        if not val:
            continue
        if val not in out:
            out.append(val)
    return out


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _load_aggregate_payload(cur) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT metadata
        FROM listening_queries
        WHERE query_type = 'brand'
          AND query_name = '__aggregate__'
          AND is_active = TRUE
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    metadata = row[0] if isinstance(row[0], dict) else {}
    full = metadata.get("full_payload")
    if isinstance(full, dict) and full.get("keywords") is not None:
        payload = dict(full)
        payload.setdefault("film_title", "Galaxy Cinema")
        payload.setdefault("film_slug", "galaxy_cinema")
        return payload
    return None


def _load_exclude_rules(cur) -> list[str]:
    """Dashboard Settings → crisis exclude_rules (context + spam) for Marketing crawl."""
    cur.execute(
        """
        SELECT metadata
        FROM listening_queries
        WHERE query_type = 'crisis'
          AND query_name = 'exclude_rules'
          AND is_active = TRUE
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return []

    meta = row[0] if isinstance(row[0], dict) else {}
    terms: list[str] = []
    for key in ("exclude_context", "exclude_spam", "exclude_keywords"):
        raw = meta.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                val = str(item.get("value") or item.get("keyword") or "").strip()
            else:
                val = str(item or "").strip()
            if val and val not in terms:
                terms.append(val)
    return _dedupe(terms)


def _append_cinemas(cur, payload: dict[str, Any]) -> None:
    cur.execute(
        """
        SELECT c.cinema_name, c.metadata
        FROM cinemas c
        JOIN brands b ON b.brand_id = c.brand_id
        WHERE b.brand_slug = 'glx'
          AND c.is_active = TRUE
        ORDER BY c.cinema_name
        """
    )
    queries: list[str] = []
    urls: list[str] = []
    for cinema_name, cinema_meta in cur.fetchall():
        meta = cinema_meta if isinstance(cinema_meta, dict) else {}
        query = str(meta.get("google_maps_query") or cinema_name or "").strip()
        if query and query not in queries:
            queries.append(query)
        url = str(meta.get("place_url") or meta.get("google_maps_url") or "").strip()
        if url and url not in urls:
            urls.append(url)
    if queries:
        payload["google_maps_queries"] = queries
    if urls:
        payload["google_maps_urls"] = urls


def _load_mkt_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "film_title": "Galaxy Cinema",
        "film_slug": "galaxy_cinema",
        "keywords": [],
        "sub_keywords": [],
        "branch_keywords": [],
        "hashtags": [],
        "listening_keywords": [],
        "google_maps_queries": [],
        "google_maps_urls": [],
        "competitor_keywords": [],
    }

    with get_connection() as conn:
        cur = conn.cursor()
        aggregate = _load_aggregate_payload(cur)
        cur.execute(
            """
            SELECT COUNT(*)
            FROM listening_queries
            WHERE query_type = 'brand'
              AND query_name <> '__aggregate__'
              AND is_active = TRUE
            """
        )
        brand_row_count = int(cur.fetchone()[0] or 0)
        if aggregate is not None and brand_row_count == 0:
            _append_cinemas(cur, aggregate)
            exclude = _load_exclude_rules(cur)
            if exclude:
                aggregate["exclude_keywords"] = _dedupe(
                    list(aggregate.get("exclude_keywords") or []) + exclude
                )
            return aggregate

        cur.execute(
            """
            SELECT lq.keywords, lq.hashtags, lq.metadata, lq.is_active, b.brand_slug, b.is_primary
            FROM listening_queries lq
            LEFT JOIN brands b ON b.brand_id = lq.brand_id
            WHERE lq.query_type = 'brand'
              AND lq.query_name <> '__aggregate__'
            ORDER BY b.is_primary DESC NULLS LAST, lq.query_name
            """
        )
        rows = cur.fetchall()
        if not rows:
            raise RuntimeError(
                "No listening_queries in DB. Run scripts/shared/seed_listening_config.py "
                "or set SOCIAL_CONFIG_SOURCE=file"
            )

        for keywords, hashtags, metadata, is_active, brand_slug, is_primary in rows:
            if not is_active:
                continue
            meta = metadata if isinstance(metadata, dict) else {}
            kw_vals = _term_values(keywords)
            ht_vals = _term_values(hashtags)
            sub_vals = _term_values(meta.get("sub_keywords"))
            branch_vals = _term_values(meta.get("branch_keywords"))
            listen_vals = _term_values(meta.get("listening_keywords"))

            ht_items = hashtags if isinstance(hashtags, list) else []
            for item in ht_items:
                if isinstance(item, dict) and item.get("kind") == "campaign":
                    val = str(item.get("value") or "").strip()
                    if val:
                        listen_vals.append(val)

            payload["keywords"].extend(kw_vals)
            payload["sub_keywords"].extend(sub_vals)
            payload["branch_keywords"].extend(branch_vals)
            payload["hashtags"].extend(ht_vals)
            payload["listening_keywords"].extend(listen_vals)

            if brand_slug and brand_slug != "glx" and not is_primary:
                payload["competitor_keywords"].extend(kw_vals)

        for key in (
            "keywords",
            "sub_keywords",
            "branch_keywords",
            "hashtags",
            "listening_keywords",
            "competitor_keywords",
        ):
            payload[key] = _dedupe(payload[key])

        _append_cinemas(cur, payload)

        exclude = _load_exclude_rules(cur)
        if exclude:
            payload["exclude_keywords"] = _dedupe(list(payload.get("exclude_keywords") or []) + exclude)
        elif "exclude_keywords" not in payload:
            payload["exclude_keywords"] = []

    return payload


def _load_film_payload(film_slug: str) -> dict[str, Any]:
    slug = film_slug.strip().lower().replace(" ", "_")
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT lq.keywords, lq.hashtags, lq.metadata, f.film_title, lq.is_active
            FROM films f
            LEFT JOIN listening_queries lq
              ON lq.query_type = 'movie'
             AND lq.metadata->>'film_slug' = f.film_slug
            WHERE f.film_slug = %s
            ORDER BY lq.updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(
                f"Film slug not found in DB: {slug}. Run scripts/distribution/seed_films.py"
            )

        keywords, hashtags, metadata, film_title, is_active = row
        if keywords is None and hashtags is None and metadata is None:
            # Film exists but no listening_queries row yet — fallback title only
            payload = {
                "film_title": film_title or slug,
                "film_slug": slug,
                "keywords": [film_title or slug],
                "core_keywords": [film_title or slug],
                "sub_keywords": [],
                "branch_keywords": [],
                "hashtags": [],
                "listening_keywords": [],
                "ambiguous_keywords": [],
                "context_keywords": [],
                "exclude_keywords": [],
                "require_context": False,
            }
        else:
            if is_active is False:
                raise RuntimeError(f"Film keyword query inactive in DB: {slug}")
            meta = metadata if isinstance(metadata, dict) else {}
            full = meta.get("full_payload") if isinstance(meta.get("full_payload"), dict) else {}
            kw_vals = _dedupe(_term_values(keywords) + _term_values(full.get("keywords")))
            core_vals = _dedupe(
                _term_values(meta.get("core_keywords"))
                + _term_values(full.get("core_keywords"))
                + kw_vals
            )
            payload = {
                "film_title": film_title or str(full.get("film_title") or slug),
                "film_slug": slug,
                "keywords": kw_vals or core_vals,
                "core_keywords": core_vals,
                "sub_keywords": _dedupe(
                    _term_values(meta.get("sub_keywords")) + _term_values(full.get("sub_keywords"))
                ),
                "branch_keywords": _dedupe(
                    _term_values(meta.get("branch_keywords"))
                    + _term_values(full.get("branch_keywords"))
                ),
                "hashtags": _dedupe(_term_values(hashtags) + _term_values(full.get("hashtags"))),
                "listening_keywords": _dedupe(
                    _term_values(meta.get("listening_keywords"))
                    + _term_values(full.get("listening_keywords"))
                ),
                "boost_keywords": _dedupe(
                    _term_values(meta.get("boost_keywords"))
                    + _term_values(full.get("boost_keywords"))
                ),
                "ambiguous_keywords": _dedupe(
                    _term_values(meta.get("ambiguous_keywords"))
                    + _term_values(full.get("ambiguous_keywords"))
                ),
                "ambiguous_context_keywords": _dedupe(
                    _term_values(meta.get("ambiguous_context_keywords"))
                    + _term_values(full.get("ambiguous_context_keywords"))
                ),
                "context_keywords": _dedupe(
                    _term_values(meta.get("context_keywords"))
                    + _term_values(full.get("context_keywords"))
                ),
                "exclude_keywords": _dedupe(
                    _term_values(meta.get("exclude_keywords"))
                    + _term_values(full.get("exclude_keywords"))
                ),
                "soft_exclude_keywords": _dedupe(
                    _term_values(meta.get("soft_exclude_keywords"))
                    + _term_values(full.get("soft_exclude_keywords"))
                ),
                "require_context": bool(
                    meta.get("require_context", full.get("require_context", False))
                ),
                "listening_from": str(
                    meta.get("listening_from") or full.get("listening_from") or ""
                ).strip()
                or None,
                "distribution": True,
                "query_type": "movie",
            }

        exclude = _load_exclude_rules(cur)
        if exclude:
            payload["exclude_keywords"] = _dedupe(
                list(payload.get("exclude_keywords") or []) + exclude
            )
        return payload


def load_keyword_payload_from_db(film_slug: str | None = None) -> dict[str, Any]:
    profile = (os.getenv("SOCIAL_LISTENING_PROFILE") or "mkt").strip().lower()
    slug = (film_slug or os.getenv("SOCIAL_FILM_SLUG") or "").strip() or None
    if profile in {"dis", "distribution", "film"} or slug:
        if not slug:
            raise RuntimeError(
                "Distribution DB config requires SOCIAL_FILM_SLUG (or film_slug arg)"
            )
        return _load_film_payload(slug)
    return _load_mkt_payload()


def list_film_keyword_payloads_from_db(*, active_only: bool = True) -> list[dict[str, Any]]:
    """All movie listening_queries for detect/import (Settings-driven)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT f.film_slug
            FROM films f
            WHERE (%s = FALSE OR f.is_active = TRUE)
            ORDER BY f.film_title
            """,
            (active_only,),
        )
        slugs = [str(r[0]) for r in cur.fetchall()]
    out: list[dict[str, Any]] = []
    for slug in slugs:
        try:
            out.append(_load_film_payload(slug))
        except RuntimeError:
            continue
    return out


def load_galaxy_cinema_queries_from_db() -> list[str]:
    with get_connection() as conn:
        cur = conn.cursor()
        payload: dict[str, Any] = {}
        _append_cinemas(cur, payload)
    return payload.get("google_maps_queries") or []
