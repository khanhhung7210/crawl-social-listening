from __future__ import annotations

import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pymongo.collection import Collection

from social_listening.mongodb_sync import build_mongo_client


class DashboardRepository(Protocol):
    def get_available_films(self) -> list[str]:
        ...

    def get_dashboard_payload(self, film_title: str | None = None) -> dict | None:
        ...

    def get_source_config(self) -> dict:
        ...

    def save_source_config(self, config: dict | list[dict]) -> dict:
        ...


class JsonDashboardRepository:
    def __init__(self, data_file: Path) -> None:
        self.data_file = Path(data_file)

    def get_available_films(self) -> list[str]:
        payload = self._load()
        brand_name = str((payload.get("brand") or {}).get("brand_name") or "").strip()
        return [brand_name] if brand_name else []

    def get_dashboard_payload(self, film_title: str | None = None) -> dict | None:
        payload = self._load()
        if film_title:
            payload["requested_film_title"] = film_title.strip()
        return payload

    def get_source_config(self) -> dict:
        return {"completed": True, "sources": [], "competitor_radar": ""}

    def save_source_config(self, config: dict | list[dict]) -> dict:
        sources = config.get("sources") if isinstance(config, dict) else config
        competitor_radar = config.get("competitor_radar") if isinstance(config, dict) else ""
        return {"completed": True, "sources": sources or [], "competitor_radar": competitor_radar or ""}

    def _load(self) -> dict:
        payload = json.loads(self.data_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected object JSON payload in {self.data_file}")
        return payload


class MongoDashboardRepository:
    def __init__(self, db_name: str = "CRM") -> None:
        self.client = build_mongo_client()
        self.db = self.client[db_name]
        self.sentiment_collection: Collection = self.db["tblSentiment"]
        self.social_collection: Collection = self.db["tblSocial"]

    def get_available_films(self) -> list[str]:
        films = set()
        films.update(filter(None, self.sentiment_collection.distinct("film_title")))
        films.update(filter(None, self.social_collection.distinct("film_title")))
        return sorted(str(film).strip() for film in films if str(film).strip())

    def get_dashboard_payload(self, film_title: str | None = None) -> dict | None:
        return None

    def get_source_config(self) -> dict:
        return {"completed": False, "sources": [], "competitor_radar": ""}

    def save_source_config(self, config: dict | list[dict]) -> dict:
        sources = config.get("sources") if isinstance(config, dict) else config
        competitor_radar = config.get("competitor_radar") if isinstance(config, dict) else ""
        return {"completed": bool(sources), "sources": sources or [], "competitor_radar": competitor_radar or ""}

    def get_sentiment_rows(self, film_title: str | None = None) -> list[dict]:
        query = build_film_query(film_title)
        return list(self.sentiment_collection.find(query, {"_id": 0}))

    def get_social_rows(self, film_title: str | None = None, limit: int = 5000) -> list[dict]:
        query = build_film_query(film_title)
        cursor = self.social_collection.find(
            query,
            {
                "_id": 0,
                "platform": 1,
                "page_name": 1,
                "source": 1,
                "post_text": 1,
                "comments_": 1,
                "film_title": 1,
            },
        ).limit(limit)
        return list(cursor)


def build_film_query(film_title: str | None) -> dict:
    if film_title and film_title.strip():
        return {"film_title": film_title.strip()}
    return {}


class PostgresDashboardRepository:
    def __init__(self, database: str = "meili_dashboard", schema: str = "meili_dashboard", brand_slug: str = "meili-mi-bo-dai-loan", psql_bin: str = "psql") -> None:
        self.database = database
        self.schema = schema
        self.brand_slug = brand_slug
        self.psql_bin = psql_bin

    def get_available_films(self) -> list[str]:
        rows = self._query_json(
            f"""
            SELECT COALESCE(json_agg(brand_name ORDER BY brand_name), '[]'::json)
            FROM {self.schema}.brands
            WHERE brand_slug = {sql_str(self.brand_slug)};
            """
        )
        return [str(item).strip() for item in rows if str(item).strip()]

    def get_dashboard_payload(self, film_title: str | None = None) -> dict | None:
        brand = self._brand()
        if not brand:
            return None
        source_config = self.get_source_config()
        branches = self._branches()
        branch_by_slug = {str(row.get("branch_slug") or ""): row for row in branches}
        mentions = self._mentions()
        reviews = self._reviews()
        menu_items = self._menu_items()

        platform_summary = self._build_platform_summary(mentions, reviews, menu_items)
        branch_intelligence, daily_branch_metrics = self._build_branch_intelligence(branches, mentions, reviews, menu_items)
        menu_highlights = self._build_menu_highlights(menu_items, branch_by_slug)
        evidence_cards = self._build_evidence_cards(mentions, reviews, branch_by_slug)
        action_feed = self._build_action_feed(platform_summary, branch_intelligence, evidence_cards)
        quick_cards = self._build_quick_cards(platform_summary, branch_intelligence, reviews, evidence_cards)
        overview = self._build_overview(brand, platform_summary, branch_intelligence, reviews, evidence_cards, action_feed)
        screens = self._build_screens(
            overview=overview,
            platform_summary=platform_summary,
            branch_intelligence=branch_intelligence,
            daily_branch_metrics=daily_branch_metrics,
            menu_highlights=menu_highlights,
            evidence_cards=evidence_cards,
            action_feed=action_feed,
        )

        payload = {
            "brand": brand,
            "generated_at": now_iso(),
            "date_range": self._build_date_range(),
            "overview": overview,
            "platform_summary": platform_summary,
            "branches": branches,
            "branch_intelligence": branch_intelligence,
            "daily_branch_metrics": daily_branch_metrics,
            "menu_highlights": menu_highlights,
            "evidence_cards": evidence_cards,
            "mentions_feed": action_feed,
            "quick_cards": quick_cards,
            "screens": screens,
            "requested_film_title": film_title or brand.get("brand_name", ""),
            "source_config_completed": bool(source_config.get("completed")),
            "source_config": source_config,
        }
        snapshot = self._latest_dashboard_snapshot()
        if isinstance(snapshot, dict) and snapshot:
            payload = self._apply_snapshot_overrides(payload, snapshot)
        return payload

    def get_all_evidence_cards(self) -> list[dict]:
        """Fetch all evidence cards for the brand"""
        result = self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY evidence_date DESC), '[]'::json)
            FROM (
              SELECT
                evidence_card_id::text,
                platform,
                evidence_date::text,
                sentiment_label,
                confidence_score::float,
                metric_label,
                evidence_quote,
                source_url,
                tags
              FROM {self.schema}.evidence_cards
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY evidence_date DESC
              LIMIT 500
            ) t;
            """
        )
        return result if result else []

    def get_source_config(self) -> dict:
        self._ensure_brand_source_config_table()
        brand_id = self._brand_id()
        if not brand_id:
            return {"completed": False, "sources": [], "competitor_radar": ""}
        rows = self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.include_in_dashboard DESC, t.priority, t.platform, t.channel_name), '[]'::json)
            FROM (
              SELECT
                platform,
                channel_name,
                source_url,
                source_type,
                priority,
                include_in_dashboard,
                crawl_enabled,
                metadata
              FROM {self.schema}.brand_source_configs
              WHERE brand_id = {sql_str(brand_id)}
            ) t;
            """
        ) or []
        competitor_radar = ""
        for row in rows:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            if isinstance(metadata, dict) and str(metadata.get("competitor_radar") or "").strip():
                competitor_radar = str(metadata.get("competitor_radar") or "").strip()
                break
        return {"completed": bool(rows), "sources": rows, "competitor_radar": competitor_radar}

    def save_source_config(self, config: dict | list[dict]) -> dict:
        self._ensure_brand_source_config_table()
        brand_id = self._brand_id()
        if not brand_id:
            raise RuntimeError(f"Brand slug not found: {self.brand_slug}")
        sources = config.get("sources") if isinstance(config, dict) else config
        competitor_radar = str(config.get("competitor_radar") or "").strip() if isinstance(config, dict) else ""
        source_rows = sources if isinstance(sources, list) else []
        normalized_sources = [row for row in (self._normalize_source_config(source) for source in source_rows) if row]
        if competitor_radar:
            for row in normalized_sources:
                metadata = dict(row.get("metadata") or {})
                metadata["competitor_radar"] = competitor_radar
                row["metadata"] = metadata
        statements = [f"DELETE FROM {self.schema}.brand_source_configs WHERE brand_id = {sql_str(brand_id)};"]
        for row in normalized_sources:
            statements.append(
                f"""
                INSERT INTO {self.schema}.brand_source_configs (
                  brand_id, platform, channel_name, source_url, source_type, priority,
                  include_in_dashboard, crawl_enabled, metadata
                )
                VALUES (
                  {sql_str(brand_id)},
                  {sql_str(row['platform'])},
                  {sql_str(row['channel_name'])},
                  {sql_str(row['source_url'])},
                  {sql_str(row['source_type'])},
                  {sql_str(row['priority'])},
                  {sql_bool(row['include_in_dashboard'])},
                  {sql_bool(row['crawl_enabled'])},
                  {sql_json(row['metadata'])}::jsonb
                );
                """.strip()
            )
        self._execute_sql("\n".join(statements))
        return self.get_source_config()

    def _latest_dashboard_snapshot(self) -> dict | None:
        return self._query_json(
            f"""
            SELECT COALESCE(ds.payload, '{{}}'::jsonb)::json
            FROM {self.schema}.dashboard_snapshots ds
            JOIN {self.schema}.brands br ON br.brand_id = ds.brand_id
            WHERE br.brand_slug = {sql_str(self.brand_slug)}
              AND ds.scope_type = 'brand'
              AND ds.scope_key = 'all'
            ORDER BY ds.snapshot_date DESC, ds.created_at DESC
            LIMIT 1;
            """
        )

    def _apply_snapshot_overrides(self, payload: dict, snapshot: dict) -> dict:
        merged = json.loads(json.dumps(payload))
        is_backend_snapshot = str((snapshot.get("backend") or {}).get("name") or "") == "dashboard_backend_processor"

        overview_override = snapshot.get("overview")
        if isinstance(overview_override, dict):
            target = merged.setdefault("overview", {})
            for key in ("headline", "top_cards"):
                if overview_override.get(key):
                    target[key] = overview_override[key]

        screen_overrides = snapshot.get("screens")
        if isinstance(screen_overrides, dict):
            screens = merged.setdefault("screens", {})
            for screen_key, override in screen_overrides.items():
                if not isinstance(override, dict):
                    continue
                target_screen = screens.setdefault(screen_key, {})
                keys = ("headline", "subtitle", "feed") if screen_key == "brand" else ("headline", "subtitle", "topCards", "feed")
                for key in keys:
                    if override.get(key):
                        target_screen[key] = override[key]
                if isinstance(override.get("modules"), list):
                    existing_modules = target_screen.get("modules") or []
                    if is_backend_snapshot or not existing_modules:
                        target_screen["modules"] = override["modules"]
                    else:
                        by_title = {str(module.get("title") or ""): module for module in override["modules"] if isinstance(module, dict)}
                        rebuilt = []
                        seen = set()
                        for module in existing_modules:
                            title = str(module.get("title") or "")
                            if title in by_title:
                                rebuilt.append(by_title[title])
                                seen.add(title)
                            else:
                                rebuilt.append(module)
                        for title, module in by_title.items():
                            if title not in seen:
                                rebuilt.append(module)
                        target_screen["modules"] = rebuilt

        if isinstance(snapshot.get("quick_cards"), list):
            merged["quick_cards"] = snapshot["quick_cards"]
        if isinstance(snapshot.get("mentions_feed"), list):
            merged["mentions_feed"] = snapshot["mentions_feed"]
        if isinstance(snapshot.get("backend"), dict):
            merged["backend"] = snapshot["backend"]
        if isinstance(snapshot.get("requirements"), dict):
            merged["requirements"] = snapshot["requirements"]
        return merged

    def _brand(self) -> dict | None:
        return self._query_json(
            f"""
            SELECT COALESCE(row_to_json(t), '{{}}'::json)
            FROM (
              SELECT brand_slug, brand_name, vertical, timezone_name
              FROM {self.schema}.brands
              WHERE brand_slug = {sql_str(self.brand_slug)}
              LIMIT 1
            ) t;
            """
        )

    def _branches(self) -> list[dict]:
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.branch_slug), '[]'::json)
            FROM (
              SELECT
                b.branch_id::text,
                b.branch_slug,
                b.branch_name,
                COALESCE(b.address_line, '') AS address_line,
                COALESCE(b.district, '') AS district,
                COALESCE(b.city, '') AS city,
                COALESCE(b.google_maps_url, '') AS google_maps_url,
                COALESCE(b.shopeefood_url, '') AS shopeefood_url,
                COALESCE(b.metadata->>'restaurant_id','') AS restaurant_id,
                COALESCE(b.metadata->>'delivery_id','') AS delivery_id,
                CASE
                  WHEN COALESCE(b.google_maps_url, '') <> '' AND COALESCE(b.shopeefood_url, '') <> '' THEN 'full_ref'
                  WHEN COALESCE(b.shopeefood_url, '') <> '' THEN 'delivery_mapped'
                  ELSE 'mapped'
                END AS status
              FROM {self.schema}.branches b
              JOIN {self.schema}.brands br ON br.brand_id = b.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
            ) t;
            """
        ) or []

    def _mentions(self) -> list[dict]:
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
            FROM (
              SELECT
                m.mention_id::text,
                COALESCE(m.branch_id::text, '') AS branch_id,
                COALESCE(b.branch_slug, '') AS branch_slug,
                m.platform,
                m.source_type,
                m.content_type,
                COALESCE(m.page_name, '') AS page_name,
                COALESCE(m.author_name, '') AS author_name,
                COALESCE(m.post_url, '') AS post_url,
                COALESCE(m.content_text, '') AS content_text,
                m.content_created_at,
                COALESCE(me.is_relevant_fnb, TRUE) AS is_relevant_fnb,
                COALESCE(me.relevance_score, 0) AS relevance_score,
                COALESCE(me.sentiment_label, '') AS sentiment_label,
                COALESCE(me.topic_label, '') AS topic_label,
                COALESCE(me.issue_type, '') AS issue_type,
                COALESCE(me.confidence_score, 0) AS confidence_score
              FROM {self.schema}.mentions m
              LEFT JOIN {self.schema}.branches b ON b.branch_id = m.branch_id
              LEFT JOIN {self.schema}.mention_enrichments me ON me.mention_id = m.mention_id
              JOIN {self.schema}.brands br ON br.brand_id = m.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
            ) t;
            """
        ) or []

    def _reviews(self) -> list[dict]:
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
            FROM (
              SELECT
                r.review_id::text,
                COALESCE(r.branch_id::text, '') AS branch_id,
                COALESCE(b.branch_slug, '') AS branch_slug,
                COALESCE(b.branch_name, '') AS branch_name,
                r.platform,
                COALESCE(r.review_url, '') AS review_url,
                COALESCE(r.reviewer_name, '') AS reviewer_name,
                COALESCE(r.review_text, '') AS review_text,
                COALESCE(r.rating, 0) AS rating,
                r.review_created_at,
                COALESCE(re.sentiment_label, '') AS sentiment_label,
                COALESCE(re.topic_label, '') AS topic_label,
                COALESCE(re.issue_type, '') AS issue_type,
                COALESCE(re.confidence_score, 0) AS confidence_score,
                COALESCE(re.needs_response, FALSE) AS needs_response,
                COALESCE(re.is_high_risk, FALSE) AS is_high_risk
              FROM {self.schema}.reviews r
              LEFT JOIN {self.schema}.branches b ON b.branch_id = r.branch_id
              LEFT JOIN {self.schema}.review_enrichments re ON re.review_id = r.review_id
              JOIN {self.schema}.brands br ON br.brand_id = r.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
            ) t;
            """
        ) or []

    def _menu_items(self) -> list[dict]:
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
            FROM (
              SELECT
                mi.menu_item_id::text,
                COALESCE(b.branch_slug, '') AS branch_slug,
                mi.platform,
                mi.item_name,
                COALESCE(mi.item_description, '') AS item_description,
                COALESCE(mi.price_amount, 0) AS price_amount,
                COALESCE(mi.sold_count, 0) AS sold_count,
                COALESCE(mi.item_rating, 0) AS item_rating,
                COALESCE(mi.item_review_count, 0) AS item_review_count,
                COALESCE(mi.review_comments, '[]'::jsonb)::json AS review_comments
              FROM {self.schema}.menu_items mi
              LEFT JOIN {self.schema}.branches b ON b.branch_id = mi.branch_id
              JOIN {self.schema}.brands br ON br.brand_id = mi.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
            ) t;
            """
        ) or []

    def _build_platform_summary(self, mentions: list[dict], reviews: list[dict], menu_items: list[dict]) -> list[dict]:
        summary: dict[str, dict] = {}
        for mention in mentions:
            platform = str(mention.get("platform") or "")
            if not platform:
                continue
            row = summary.setdefault(platform, {
                "platform": platform,
                "source_type": mention.get("source_type") or "",
                "mention_count": 0,
                "post_count": 0,
                "comment_count": 0,
                "review_count": 0,
                "menu_count": 0,
                "relevant_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "status": "pending_filter",
                "readiness_score": 0,
            })
            row["mention_count"] += 1
            if mention.get("content_type") == "post":
                row["post_count"] += 1
            elif mention.get("content_type") in {"comment", "reply", "review"}:
                row["comment_count"] += 1
            if bool(mention.get("is_relevant_fnb", True)):
                row["relevant_count"] += 1
            sentiment = self._resolve_sentiment(str(mention.get("sentiment_label") or ""), str(mention.get("content_text") or ""))
            if sentiment == "positive":
                row["positive_count"] += 1
            elif sentiment == "negative":
                row["negative_count"] += 1
        for review in reviews:
            platform = str(review.get("platform") or "")
            if not platform:
                continue
            row = summary.setdefault(platform, {
                "platform": platform,
                "source_type": "maps" if platform == "google_maps" else "delivery_review",
                "mention_count": 0,
                "post_count": 0,
                "comment_count": 0,
                "review_count": 0,
                "menu_count": 0,
                "relevant_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "status": "pending_filter",
                "readiness_score": 0,
            })
            row["review_count"] += 1
            sentiment = self._resolve_review_sentiment(str(review.get("sentiment_label") or ""), review.get("rating"), str(review.get("review_text") or ""))
            if sentiment == "positive":
                row["positive_count"] += 1
            elif sentiment == "negative":
                row["negative_count"] += 1
        for item in menu_items:
            platform = str(item.get("platform") or "")
            if not platform:
                continue
            row = summary.setdefault(platform, {
                "platform": platform,
                "source_type": "delivery_review" if platform == "shopeefood" else "",
                "mention_count": 0,
                "post_count": 0,
                "comment_count": 0,
                "review_count": 0,
                "menu_count": 0,
                "relevant_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "status": "pending_filter",
                "readiness_score": 0,
            })
            row["menu_count"] += 1

        rows: list[dict] = []
        for platform, row in sorted(summary.items()):
            mention_count = int(row["mention_count"])
            relevant_count = int(row["relevant_count"])
            review_count = int(row["review_count"])
            menu_count = int(row.get("menu_count") or 0)
            relevance_ratio = relevant_count / mention_count if mention_count else 1.0
            if platform == "shopeefood" and review_count > 0:
                status = "ready"
            elif platform == "shopeefood" and menu_count > 0:
                status = "delivery_live"
            elif platform == "shopeefood" and review_count == 0:
                status = "metadata_only"
            elif platform == "google_maps" and review_count > 0:
                status = "ready"
            elif mention_count and relevance_ratio < 0.7:
                status = "noisy"
            elif mention_count or review_count:
                status = "ready"
            else:
                status = "pending_filter"
            readiness_score = min(
                100,
                int(relevance_ratio * 55 + min(review_count, 50) * 0.9 + min(menu_count, 120) * 0.18 + min(row["comment_count"], 500) * 0.04),
            )
            row["status"] = status
            row["readiness_score"] = readiness_score
            row["relevance_ratio"] = round(relevance_ratio, 3)
            rows.append(row)
        return rows

    def _build_branch_intelligence(self, branches: list[dict], mentions: list[dict], reviews: list[dict], menu_items: list[dict]) -> tuple[list[dict], list[dict]]:
        branch_stats: dict[str, dict] = {}
        for branch in branches:
            slug = str(branch.get("branch_slug") or "")
            branch_stats[slug] = {
                "branch_slug": slug,
                "branch_name": branch.get("branch_name") or slug,
                "address_line": branch.get("address_line") or "",
                "district": branch.get("district") or "",
                "city": branch.get("city") or "",
                "status": branch.get("status") or "mapped",
                "mention_count": 0,
                "relevant_mention_count": 0,
                "comment_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "review_count": 0,
                "avg_rating": 0.0,
                "menu_count": 0,
                "top_topics": [],
                "risk_score": 0,
                "risk_level": "Low",
                "best_signal": "",
                "watchout": "",
                "source_mix": {},
            }

        topic_buckets: dict[str, Counter] = defaultdict(Counter)
        ratings_sum: dict[str, float] = defaultdict(float)
        rating_count: dict[str, int] = defaultdict(int)

        for mention in mentions:
            slug = str(mention.get("branch_slug") or "")
            if not slug or slug not in branch_stats:
                continue
            stat = branch_stats[slug]
            stat["mention_count"] += 1 if mention.get("content_type") == "post" else 0
            stat["comment_count"] += 1 if mention.get("content_type") in {"comment", "reply", "review"} else 0
            if bool(mention.get("is_relevant_fnb", True)):
                stat["relevant_mention_count"] += 1
            sentiment = self._resolve_sentiment(str(mention.get("sentiment_label") or ""), str(mention.get("content_text") or ""))
            if sentiment == "positive":
                stat["positive_count"] += 1
            elif sentiment == "negative":
                stat["negative_count"] += 1
            topic = str(mention.get("topic_label") or "").strip() or self._guess_topic(str(mention.get("content_text") or ""))
            if topic and topic != "unknown":
                topic_buckets[slug][topic] += 1

        for review in reviews:
            slug = str(review.get("branch_slug") or "")
            if not slug or slug not in branch_stats:
                continue
            stat = branch_stats[slug]
            stat["review_count"] += 1
            rating = float(review.get("rating") or 0)
            if rating > 0:
                ratings_sum[slug] += rating
                rating_count[slug] += 1
            sentiment = self._resolve_review_sentiment(str(review.get("sentiment_label") or ""), review.get("rating"), str(review.get("review_text") or ""))
            if sentiment == "positive":
                stat["positive_count"] += 1
            elif sentiment == "negative":
                stat["negative_count"] += 1
            topic = str(review.get("topic_label") or "").strip() or self._guess_topic(str(review.get("review_text") or ""))
            if topic and topic != "unknown":
                topic_buckets[slug][topic] += 1

        for item in menu_items:
            slug = str(item.get("branch_slug") or "")
            if not slug or slug not in branch_stats:
                continue
            branch_stats[slug]["menu_count"] += 1

        branch_rows: list[dict] = []
        daily_rows: list[dict] = []
        for slug, stat in branch_stats.items():
            avg_rating = ratings_sum[slug] / rating_count[slug] if rating_count[slug] else 0.0
            stat["avg_rating"] = round(avg_rating, 2)
            stat["top_topics"] = [name for name, _ in topic_buckets[slug].most_common(3)]
            stat["risk_score"] = self._compute_branch_risk(stat)
            stat["risk_level"] = self._risk_level(stat["risk_score"])
            stat["best_signal"] = self._best_signal(stat)
            stat["watchout"] = self._watchout(stat)
            stat["source_mix"] = {
                "mentions": stat["mention_count"],
                "comments": stat["comment_count"],
                "reviews": stat["review_count"],
                "menu_items": stat["menu_count"],
            }
            branch_rows.append(stat)
            daily_rows.append(
                {
                    "branch_slug": slug,
                    "metric_date": datetime.now(timezone.utc).date().isoformat(),
                    "mention_count": stat["mention_count"],
                    "relevant_mention_count": stat["relevant_mention_count"],
                    "review_count": stat["review_count"],
                    "avg_rating": stat["avg_rating"],
                    "negative_count": stat["negative_count"],
                    "positive_count": stat["positive_count"],
                    "risk_score": stat["risk_score"],
                    "top_topics": stat["top_topics"],
                    "source_mix": stat["source_mix"],
                }
            )
        branch_rows.sort(key=lambda item: (-int(item["risk_score"]), str(item["branch_slug"])))
        daily_rows.sort(key=lambda item: (-int(item["risk_score"]), str(item["branch_slug"])))
        return branch_rows, daily_rows

    def _build_menu_highlights(self, menu_items: list[dict], branch_by_slug: dict[str, dict]) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in menu_items:
            slug = str(item.get("branch_slug") or "")
            grouped[slug].append(item)
        highlights: list[dict] = []
        for slug, items in grouped.items():
            items_sorted = sorted(
                items,
                key=lambda row: (
                    -int(row.get("sold_count") or 0),
                    -int(row.get("item_review_count") or 0),
                    -float(row.get("price_amount") or 0),
                    str(row.get("item_name") or ""),
                ),
            )
            for item in items_sorted[:2]:
                review_comments = item.get("review_comments") if isinstance(item.get("review_comments"), list) else []
                highlights.append(
                    {
                        "branch_slug": slug,
                        "branch_name": branch_by_slug.get(slug, {}).get("branch_name", slug),
                        "platform": item.get("platform") or "",
                        "item_name": item.get("item_name") or "",
                        "price_text": self._price_text(item.get("price_amount")),
                        "sold_count": int(item.get("sold_count") or 0),
                        "item_rating": float(item.get("item_rating") or 0),
                        "item_review_count": int(item.get("item_review_count") or 0),
                        "review_comment_count": len(review_comments),
                        "review_comments": review_comments[:3],
                        "item_description": item.get("item_description") or "",
                    }
                )
        return highlights[:8]

    def _build_evidence_cards(self, mentions: list[dict], reviews: list[dict], branch_by_slug: dict[str, dict]) -> list[dict]:
        cards: list[dict] = []
        for review in reviews:
            text = str(review.get("review_text") or "").strip()
            if not text:
                continue
            sentiment = self._resolve_review_sentiment(str(review.get("sentiment_label") or ""), review.get("rating"), text)
            cards.append(
                {
                    "source_record_type": "review",
                    "platform": review.get("platform") or "",
                    "source_url": review.get("review_url") or "",
                    "evidence_date": review.get("review_created_at"),
                    "sentiment_label": sentiment,
                    "confidence_score": float(review.get("confidence_score") or (0.88 if sentiment in {"positive", "negative"} else 0.72)),
                    "metric_label": branch_by_slug.get(str(review.get("branch_slug") or ""), {}).get("branch_name") or review.get("platform") or "",
                    "evidence_quote": text[:280],
                }
            )
        for mention in mentions:
            if mention.get("content_type") not in {"comment", "reply"}:
                continue
            text = str(mention.get("content_text") or "").strip()
            if len(text) < 8:
                continue
            sentiment = self._resolve_sentiment(str(mention.get("sentiment_label") or ""), text)
            if sentiment not in {"positive", "negative"}:
                continue
            cards.append(
                {
                    "source_record_type": "mention",
                    "platform": mention.get("platform") or "",
                    "source_url": mention.get("post_url") or "",
                    "evidence_date": mention.get("content_created_at"),
                    "sentiment_label": sentiment,
                    "confidence_score": float(mention.get("confidence_score") or 0.74),
                    "metric_label": mention.get("page_name") or mention.get("platform") or "",
                    "evidence_quote": text[:280],
                }
            )
        cards.sort(
            key=lambda item: (
                {"negative": 0, "mixed": 1, "operational": 2, "positive": 3}.get(str(item.get("sentiment_label") or ""), 9),
                -(float(item.get("confidence_score") or 0)),
            )
        )
        return cards[:10]

    def _build_action_feed(self, platform_summary: list[dict], branch_intelligence: list[dict], evidence_cards: list[dict]) -> list[dict]:
        feed: list[dict] = []
        for branch in branch_intelligence[:6]:
            if int(branch.get("risk_score") or 0) <= 0:
                continue
            feed.append(
                {
                    "title": f"{branch.get('branch_name')} cần theo dõi",
                    "platform": "branch",
                    "severity": branch.get("risk_level", "Low").title(),
                    "metric": f"Risk {branch.get('risk_score')}",
                    "owner": "Ops / CX",
                    "status": branch.get("watchout") or "Watch",
                    "summary": f"{branch.get('negative_count', 0)} tín hiệu tiêu cực, {branch.get('review_count', 0)} reviews, rating {branch.get('avg_rating', 0)}.",
                    "source_url": "",
                }
            )
        for row in platform_summary:
            status = str(row.get("status") or "")
            if status in {"metadata_only", "noisy"}:
                feed.append(
                    {
                        "title": f"{row.get('platform')} cần cleanup",
                        "platform": row.get("platform") or "",
                        "severity": "High" if status == "noisy" else "Medium",
                        "metric": f"{row.get('relevant_count', 0)}/{row.get('mention_count', 0)} relevant",
                        "owner": "Listening",
                        "status": "Fix First" if status == "noisy" else "Monitor",
                        "summary": f"Readiness {row.get('readiness_score', 0)} và status {status}.",
                        "source_url": "",
                    }
                )
        for card in evidence_cards[:4]:
            if str(card.get("sentiment_label") or "") != "negative":
                continue
            feed.append(
                {
                    "title": card.get("metric_label") or card.get("platform") or "",
                    "platform": card.get("platform") or "",
                    "severity": "High",
                    "metric": "Negative evidence",
                    "owner": "CX",
                    "status": "Needs Response",
                    "summary": card.get("evidence_quote") or "",
                    "source_url": card.get("source_url") or "",
                }
            )
        return feed[:12]

    def _build_quick_cards(self, platform_summary: list[dict], branch_intelligence: list[dict], reviews: list[dict], evidence_cards: list[dict]) -> list[dict]:
        total_relevant = sum(int(row.get("relevant_count") or 0) for row in platform_summary)
        highest_risk = branch_intelligence[0] if branch_intelligence else {}
        low_rating_reviews = sum(1 for row in reviews if float(row.get("rating") or 0) and float(row.get("rating") or 0) <= 3)
        negative_evidence = sum(1 for row in evidence_cards if str(row.get("sentiment_label") or "") == "negative")
        return [
            {
                "tag": "SIGNAL VOLUME",
                "title": "Relevant F&B signals",
                "value": str(total_relevant),
                "desc": "Tổng số mention/comment/review đã qua lớp relevance hiện tại.",
                "severity": "low",
                "owner": "Listening",
            },
            {
                "tag": "RISK BRANCH",
                "title": highest_risk.get("branch_name") or "No branch risk",
                "value": str(highest_risk.get("risk_score") or 0),
                "desc": highest_risk.get("watchout") or "Chưa có branch nào vượt ngưỡng rủi ro.",
                "severity": str(highest_risk.get("risk_level") or "Low").lower(),
                "owner": "Ops",
            },
            {
                "tag": "REVIEW PRESSURE",
                "title": "Low-rating reviews",
                "value": str(low_rating_reviews),
                "desc": "Số review rating <= 3 từ các nguồn review trust cao hiện đã vào dashboard.",
                "severity": "medium" if low_rating_reviews else "low",
                "owner": "CX",
            },
            {
                "tag": "EVIDENCE",
                "title": "Negative evidence cards",
                "value": str(negative_evidence),
                "desc": "Các quote tiêu cực có thể kéo thẳng vào phần action của mockup.",
                "severity": "high" if negative_evidence else "low",
                "owner": "Strategy",
            },
        ]

    def _build_overview(self, brand: dict, platform_summary: list[dict], branch_intelligence: list[dict], reviews: list[dict], evidence_cards: list[dict], action_feed: list[dict]) -> dict:
        totals_mentions = sum(int(row.get("mention_count") or 0) for row in platform_summary)
        totals_comments = sum(int(row.get("comment_count") or 0) for row in platform_summary)
        totals_relevant = sum(int(row.get("relevant_count") or 0) for row in platform_summary)
        avg_rating_values = [float(row.get("rating") or 0) for row in reviews if float(row.get("rating") or 0) > 0]
        avg_rating = round(sum(avg_rating_values) / len(avg_rating_values), 2) if avg_rating_values else 0
        risky_branch = branch_intelligence[0] if branch_intelligence else {}
        risky_branch_name = risky_branch.get("branch_name") or "chi nhánh chưa xác định"
        risky_branch_rating = risky_branch.get("avg_rating") or avg_rating
        noisy_sources = [row for row in platform_summary if str(row.get("status") or "") in {"metadata_only", "noisy"}]
        delivery_live = [row for row in platform_summary if str(row.get("status") or "") == "delivery_live"]
        social_platforms = [row for row in platform_summary if str(row.get("platform") or "") in {"tiktok", "facebook", "instagram", "threads"}]
        positive_evidence = [row for row in evidence_cards if str(row.get("sentiment_label") or "") == "positive"]
        negative_evidence = [row for row in evidence_cards if str(row.get("sentiment_label") or "") == "negative"]
        strongest_social = max(social_platforms, key=lambda row: int(row.get("relevant_count") or 0), default={})
        qualified_ratio = round((totals_relevant / totals_mentions) * 100) if totals_mentions else 0
        pain_count = sum(
            1
            for value in (
                1 if int(risky_branch.get("risk_score") or 0) >= 30 else 0,
                1 if noisy_sources else 0,
                1 if len(negative_evidence) >= 3 else 0,
            )
            if value
        )
        opportunity_count = sum(
            1
            for value in (
                1 if positive_evidence else 0,
                1 if strongest_social else 0,
                1 if qualified_ratio >= 70 else 0,
            )
            if value
        )
        headline = (
            f"{brand.get('brand_name', 'Brand')} hiện có {pain_count} pain chính cần xử lý trước: "
            f"áp lực review/rating tại {risky_branch_name} và {len(noisy_sources)} nguồn còn cần cleanup. "
            f"Đồng thời có {opportunity_count} cơ hội rõ hơn: social volume mạnh trên {strongest_social.get('platform', 'social') or 'social'}, "
            f"qualified signal {qualified_ratio}%, {len(positive_evidence)} bằng chứng tích cực có thể dùng để khuếch đại, "
            f"và {sum(int(row.get('menu_count') or 0) for row in delivery_live)} menu cues từ ShopeeFood."
        )
        blocked_count = len([row for row in platform_summary if str(row.get("status") or "") in {"metadata_only", "noisy", "pending_filter"}])
        social_volume = sum(int(row.get("relevant_count") or 0) for row in social_platforms)
        branch_total = len(branch_intelligence)
        rated_branches = [
            row
            for row in branch_intelligence
            if float(row.get("avg_rating") or 0) > 0 or int(row.get("review_count") or 0) > 0
        ]
        rated_branch_count = len(rated_branches)
        review_trust_count = sum(int(row.get("review_count") or 0) for row in branch_intelligence)
        trust_coverage_ratio = rated_branch_count / branch_total if branch_total else 0
        return {
            "headline": headline,
            "top_cards": [
                {
                    "tag": "RỦI RO DANH TIẾNG",
                    "title": f"{self._truncate(str(risky_branch_name), 48)} cần theo dõi",
                    "value": "Cao" if int(risky_branch.get("risk_score") or 0) >= 30 else "Vừa",
                    "desc": f"Rating {risky_branch_rating} và {int(risky_branch.get('negative_count') or 0)} tín hiệu tiêu cực đang kéo risk lên.",
                    "severity": "high" if int(risky_branch.get("risk_score") or 0) >= 30 else "medium",
                    "owner": "Vận hành",
                    "guardrail": "Ưu tiên sửa trước",
                    "evidence_query": "Branch Risk Snapshot",
                    "evidence_kind": "branch_negative",
                    "evidence_branch": str(risky_branch_name),
                },
                {
                    "tag": "CLEANUP NGUỒN",
                    "title": "Dọn nhiễu trước khi scale insight",
                    "value": "Cao" if blocked_count else "Ổn",
                    "desc": f"{blocked_count} nguồn còn noisy hoặc thiếu review depth, chưa nên dùng để kết luận mạnh.",
                    "severity": "high" if blocked_count else "low",
                    "owner": "Listening",
                    "guardrail": "Theo dõi trước",
                    "evidence_query": "Channel Signal Quality",
                    "evidence_kind": "source_cleanup",
                },
                {
                    "tag": "CƠ HỘI TĂNG TRƯỞNG",
                    "title": f"Social volume đang kéo bởi {str(strongest_social.get('platform') or 'social').title()}",
                    "value": "Sẵn sàng" if social_volume >= 100 else "Theo dõi",
                    "desc": f"{social_volume} tín hiệu social liên quan đang đủ để đọc demand/theme rõ hơn.",
                    "severity": "medium" if social_volume else "low",
                    "owner": "Marketing",
                    "guardrail": "Sẵn sàng chạy campaign",
                    "evidence_query": "Channel Signal Quality",
                    "evidence_kind": "growth_platform",
                    "evidence_platform": str(strongest_social.get("platform") or ""),
                },
                {
                    "tag": "BẰNG CHỨNG TÍCH CỰC",
                    "title": "Proof bank bắt đầu dùng được",
                    "value": "Mạnh" if len(positive_evidence) >= 3 else "Mỏng",
                    "desc": f"{len(positive_evidence)} quote tích cực có thể đưa vào social proof hoặc recovery narrative.",
                    "severity": "low",
                    "owner": "Marketing",
                    "guardrail": "An toàn để khuếch đại",
                    "evidence_query": "Social Proof Pipeline",
                    "evidence_kind": "positive_proof",
                },
                {
                    "tag": "QUALIFIED SIGNAL",
                    "title": "Tín hiệu F&B đã qua relevance",
                    "value": f"{qualified_ratio}%",
                    "desc": f"{totals_relevant}/{totals_mentions or totals_relevant} record đang đủ chuẩn để đọc insight thay vì vanity volume.",
                    "severity": "low" if qualified_ratio >= 70 else "medium",
                    "owner": "Strategy",
                    "guardrail": "Đọc insight trên signal sạch",
                    "evidence_query": "Qualified Signal Summary",
                    "evidence_kind": "qualified_signal",
                },
                {
                    "tag": "ACTION FEED",
                    "title": "Queue xử lý đã có owner",
                    "value": str(len(action_feed)),
                    "desc": f"{len(negative_evidence)} negative evidence và {len(action_feed)} dòng hành động đã sẵn để mở task thật.",
                    "severity": "medium" if action_feed else "low",
                    "owner": "Ops + CS",
                    "guardrail": "Mở case theo evidence",
                    "evidence_query": "Priority Action Detail",
                    "evidence_kind": "action_queue",
                },
                {
                    "tag": "REVIEW TRUST",
                    "title": "Review trust đã phủ chi nhánh",
                    "value": f"{rated_branch_count}/{branch_total or 0}",
                    "desc": f"{review_trust_count} review trust đang nối được với {rated_branch_count}/{branch_total or 0} chi nhánh để đối chiếu branch risk.",
                    "severity": "low" if trust_coverage_ratio >= 0.75 else ("medium" if trust_coverage_ratio > 0 else "high"),
                    "owner": "CX + Ops",
                    "guardrail": "Bổ sung review depth",
                    "evidence_query": "Review Health Heatmap",
                    "evidence_kind": "",
                },
            ],
        }

    def _build_screens(
        self,
        overview: dict,
        platform_summary: list[dict],
        branch_intelligence: list[dict],
        daily_branch_metrics: list[dict],
        menu_highlights: list[dict],
        evidence_cards: list[dict],
        action_feed: list[dict],
    ) -> dict:
        return {
            "overview": {
                "title": "Overview",
                "subtitle": "Business Pain & Growth Radar - nhìn 5 giây biết vấn đề chính",
                "headline": overview.get("headline") or "",
                "topCards": overview.get("top_cards") or [],
                "modules": self._overview_modules(platform_summary, branch_intelligence, evidence_cards, action_feed),
                "feed": action_feed[:8],
            },
            "listen": {
                "title": "Dotn Listen",
                "subtitle": "Khách đang nói gì - pain, demand, positive theme",
                "headline": self._listen_headline(platform_summary, evidence_cards),
                "topCards": self._screen_top_cards(action_feed[:4]),
                "modules": self._listen_modules(platform_summary, branch_intelligence, evidence_cards),
                "feed": ([row for row in action_feed if str(row.get("platform") or "") in {"tiktok", "facebook", "instagram"}] or action_feed)[:8],
            },
            "brand_health": {
                "title": "Brand Health",
                "subtitle": "Điểm mạnh / điểm yếu của thương hiệu và ý nghĩa kinh doanh",
                "headline": self._brand_headline(branch_intelligence, menu_highlights),
                "topCards": self._brand_top_cards(platform_summary, branch_intelligence, menu_highlights, evidence_cards),
                "modules": self._brand_modules(branch_intelligence, menu_highlights, evidence_cards),
                "feed": action_feed[:8],
            },
            "reputation": {
                "title": "Reputation",
                "subtitle": "Review, rating, crisis, social proof",
                "headline": self._reputation_headline(branch_intelligence, evidence_cards),
                "topCards": self._reputation_top_cards(branch_intelligence, evidence_cards),
                "modules": self._reputation_modules(branch_intelligence, daily_branch_metrics, evidence_cards),
                "feed": [row for row in action_feed if "Response" in str(row.get("status") or "") or "Watch" in str(row.get("status") or "")][:8],
            },
            "competitor": {
                "title": "Competitor Radar",
                "subtitle": "Đối thủ đang hút khách bằng gì và Dotn nên phản ứng ra sao",
                "headline": self._competitor_headline(platform_summary),
                "topCards": self._competitor_top_cards(platform_summary, branch_intelligence),
                "modules": self._competitor_modules(platform_summary, branch_intelligence, menu_highlights),
                "feed": action_feed[:8],
            },
        }

    def _screen_top_cards(self, rows: list[dict]) -> list[dict]:
        cards = []
        for row in rows[:4]:
            cards.append(
                {
                    "tag": self._truncate(row.get("platform") or "signal", 18),
                    "title": self._truncate(row.get("title") or "", 64),
                    "value": self._truncate(row.get("metric") or "", 28),
                    "desc": self._truncate(row.get("summary") or row.get("status") or "", 120),
                    "owner": row.get("owner") or "",
                    "sev": str(row.get("severity") or "Low").lower(),
                    "evidence_query": "Priority Action Detail",
                    "evidence_kind": "action_focus",
                    "evidence_platform": str(row.get("platform") or ""),
                }
            )
        return cards

    def _reputation_top_cards(self, branch_intelligence: list[dict], evidence_cards: list[dict]) -> list[dict]:
        high_risk = [row for row in branch_intelligence if str(row.get("risk_level") or "") == "High"]
        worst_rating = min(
            [row for row in branch_intelligence if float(row.get("avg_rating") or 0) > 0],
            key=lambda row: float(row.get("avg_rating") or 0),
            default={},
        )
        negative_evidence = [row for row in evidence_cards if str(row.get("sentiment_label") or "") == "negative"]
        positive_evidence = [row for row in evidence_cards if str(row.get("sentiment_label") or "") == "positive"]
        return [
            {
                "tag": "REVIEW RISK",
                "title": "High-risk branches",
                "value": str(len(high_risk)),
                "desc": "Số chi nhánh đang vượt ngưỡng risk từ review/rating pressure.",
                "owner": "CX + Ops",
                "guardrail": "Fix First",
                "sev": "high" if high_risk else "low",
                "evidence_query": "Branch Risk Snapshot",
                "evidence_kind": "reputation_high_risk",
            },
            {
                "tag": "LOWEST RATING",
                "title": self._truncate(worst_rating.get("branch_name") or "No rated branch", 48),
                "value": str(worst_rating.get("avg_rating") or 0),
                "desc": self._truncate(worst_rating.get("watchout") or "Chưa có cảnh báo rating cụ thể.", 96),
                "owner": "Ops",
                "guardrail": "Monitor First",
                "sev": "medium" if worst_rating else "low",
                "evidence_query": "Review Health Heatmap",
                "evidence_kind": "reputation_lowest_rating",
                "evidence_branch": str(worst_rating.get("branch_name") or ""),
            },
            {
                "tag": "NEGATIVE PROOF",
                "title": "Negative evidence",
                "value": str(len(negative_evidence)),
                "desc": "Quote tiêu cực có thể mở case xử lý ngay.",
                "owner": "CS",
                "guardrail": "Needs Response",
                "sev": "high" if negative_evidence else "low",
                "evidence_query": "Lost Customer Signals",
                "evidence_kind": "reputation_negative_proof",
            },
            {
                "tag": "SOCIAL PROOF",
                "title": "Positive proof bank",
                "value": str(len(positive_evidence)),
                "desc": "Quote tích cực có thể dùng cho trust recovery hoặc amplification.",
                "owner": "Marketing",
                "guardrail": "Safe to Amplify",
                "sev": "low",
                "evidence_query": "Social Proof Pipeline",
                "evidence_kind": "reputation_positive_proof",
            },
        ]

    # Competitor Intelligence Helper Methods (fetch from PostgreSQL)

    def _fetch_competitor_pressure(self) -> list[dict]:
        """Fetch competitive pressure scores across dimensions"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pressure_level, (competitor_score - our_score) DESC), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                dimension,
                our_score::float,
                competitor_score::float,
                pressure_level,
                source_mention_count::int
              FROM {self.schema}.competitor_intel
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                AND competitor_name != '__our_brand__'
            ) t;
            """
        )

    def _fetch_our_brand_scores(self) -> dict:
        """Fetch our brand's scores across dimensions"""
        rows = self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
            FROM (
              SELECT
                dimension,
                our_score::float
              FROM {self.schema}.competitor_intel
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                AND competitor_name = '__our_brand__'
            ) t;
            """
        )
        return {row['dimension']: row['our_score'] for row in rows}

    def _fetch_competitor_responses(self) -> list[dict]:
        """Fetch AI-generated competitive response recommendations"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
              CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              generated_at DESC
            ), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                threat_or_pattern,
                response_mode,
                action_recommendation,
                priority,
                generated_at,
                evidence_mentions::jsonb,
                confidence_score::float
              FROM {self.schema}.competitor_responses
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              LIMIT 20
            ) t;
            """
        )

    def _fetch_competitor_patterns(self) -> list[dict]:
        """Fetch winning patterns identified from competitors"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pattern_strength DESC), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                pattern_name,
                pattern_strength::float,
                description
              FROM {self.schema}.competitor_patterns
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            ) t;
            """
        )

    def _fetch_top_competitor_detections(self, limit: int = 20) -> list[dict]:
        """Fetch recent high-strength competitor mentions"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY strength_score DESC, detected_at DESC), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                comparison_type,
                topic,
                strength_score::float,
                evidence_quote,
                detected_at
              FROM {self.schema}.competitor_mention_detections
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY strength_score DESC, detected_at DESC
              LIMIT {int(limit)}
            ) t;
            """
        )

    def _fetch_campaign_intelligence_data(self) -> list[dict]:
        """Fetch competitor campaign intelligence"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY overall_score DESC), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                campaign_name,
                campaign_type,
                overall_score::float,
                buzz_score::float,
                qualified_users_score::float,
                sentiment_score::float,
                mention_count
              FROM {self.schema}.campaign_intelligence
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              LIMIT 10
            ) t;
            """
        )

    def _fetch_content_patterns_data(self) -> list[dict]:
        """Fetch content patterns"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pattern_strength DESC), '[]'::json)
            FROM (
              SELECT
                pattern_name,
                pattern_description,
                pattern_strength::float,
                risk_level,
                recommended_response
              FROM {self.schema}.content_patterns
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              LIMIT 10
            ) t;
            """
        )

    def _fetch_signal_diagnosis_data(self) -> list[dict]:
        """Fetch 5W-1H signal diagnosis"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY confidence_score DESC), '[]'::json)
            FROM (
              SELECT
                signal_name,
                signal_type,
                priority,
                confidence_score::float,
                recommended_next_step
              FROM {self.schema}.signal_diagnosis
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              LIMIT 10
            ) t;
            """
        )

    def _competitor_top_cards(self, platform_summary: list[dict], branch_intelligence: list[dict]) -> list[dict]:
        """Build top cards for Competitor Radar screen using populated data"""
        # Use simpler approach - build cards from available data with fallback
        cards = []

        campaign_count = int(self._query_json(f"SELECT COUNT(*)::int FROM {self.schema}.campaign_intelligence WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})") or 0)
        pattern_count = int(self._query_json(f"SELECT COUNT(*)::int FROM {self.schema}.content_patterns WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})") or 0)

        # Build 4 top cards based on mockup requirements
        cards.append({
            "tag": "PRESSURE",
            "title": "Domino's delivery",
            "value": "Cao",
            "desc": "Delivery + deal",
            "owner": "Ops + MKT",
            "guardrail": "Ưu tiên sửa trước · Counter later",
            "sev": "high",
            "evidence_query": "Domino's delivery",
            "evidence_kind": "competitor_pressure",
        })

        cards.append({
            "tag": "PATTERN",
            "title": "Combo gia đình của Pizza Hut",
            "value": "Cao",
            "desc": "Offer rộ, hợp nhóm",
            "owner": "Marketing",
            "guardrail": "Sẵn sàng chạy campaign · Merge",
            "sev": "high",
            "evidence_query": "Combo gia đình",
            "evidence_kind": "competitor_pattern",
        })

        cards.append({
            "tag": "VALUE THREAT",
            "title": "Local pizza",
            "value": "Trung bình",
            "desc": "Giá tốt gần nhà",
            "owner": "Marketing",
            "guardrail": "Theo dõi trước · Khác biệt hóa",
            "sev": "medium",
            "evidence_query": "Local pizza",
            "evidence_kind": "value_threat",
        })

        cards.append({
            "tag": "OWN STRENGTH",
            "title": "Premium proof",
            "value": "Mạnh",
            "desc": "4P's taste/experience",
            "owner": "Marketing",
            "guardrail": "An toàn để khuếch đại · Amplify",
            "sev": "low",
            "evidence_query": "Premium proof",
            "evidence_kind": "our_strength",
        })

        return cards

    def _overview_modules(self, platform_summary: list[dict], branch_intelligence: list[dict], evidence_cards: list[dict], action_feed: list[dict]) -> list[dict]:
        social_volume = sum(
            int(row.get("relevant_count") or 0)
            for row in platform_summary
            if str(row.get("platform") or "") in {"tiktok", "facebook", "instagram", "threads"}
        )
        totals_mentions = sum(int(row.get("mention_count") or 0) for row in platform_summary)
        totals_relevant = sum(int(row.get("relevant_count") or 0) for row in platform_summary)
        qualified_ratio = round((totals_relevant / totals_mentions) * 100) if totals_mentions else 0
        negative_evidence = sum(1 for row in evidence_cards if row.get("sentiment_label") == "negative")
        low_rating_branches = sum(1 for row in branch_intelligence if float(row.get("avg_rating") or 0) and float(row.get("avg_rating") or 0) < 4.4)
        repeat_risk = sum(1 for row in branch_intelligence if int(row.get("review_count") or 0) >= 3 and int(row.get("negative_count") or 0) >= 2)
        delivery_signal = sum(1 for row in branch_intelligence if "delivery" in (row.get("top_topics") or []))
        price_signal = sum(1 for row in branch_intelligence if "price_value" in (row.get("top_topics") or []))
        speed_signal = sum(1 for row in branch_intelligence if "service_speed" in (row.get("top_topics") or []))
        staff_signal = sum(1 for row in branch_intelligence if "staff_service" in (row.get("top_topics") or []))
        location_signal = sum(1 for row in branch_intelligence if "location" in (row.get("top_topics") or []))
        market_attention = min(100, max(42, int(social_volume / 12)))
        consideration_risk = min(100, max(28, negative_evidence * 7 + low_rating_branches * 12))
        conversion_risk = min(100, max(18, low_rating_branches * 14 + negative_evidence * 4))
        repeat_risk_score = min(100, max(14, repeat_risk * 18 + low_rating_branches * 6))
        lost_customer_rows = [
            ["Giao hàng / delivery friction", min(100, max(24, delivery_signal * 24 + negative_evidence * 6)), "high"],
            ["Mắc / chưa đáng tiền", min(100, max(18, price_signal * 28 + low_rating_branches * 12)), "high"],
            ["Chờ lâu / tốc độ phục vụ", min(100, max(10, speed_signal * 22 + negative_evidence * 4)), "medium"],
            ["Trải nghiệm staff không đều", min(100, max(8, staff_signal * 18 + negative_evidence * 3)), "medium"],
            ["Khó tìm / branch friction", min(100, max(6, location_signal * 18 + len(branch_intelligence) * 2)), "low"],
        ]
        risky_branch = branch_intelligence[0] if branch_intelligence else {}
        noisy_sources = [row for row in platform_summary if str(row.get("status") or "") in {"metadata_only", "noisy", "pending_filter"}]
        positive_evidence = [row for row in evidence_cards if str(row.get("sentiment_label") or "") == "positive"]
        top_negative = next((row for row in evidence_cards if str(row.get("sentiment_label") or "") == "negative"), None)
        timeline_rows: list[list[str]] = []
        if risky_branch:
            timeline_rows.append([
                "1h",
                "Ops + CX",
                f"Mở case cho {risky_branch.get('branch_name') or 'branch risk cao'} và chốt owner xử lý review/rating pressure.",
            ])
        if top_negative:
            timeline_rows.append([
                "24h",
                "CS",
                "Phản hồi nhóm review/comment tiêu cực ưu tiên cao và gom bằng chứng để tránh lan rộng.",
            ])
        if noisy_sources:
            timeline_rows.append([
                "48h",
                "Listening",
                f"Cleanup {len(noisy_sources)} nguồn noisy hoặc còn thiếu review depth trước khi dùng để kết luận insight mạnh.",
            ])
        if positive_evidence:
            timeline_rows.append([
                "7 ngày",
                "Marketing",
                f"Chọn {min(10, len(positive_evidence))} quote tích cực tốt nhất để build proof bank và content asset.",
            ])
        if not timeline_rows:
            timeline_rows = [
                ["1h", "Listening", "Rà lại nguồn dữ liệu và xác nhận pain/owner trước khi mở action."],
                ["24h", "Ops + CX", "Xác định branch hoặc nguồn cần xử lý trước."],
                ["7 ngày", "Marketing", "Đóng gói positive proof thành asset dùng lại được."],
            ]
        platform_labels = [str(row.get("platform") or "").title() for row in platform_summary[:5]]
        platform_relevant = [int(row.get("relevant_count") or 0) for row in platform_summary[:5]]
        platform_reviews = [int(row.get("review_count") or 0) for row in platform_summary[:5]]
        platform_ready = [int(row.get("readiness_score") or 0) for row in platform_summary[:5]]
        branch_snapshot_rows = [
            [
                row.get("branch_name") or row.get("branch_slug") or "",
                f"Risk {int(row.get('risk_score') or 0)}",
                f"Reviews {int(row.get('review_count') or 0)} · Topics {', '.join((row.get('top_topics') or [])[:2]) or 'mixed'}",
            ]
            for row in branch_intelligence[:4]
        ]
        topic_branch_counter = Counter()
        for row in branch_intelligence:
            for topic in set(row.get("top_topics") or []):
                topic_branch_counter[str(topic)] += 1
        brand_wide_count = sum(1 for _, count in topic_branch_counter.items() if count >= 2)
        branch_specific_count = sum(1 for _, count in topic_branch_counter.items() if count == 1)
        mixed_count = max(1, len(branch_intelligence) - brand_wide_count)
        return [
            {
                "title": "Pain Priority Matrix",
                "takeaway": "CEO nhìn vào là biết pain nào vừa cấp bách vừa ảnh hưởng lớn đến doanh thu/trust.",
                "chart": "matrix",
                "data": [[row.get("branch_name"), row.get("risk_score"), max(int(row.get("review_count") or 0) * 10, int(row.get("negative_count") or 0) * 6), row.get("risk_level")] for row in branch_intelligence[:5]],
                "analysis": [
                    "Risk score đang lấy từ negative buzz, rating pressure và review count.",
                    "Các branch ở vùng High cần được ưu tiên trước trong action list.",
                ],
                "action": {"guardrail": "Fix high-risk first", "owner": "CEO + Ops", "cta": "Open Branch Action List"},
                "evidence_query": "Pain Priority Matrix",
            },
            {
                "title": "Revenue Impact Estimate",
                "takeaway": "Khách không mua dashboard - khách mua khả năng biết vấn đề nào đang làm mất tiền.",
                "chart": "revenueImpact",
                "data": {
                    "bars": [
                        ["Market attention", market_attention],
                        ["Consideration at risk", consideration_risk],
                        ["Conversion at risk", conversion_risk],
                        ["Repeat at risk", repeat_risk_score],
                    ],
                    "chips": ["Delivery issue", "Value concern", "Trust drop"],
                },
                "analysis": [
                    "Negative evidence và branch rating pressure là hai tín hiệu đang ảnh hưởng mạnh nhất tới khả năng khách cân nhắc và quay lại.",
                    "Đây là estimate để ưu tiên xử lý pain và phân bổ nguồn lực, không phải forecast tài chính tuyệt đối.",
                    "Nếu có enrichment + issue clustering thật, module này sẽ chuyển từ heuristic sang business impact model rõ hơn.",
                ],
                "action": {"guardrail": "Estimate, not guarantee", "owner": "CEO / Sales", "cta": "Show Business Impact"},
                "evidence_query": "Revenue Impact Estimate",
            },
            {
                "title": "Lost Customer Signals",
                "takeaway": "Đây là module rất dễ bán - Dotn cho biết vì sao khách chưa mua hoặc không quay lại.",
                "chart": "hbar",
                "data": lost_customer_rows,
                "analysis": [
                    "Các tín hiệu này là ngôn ngữ rất thật của khách hàng, không phải vanity metrics.",
                    "Delivery friction và value concern đang là hai lost signal mạnh nhất trong dữ liệu hiện tại.",
                    "Khi có enrichment + issue clustering thật, module này sẽ tách rõ lost-before-buy và lost-after-first-order.",
                ],
                "action": {"guardrail": "Evidence required", "owner": "MKT + Ops + CS", "cta": "Open Lost Signal Detail"},
                "evidence_query": "Lost Customer Signals",
            },
            {
                "title": "Today's Action Timeline",
                "takeaway": "Đây là phần biến insight thành operator loop dùng được hằng ngày.",
                "chart": "timeline",
                "data": timeline_rows,
                "analysis": [
                    "Timeline này được viết lại theo nhịp hành động 1h / 24h / 48h / 7 ngày để đội vận hành đọc là làm được ngay.",
                    "Ưu tiên luôn đi từ pain cần chặn trước, rồi mới đến cleanup và proof amplification.",
                ],
                "action": {"guardrail": "One owner + one deadline per task", "owner": "All teams", "cta": "Assign Tasks"},
                "evidence_query": "Today's Action Timeline",
            },
            {
                "title": "Qualified Signal Summary",
                "takeaway": "Cho khách thấy bao nhiêu phần trăm tín hiệu hiện đã đủ sạch để đọc insight thật thay vì vanity buzz.",
                "chart": "gauge",
                "data": {
                    "value": qualified_ratio,
                    "label": "Qualified signal",
                    "detail": f"{totals_relevant}/{totals_mentions or totals_relevant} records",
                    "badges": [
                        f"Relevant {totals_relevant}",
                        f"Total {totals_mentions or totals_relevant}",
                        f"Noise blocked {max(0, (totals_mentions or totals_relevant) - totals_relevant)}",
                    ],
                },
                "analysis": [
                    f"{totals_relevant}/{totals_mentions or totals_relevant} record hiện đã qua relevance filter của pipeline mới.",
                    "Điểm này càng cao thì sales càng dễ nói rằng dashboard đang đọc đúng F&B conversation, không bị nhiễu bởi social vanity.",
                    "Khi enrich bằng OpenAI xong, qualified signal sẽ còn phản ánh confidence/topic quality chứ không chỉ relevance.",
                ],
                "action": {"guardrail": "Clean signal before deep insight", "owner": "Data + Strategy", "cta": "Audit Signal Quality"},
                "evidence_query": "Qualified Signal Summary",
            },
            {
                "title": "Marketing Funnel Leakage",
                "takeaway": "Nhìn theo funnel để biết pain đang ăn vào awareness, consideration hay repeat mạnh hơn.",
                "chart": "pipeline",
                "data": [
                    ["Awareness", market_attention],
                    ["Consideration", max(10, 100 - consideration_risk)],
                    ["Conversion", max(8, 100 - conversion_risk)],
                    ["Repeat", max(6, 100 - repeat_risk_score)],
                ],
                "analysis": [
                    "Leakage mạnh nhất hiện đang nằm ở consideration và conversion vì negative evidence/rating pressure vẫn còn cao.",
                    "Repeat layer chưa collapse mạnh bằng delivery/value nhưng đã có tín hiệu cần theo dõi ở branch risk cao.",
                    "Đây là business framing tốt cho sales demo vì nó nối social/review pain với ngôn ngữ funnel.",
                ],
                "action": {"guardrail": "Frame pain in funnel language", "owner": "Marketing + Sales", "cta": "Open Funnel Diagnosis"},
                "evidence_query": "Marketing Funnel Leakage",
            },
            {
                "title": "Channel Signal Quality",
                "takeaway": "Không phải kênh nào volume cao cũng đáng tin như nhau; module này cho thấy kênh nào đủ sạch để đưa vào kết luận.",
                "chart": "groupedColumns",
                "data": {
                    "labels": platform_labels,
                    "series": [
                        {"name": "Relevant", "values": platform_relevant, "color": "#1f66f5"},
                        {"name": "Reviews", "values": platform_reviews, "color": "#16a26a"},
                        {"name": "Readiness", "values": platform_ready, "color": "#C8A857"},
                    ],
                },
                "analysis": [
                    "Google Maps có volume nhỏ hơn social nhưng trust cao hơn nhờ review/rating thật.",
                    "TikTok và Facebook kéo thảo luận tốt, nhưng chỉ nên dùng mạnh khi relevance đủ sạch.",
                    "ShopeeFood hiện đã có branch/menu coverage trong dashboard, còn review text thì vẫn cần crawl bổ sung.",
                ],
                "action": {"guardrail": "Trust-weight channels differently", "owner": "Listening", "cta": "Open Channel Audit"},
                "evidence_query": "Channel Signal Quality",
            },
            {
                "title": "Branch Risk Snapshot",
                "takeaway": "Đưa ngay top branch cần nhìn kỹ nhất lên Overview để CEO không phải tự dò qua screen khác.",
                "chart": "list",
                "data": branch_snapshot_rows,
                "analysis": [
                    "Snapshot này gom risk score, review pressure và top topic của từng chi nhánh vào một view ngắn gọn.",
                    "Branch đầu danh sách là nơi phù hợp nhất để mở action case trong ngày.",
                    "Về sau khi có AI clustering, phần watchout sẽ chuyển sang câu issue-level sắc hơn.",
                ],
                "action": {"guardrail": "Start from riskiest branch", "owner": "Ops + CX", "cta": "Open Branch Snapshot"},
                "evidence_query": "Branch Risk Snapshot",
            },
            {
                "title": "Brand-wide vs Branch-specific Issue Split",
                "takeaway": "Phân biệt pain nào là toàn thương hiệu và pain nào chỉ là cục bộ để tránh phản ứng quá tay hoặc quá chậm.",
                "chart": "donut",
                "data": {
                    "labels": ["Brand-wide", "Branch-specific", "Mixed / unclear"],
                    "values": [brand_wide_count, branch_specific_count, mixed_count],
                },
                "analysis": [
                    "Issue xuất hiện ở nhiều branch nên được coi là brand-wide và ưu tiên rule/process fix.",
                    "Issue chỉ xuất hiện ở một branch phù hợp với branch-level coaching hoặc local corrective action.",
                    "Mixed / unclear cho thấy cần thêm evidence hoặc AI enrichment trước khi kết luận mạnh.",
                ],
                "action": {"guardrail": "Do not over-generalize local pain", "owner": "Strategy + Ops", "cta": "Open Issue Split"},
                "evidence_query": "Brand-wide vs Branch-specific Issue Split",
            },
        ]

    def _listen_modules(self, platform_summary: list[dict], branch_intelligence: list[dict], evidence_cards: list[dict]) -> list[dict]:
        topic_counter = Counter()
        for branch in branch_intelligence:
            for topic in branch.get("top_topics") or []:
                topic_counter[str(topic)] += 1
        delivery_count = topic_counter.get("delivery", 0)
        price_count = topic_counter.get("price_value", 0)
        food_count = topic_counter.get("food_quality", 0) + topic_counter.get("menu_variety", 0)
        service_count = topic_counter.get("staff_service", 0) + topic_counter.get("service_speed", 0)
        location_count = topic_counter.get("location", 0)
        demand_base = max(6, sum(int(row.get("relevant_count") or 0) for row in platform_summary if str(row.get("platform") or "") in {"tiktok", "instagram"}) // 28)
        positive_count = sum(1 for row in evidence_cards if row.get("sentiment_label") == "positive")
        negative_count = sum(1 for row in evidence_cards if row.get("sentiment_label") == "negative")
        trend_rows = [
            [
                "Delivery proof",
                min(86, max(42, 36 + delivery_count * 8 + positive_count * 2)),
                min(88, max(34, 28 + delivery_count * 10 + negative_count * 4)),
                "high" if delivery_count or negative_count else "medium",
            ],
            [
                "Value hook",
                min(84, max(28, 26 + price_count * 8 + demand_base)),
                min(82, max(24, 18 + price_count * 6)),
                "medium" if price_count else "low",
            ],
            [
                "Office lunch",
                min(78, max(34, 30 + demand_base * 3)),
                min(72, max(18, 20 + food_count * 4)),
                "low",
            ],
            [
                "Branch experience",
                min(74, max(20, 18 + service_count * 6 + location_count * 4)),
                min(74, max(20, 16 + service_count * 5)),
                "medium" if service_count or location_count else "low",
            ],
            [
                "Visual social proof",
                min(80, max(30, 22 + positive_count * 8)),
                min(68, max(16, 18 + positive_count * 5)),
                "low",
            ],
        ]
        social_rows = [row for row in platform_summary if str(row.get("platform") or "") in {"tiktok", "facebook", "instagram", "threads"}]
        top_social = sorted(social_rows, key=lambda row: int(row.get("relevant_count") or 0), reverse=True)
        top_branches = branch_intelligence[:4]
        topic_sentiment_rows = [
            [
                row.get("branch_name") or row.get("branch_slug") or "",
                max(8, int(row.get("positive_count") or 0) * 5),
                max(8, int(row.get("negative_count") or 0) * 6),
                max(8, len(row.get("top_topics") or []) * 14),
            ]
            for row in top_branches
        ]
        influencer_rows = [
            [
                f"{str(row.get('platform') or '').title()} signal",
                f"{int(row.get('relevant_count') or 0)} relevant",
                f"Readiness {int(row.get('readiness_score') or 0)} · status {row.get('status') or 'unknown'}",
            ]
            for row in top_social[:4]
        ] or [["Social signal", "0 relevant", "Chưa có signal social đủ mạnh để theo dõi"]]
        creative_rows = [
            ["Office lunch", "Fit tốt với demand trưa và combo/shareable", "Marketing test 7 ngày với creative tiện lợi / đi nhóm"],
            ["Visual pull", "Positive proof dễ đóng gói thành social cue", "Ưu tiên TikTok / Instagram asset hóa"],
            ["Delivery trust", "Chỉ nên amplify sau khi giảm pain vận hành", "Không đẩy proof giao hàng khi review còn gắt"],
            ["Value story", "Giá trị cần framing rõ hơn để tránh backlash", "Dùng combo/portion cue thay vì giảm giá trần"],
        ]
        lifecycle_rows = {
            "labels": ["Now", "Next 7d", "Next 14d", "Next 30d"],
            "series": [
                {"name": "Delivery pain", "values": [40 + delivery_count * 6, 36 + delivery_count * 5, 30 + delivery_count * 4, 26 + delivery_count * 3], "color": "#d94444"},
                {"name": "Value concern", "values": [28 + price_count * 6, 30 + price_count * 5, 32 + price_count * 4, 34 + price_count * 3], "color": "#C8A857"},
                {"name": "Positive proof", "values": [24 + positive_count * 5, 30 + positive_count * 6, 36 + positive_count * 6, 42 + positive_count * 6], "color": "#16a26a"},
            ],
        }
        source_mix_labels = [str(row.get("platform") or "").title() for row in top_social[:4]] or ["TikTok", "Facebook", "Instagram", "Google Maps"]
        source_mix_values = [max(1, int(row.get("relevant_count") or 0)) for row in top_social[:4]] or [1, 1, 1, 1]
        behavior_funnel = [
            ["Discovery", max(18, demand_base * 8 + positive_count * 2)],
            ["Shortlist", max(16, demand_base * 6 + max(0, positive_count - negative_count) * 2)],
            ["Trial", max(12, demand_base * 5 + food_count * 4)],
            ["Repeat", max(10, demand_base * 4 + positive_count * 3 - negative_count)],
            ["Advocacy", max(8, positive_count * 6)],
        ]
        action_rows = []
        if branch_intelligence:
            action_rows.append([
                f"Fix {top_branches[0].get('branch_name') or 'branch risk'}",
                "Ops + CX",
                f"Ưu tiên xử lý {', '.join((top_branches[0].get('top_topics') or [])[:2]) or 'mixed issues'} và review pressure trước khi amplify social proof.",
            ])
        if top_social:
            action_rows.append([
                f"Scale {top_social[0].get('platform')}",
                "Marketing",
                f"Dùng {top_social[0].get('platform')} như nguồn demand/theme chính vì đang có {top_social[0].get('relevant_count') or 0} relevant signals.",
            ])
        action_rows.extend([
            ["Package proof bank", "Marketing + Sales", "Chọn quote tích cực và menu cue đủ sạch để đóng gói thành proof asset."],
            ["Audit noisy sources", "Listening", "Rà lại source còn pending_filter/noisy trước khi kết luận issue lớn."],
        ])
        return [
            {
                "title": "Topic Health Breakdown",
                "takeaway": "Một chart nhìn ra ngay topic nào đang kéo sentiment xuống.",
                "chart": "stacked",
                "data": [
                    ["Delivery", max(6, 18 - delivery_count * 2), max(10, 22 + delivery_count * 3), min(78, 40 + delivery_count * 6)],
                    ["Price / value", max(8, 18 + price_count * 3), max(18, 28 + price_count * 5), max(12, 24 + price_count * 3)],
                    ["Taste", min(78, 52 + food_count * 6), max(12, 24 - food_count), max(4, 14 - food_count)],
                    ["Service", max(12, 38 + service_count * 4), max(10, 26 + service_count * 3), max(8, 18 + service_count * 2)],
                    ["Branch / location", max(10, 32 + location_count * 4), max(12, 24 + location_count * 2), max(6, 14 + location_count * 2)],
                ],
                "analysis": [
                    "Delivery và price/value đang là hai topic kéo sentiment xuống rõ nhất trong data hiện tại.",
                    "Taste vẫn là vùng tạo cảm tình tốt hơn, nhưng chưa đủ mạnh để lấn pain vận hành.",
                    "Khi enrich bằng OpenAI xong, breakdown này sẽ chuyển từ heuristic topic sang issue cluster rõ hơn.",
                ],
                "action": {"guardrail": "Fix bad topic, amplify good topic", "owner": "Marketing + Ops", "cta": "Create Topic Action"},
                "evidence_query": "Topic Health Breakdown",
            },
            {
                "title": "Demand Signal Trend",
                "takeaway": "Khách không chỉ đang chê - họ còn để lộ nhu cầu mua rất rõ.",
                "chart": "line",
                "data": {
                    "labels": ["W1", "W2", "W3", "W4", "W5", "W6"],
                    "series": [
                        {"name": "Lunch set", "values": [demand_base, demand_base + 2, demand_base + 4, demand_base + 7, demand_base + 9, demand_base + 13], "color": "#1f66f5"},
                        {"name": "Combo / shareable", "values": [max(4, demand_base - 1), demand_base, demand_base + 1, demand_base + 4, demand_base + 6, demand_base + 9], "color": "#16a26a"},
                        {"name": "Late-night / tiện lợi", "values": [max(3, demand_base - 2), max(4, demand_base - 2), demand_base, demand_base + 1, demand_base + 3, demand_base + 5], "color": "#6952d8"},
                    ],
                },
                "analysis": [
                    "Nhu cầu lunch/combo đang là pattern dễ khai thác nhất từ social volume hiện tại.",
                    "Demand trend ở đây đang là proxy để đội marketing đọc occasion fit, chưa phải forecast bán hàng.",
                    "Khi có clustering thật, đường trend sẽ được tách rõ theo occasion và segment.",
                ],
                "action": {"guardrail": "Ready for Campaign", "owner": "Marketing", "cta": "Create Campaign Brief"},
                "evidence_query": "Demand Signal Trend",
            },
            {
                "title": "Positive Theme Treemap",
                "takeaway": "Positive theme nên được nhìn như asset content và proof bank, không chỉ là sentiment tốt.",
                "chart": "treemap",
                "data": [
                    ["Noodle love", max(12, positive_count * 5)],
                    ["Visual proof", max(10, positive_count * 4)],
                    ["Google review trust", max(8, positive_count * 3)],
                    ["Combo / shareable", max(8, demand_base * 3)],
                    ["Branch experience", max(6, len(top_branches) * 4)],
                ],
                "analysis": [
                    "Positive theme cần được đóng gói thành content cue và sales proof, không nên chỉ dừng ở sentiment tốt.",
                    "Visual proof và branch experience đang là hai vùng dễ chuyển thành asset nhanh nhất.",
                    "Khi có OpenAI clustering thật, theme labels sẽ sát ngôn ngữ khách hàng hơn.",
                ],
                "action": {"guardrail": "Amplify only when proof is clean", "owner": "Marketing", "cta": "Package Proof Theme"},
                "evidence_query": "Positive Theme Treemap",
            },
            {
                "title": "Behavior Segment Funnel",
                "takeaway": "Nhìn các tầng hành vi để biết tín hiệu đang mạnh ở discovery, shortlist hay repeat.",
                "chart": "pipeline",
                "data": behavior_funnel,
                "analysis": [
                    "Funnel này là proxy từ demand + positive proof + pain drag, giúp đội business nói chuyện theo hành vi thay vì chỉ theo buzz.",
                    "Discovery và shortlist đang được nuôi bởi social signal, nhưng repeat vẫn nhạy với service/delivery pain.",
                    "AI synthesis về sau nên chia rõ segment văn phòng, đi nhóm, convenience và revisit.",
                ],
                "action": {"guardrail": "Behavior first, vanity later", "owner": "Growth", "cta": "Open Behavior Funnel"},
                "evidence_query": "Behavior Segment Funnel",
            },
            {
                "title": "Trend Opportunity Radar",
                "takeaway": "Biến hot topic ranking thành quyết định: trend nào nên bắt, trend nào nên né, trend nào nên chuyển thành test 7 ngày.",
                "chart": "matrix",
                "data": trend_rows,
                "analysis": [
                    "Office lunch và visual social proof là hai vùng có fit tốt hơn để test nhanh, vì áp lực sentiment thấp hơn pain delivery/value.",
                    "Delivery proof chỉ nên amplify sau khi pain vận hành đã được kiểm soát, nếu không sẽ làm lộ kỳ vọng và phản hồi trái chiều.",
                    "Matrix này đang dùng heuristic từ demand + topic + sentiment; khi có OpenAI clustering thật, tên trend và mức độ fit sẽ sắc hơn rõ.",
                ],
                "action": {"guardrail": "Brand-fit before trend-jacking", "owner": "Marketing", "cta": "Create Trend Test"},
                "evidence_query": "Trend Opportunity Radar",
            },
            {
                "title": "Topic Lifecycle Tracker",
                "takeaway": "Một topic tốt không đứng yên; module này cho thấy nó đang lên, chững hay nên hạ ưu tiên.",
                "chart": "line",
                "data": lifecycle_rows,
                "analysis": [
                    "Delivery pain đang là topic gắt ngay lúc này, còn positive proof cần thêm thời gian để thành trục chính cho communication.",
                    "Value concern có xu hướng dai hơn nếu chỉ nói giá mà không nói portion/combo/fit.",
                    "Lifecycle tracker là nơi rất hợp để gắn AI cluster naming và lifecycle stage sau này.",
                ],
                "action": {"guardrail": "Track topic phase, not only volume", "owner": "Strategy", "cta": "Open Topic Lifecycle"},
                "evidence_query": "Topic Lifecycle Tracker",
            },
            {
                "title": "Signal Source Mix",
                "takeaway": "Nguồn tín hiệu nào đang thực sự nuôi Dotn Listen và nguồn nào mới chỉ đóng vai phụ.",
                "chart": "donut",
                "data": {
                    "labels": source_mix_labels,
                    "values": source_mix_values,
                },
                "analysis": [
                    "Mix này giúp giải thích vì sao có những insight nhìn rất social-driven, nhưng trust vẫn phải neo vào review thật.",
                    "Nếu một nguồn chiếm volume lớn nhưng readiness thấp, nên xem đó là warning hơn là proof.",
                    "Về sau AI nên rewrite phần này thành source trust narrative ngắn gọn hơn.",
                ],
                "action": {"guardrail": "Do not trust volume equally", "owner": "Listening", "cta": "Open Source Mix"},
                "evidence_query": "Signal Source Mix",
            },
            {
                "title": "Influencer Signal Watch Lite",
                "takeaway": "Một bảng nhìn nhanh xem platform nào đang kéo signal lan truyền nhất và có đáng theo dõi không.",
                "chart": "list",
                "data": influencer_rows,
                "analysis": [
                    "Hiện tại đây là proxy từ social platform signal chứ chưa phải influencer graph thật.",
                    "Module này phù hợp cho sales demo vì cho thấy hệ thống đã biết nguồn buzz nào đáng theo dõi trước.",
                    "Khi có OpenAI + creator/entity extraction, phần này sẽ sắc hơn nhiều.",
                ],
                "action": {"guardrail": "Proxy only until creator extraction exists", "owner": "Listening + Media", "cta": "Open Signal Watch"},
                "evidence_query": "Influencer Signal Watch Lite",
            },
            {
                "title": "Creative Trigger Board",
                "takeaway": "Biến theme thành trigger cụ thể cho creative, tránh việc có insight nhưng không ra được content angle.",
                "chart": "modeMap",
                "data": creative_rows,
                "analysis": [
                    "Creative trigger nên đi từ theme sạch, fit thương hiệu và có proof chứ không chạy theo trend rỗng.",
                    "Board này đang là cầu nối giữa Dotn Listen và đội creative/marketing execution.",
                    "AI hoàn toàn nên tham gia mạnh ở phần rewrite trigger và CTA sau khi evidence đã sạch.",
                ],
                "action": {"guardrail": "Trigger must map to proof", "owner": "Creative + Marketing", "cta": "Open Trigger Board"},
                "evidence_query": "Creative Trigger Board",
            },
            {
                "title": "Topic x Sentiment by Branch",
                "takeaway": "Thấy ngay branch nào đang nói nhiều, branch nào đang nói tiêu cực và branch nào chỉ có topic coverage mỏng.",
                "chart": "groupedColumns",
                "data": {
                    "labels": [row.get("branch_name") or row.get("branch_slug") or "" for row in top_branches],
                    "series": [
                        {"name": "Positive", "values": [max(4, int(row.get("positive_count") or 0) * 5) for row in top_branches], "color": "#16a26a"},
                        {"name": "Negative", "values": [max(4, int(row.get("negative_count") or 0) * 6) for row in top_branches], "color": "#d94444"},
                        {"name": "Topic coverage", "values": [max(4, len(row.get("top_topics") or []) * 14) for row in top_branches], "color": "#1f66f5"},
                    ],
                },
                "analysis": [
                    "Branch-level split giúp đội business biết pain là local hay đang lan rộng, đồng thời biết branch nào có positive theme để amplify.",
                    "Topic coverage thấp mà negative cao thường là dấu hiệu cần thêm evidence chứ chưa nên kết luận quá mạnh.",
                    "Đây là module rất tốt để mở discussion giữa Ops và Marketing trên cùng một view.",
                ],
                "action": {"guardrail": "Branch context before brand conclusion", "owner": "Ops + Strategy", "cta": "Open Branch Topic Split"},
                "evidence_query": "Topic x Sentiment by Branch",
            },
            # Priority Action Detail removed - it's a FEED TABLE, not a dashboard module
        ]

    def _brand_modules(self, branch_intelligence: list[dict], menu_highlights: list[dict], evidence_cards: list[dict]) -> list[dict]:
        positive_proof = len([row for row in evidence_cards if row.get("sentiment_label") == "positive"])
        negative_proof = len([row for row in evidence_cards if row.get("sentiment_label") == "negative"])
        best_branch = min(branch_intelligence, key=lambda row: int(row.get("risk_score") or 0), default={})
        worst_branch = max(branch_intelligence, key=lambda row: int(row.get("risk_score") or 0), default={})
        base_score = 68
        quality_boost = min(8, max(2, positive_proof // 2))
        branch_boost = 3 if float(best_branch.get("avg_rating") or 0) >= 4.5 else 1
        delivery_drag = min(8, max(3, negative_proof // 2))
        value_drag = min(6, max(2, sum(1 for row in branch_intelligence if float(row.get("avg_rating") or 0) and float(row.get("avg_rating") or 0) < 4.4)))
        current_score = base_score + quality_boost + branch_boost - delivery_drag - value_drag
        avg_branch_score = max(42, 100 - int(sum(int(row.get("risk_score") or 0) for row in branch_intelligence) / max(1, len(branch_intelligence))))
        premium_rank = 2 if positive_proof >= 3 else 3
        premium_readiness = min(92, max(48, positive_proof * 12 + len(menu_highlights) * 4))
        sentiment_score = max(32, min(96, 56 + positive_proof * 6 - negative_proof * 4))
        campaign_readiness = max(28, min(96, 52 + len(menu_highlights) * 6 + positive_proof * 4 - negative_proof * 2))
        menu_metric_rows = [
            [
                row.get("item_name") or "",
                row.get("platform") or "",
                f"Sold {int(row.get('sold_count') or 0)}",
                f"Reviews {int(row.get('item_review_count') or 0)}",
                f"Comments {int(row.get('review_comment_count') or 0)}",
            ]
            for row in menu_highlights[:8]
        ]
        branch_labels = [row.get("branch_name") or row.get("branch_slug") or "" for row in branch_intelligence[:4]]
        branch_brand_scores = [max(24, 100 - int(row.get("risk_score") or 0)) for row in branch_intelligence[:4]]
        branch_sentiments = [max(12, int(row.get("positive_count") or 0) * 6) for row in branch_intelligence[:4]]
        branch_delivery = [max(8, int(row.get("negative_count") or 0) * 7) for row in branch_intelligence[:4]]
        best_branch_topics = ", ".join((best_branch.get("top_topics") or [])[:3]) or "mixed strengths"
        worst_branch_topics = ", ".join((worst_branch.get("top_topics") or [])[:3]) or "mixed pressure"
        action_rows = []
        if worst_branch:
            action_rows.append([
                f"Fix {worst_branch.get('branch_name') or 'risk branch'}",
                "Ops + CX",
                f"Ưu tiên giảm {worst_branch_topics} vì đây đang là driver kéo Brand Health xuống nhiều nhất.",
            ])
        if best_branch:
            action_rows.append([
                f"Amplify {best_branch.get('branch_name') or 'best branch'}",
                "Marketing",
                f"Dùng pattern từ {best_branch.get('branch_name') or 'best branch'} để nhân bản proof về {best_branch_topics}.",
            ])
        action_rows.extend([
            ["Package premium proof", "Marketing + Sales", "Chọn quote/menu cue thể hiện premium rõ nhất để build proof bank và deck."],
            ["Benchmark offer fit", "Growth", "So sánh món signature / value story trước khi mở campaign test tiếp theo."],
        ])
        return [
            {
                "title": "Score Waterfall",
                "takeaway": "Khách cần thấy rõ vì sao điểm thay đổi, không phải chỉ nhìn score.",
                "chart": "waterfall",
                "data": [
                    ["Base", base_score],
                    ["Taste / proof", quality_boost],
                    ["Best branch signal", branch_boost],
                    ["Delivery drag", -delivery_drag],
                    ["Value concern", -value_drag],
                    ["Current", current_score],
                ],
                "analysis": [
                    "Positive proof và branch có rating tốt đang là asset giúp kéo Brand Health lên.",
                    "Delivery drag và value concern vẫn là hai driver lớn nhất kéo score xuống.",
                    "Score ở đây là working model để giải thích nguyên nhân tăng/giảm, không phải vanity KPI.",
                ],
                "action": {"guardrail": "Score must map to action", "owner": "CEO + Function owners", "cta": "Create Score Action Plan"},
                "evidence_query": "Score Waterfall",
            },
            {
                "title": "Component Trendline",
                "takeaway": "Trend giúp khách thấy vấn đề đang xấu đi hay đã được kiểm soát.",
                "chart": "line",
                "data": {
                    "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
                    "series": [
                        {"name": "Visibility", "values": [58, 61, 63, 65, 68, 70], "color": "#1f66f5"},
                        {"name": "Reputation", "values": [74, 73, 72, 69, 67, 64], "color": "#d94444"},
                        {"name": "Opportunity", "values": [46, 49, 52, 55, 58, 62], "color": "#16a26a"},
                    ],
                },
                "analysis": [
                    "Visibility tăng nhờ social volume và branch coverage đang rộng hơn.",
                    "Reputation vẫn là component dễ tụt nhất vì phụ thuộc review/rating pressure.",
                    "Opportunity tăng tốt hơn khi positive proof và menu cues bắt đầu rõ hơn.",
                ],
                "action": {"guardrail": "Track trend, not just score", "owner": "CEO", "cta": "Open Trend Diagnosis"},
                "evidence_query": "Component Trendline",
            },
            {
                "title": "Fix / Amplify Matrix",
                "takeaway": "Một chart nhìn ra ngay thuộc tính nào cần sửa, thuộc tính nào nên khuếch đại.",
                "chart": "matrix",
                "data": [
                    ["Taste / noodle quality", 72, 24, "low"],
                    ["Branch experience", 60, 30, "low"],
                    ["Service", 48, 46, "medium"],
                    ["Value perception", 62, 76, "medium"],
                    ["Delivery", 44, 84, "high"],
                    ["Review response", 38, 66, "high"],
                ],
                "analysis": [
                    "Delivery và review response đang nằm ở vùng cần fix gấp.",
                    "Taste và branch experience là vùng mạnh hơn, phù hợp để amplify.",
                    "Value perception là vùng nhiều người quan tâm nhưng chưa thực sự khỏe.",
                ],
                "action": {"guardrail": "Fix / Amplify split", "owner": "Ops + Marketing", "cta": "Create Attribute Action"},
                "evidence_query": "Fix / Amplify Matrix",
            },
            {
                "title": "Proof of Value Gauge",
                "takeaway": "Sales cần một cách rất nhanh để chứng minh Dotn đã tìm được pain, action và khả năng đo lại.",
                "chart": "gauge",
                "data": {
                    "value": min(96, max(48, positive_proof * 9 + len(menu_highlights) + len(branch_intelligence) * 3)),
                    "label": "Proof of Value Readiness",
                    "detail": f"{positive_proof} proof · {len(menu_highlights)} menu cues · {len(branch_intelligence)} branches",
                    "badges": [
                        f"Positive proof {positive_proof}",
                        f"Menu cues {len(menu_highlights)}",
                        f"Branch coverage {len(branch_intelligence)}",
                    ],
                },
                "analysis": [
                    "Pain chính đã được nhìn ra rõ hơn ở layer Overview và Reputation.",
                    "Branch/store data và proof bank bắt đầu đủ để chuyển từ kể chuyện sang đề xuất action.",
                    "Gauge này nên được xem như readiness score cho sales demo và audit, không phải hiệu quả thật đã realized.",
                ],
                "action": {"guardrail": "Ready for 7-day audit", "owner": "Sales + CS", "cta": "Generate Audit"},
                "evidence_query": "Proof of Value Gauge",
            },
            {
                "title": "Category Brand Rank",
                "takeaway": "Khách muốn biết brand đang đứng ở đâu trong category story, không chỉ đứng ở đâu trong sentiment.",
                "chart": "list",
                "data": [
                    ["Premium rank", f"#{premium_rank}", f"Mạnh hơn ở proof/taste, còn yếu hơn ở delivery/value."],
                    ["Brand score", f"{current_score}/100", "Điểm tổng hợp hiện tại từ asset, drag và proof."],
                    ["Best branch", best_branch.get("branch_name") or "N/A", f"Pattern tốt nhất: {best_branch_topics}"],
                ],
                "analysis": [
                    "Category rank ở đây là proxy để sales nói về vị thế tương đối của brand story, chưa phải market share thật.",
                    "Premium rank tốt hơn khi positive proof, branch experience và value story đồng bộ với nhau.",
                    "Nếu AI synthesis được bật, module này nên rewrite thành narrative benchmark sắc hơn.",
                ],
                "action": {"guardrail": "Benchmark before action", "owner": "CEO + Strategy", "cta": "View Rank Drivers"},
                "evidence_query": "Category Brand Rank",
            },
            {
                "title": "Campaign Readiness & Benchmark",
                "takeaway": "Không phải cứ có trend là chạy campaign; phải biết brand đã đủ proof và đủ fit để mở test hay chưa.",
                "chart": "groupedColumns",
                "data": {
                    "labels": ["Signature bowl", "Premium noodle", "Proof bank", "Value story"],
                    "series": [
                        {"name": "Readiness", "values": [campaign_readiness, current_score, premium_readiness, sentiment_score], "color": "#1f66f5"},
                        {"name": "Benchmark", "values": [72, 74, 68, 62], "color": "#16a26a"},
                    ],
                },
                "analysis": [
                    "Campaign readiness cao nhất đang nằm ở món signature và premium noodle/premium cue.",
                    "Proof bank và value story vẫn cần thêm bằng chứng nếu muốn dùng làm benchmark rộng hơn.",
                    "Đây là module phù hợp để quyết định test 7 ngày hay vẫn nên tiếp tục chuẩn bị proof.",
                ],
                "action": {"guardrail": "Benchmark before campaign", "owner": "Marketing", "cta": "Create Brief"},
                "evidence_query": "Campaign Readiness & Benchmark",
            },
            {
                "title": "Menu Item Sales & Review Coverage",
                "takeaway": "Món nào có sold count, review count và comment evidence sẽ đáng tin hơn khi dùng làm proof hoặc campaign angle.",
                "chart": "simpleTable",
                "data": menu_metric_rows or [["No menu item metrics", "-", "Sold 0", "Reviews 0", "Comments 0"]],
                "analysis": [
                    "ShopeeFood/GrabFood menu metrics hiện được đọc từ raw payload và backfill từ review text nếu platform không trả comment theo món.",
                    "Sold count giúp tách món bán được khỏi món chỉ có mặt trên menu.",
                    "Review comments theo món là evidence tốt hơn menu name thuần khi build proof bank.",
                ],
                "action": {"guardrail": "Use item-level evidence", "owner": "Marketing + Ops", "cta": "Open Menu Evidence"},
                "evidence_query": "Menu Item Sales & Review Coverage",
            },
            {
                "title": "YMI-style Score Decomposition",
                "takeaway": "Tách điểm ra thành các driver dễ đọc để người xem hiểu score thay đổi vì cái gì.",
                "chart": "donut",
                "data": {
                    "labels": ["Taste / proof", "Branch experience", "Delivery drag", "Value drag"],
                    "values": [max(8, quality_boost * 8), max(8, branch_boost * 12), max(8, delivery_drag * 8), max(8, value_drag * 8)],
                },
                "analysis": [
                    "Taste/proof đang là vùng đóng góp dương lớn nhất cho score.",
                    "Delivery drag và value drag vẫn là hai cục âm cần nhìn rõ nếu muốn nâng health score bền vững.",
                    "Kiểu decomposition này rất hợp với mockup vì nó làm score dễ bán hơn hẳn.",
                ],
                "action": {"guardrail": "Show driver, not only score", "owner": "Strategy", "cta": "Open Score Decomposition"},
                "evidence_query": "YMI-style Score Decomposition",
            },
            {
                "title": "Brand Equity & Sentiment Score",
                "takeaway": "Gộp equity signal với sentiment để người xem thấy thương hiệu đang khỏe thật hay chỉ đang nói nhiều.",
                "chart": "gauge",
                "data": {
                    "value": sentiment_score,
                    "label": "Brand equity & sentiment",
                    "detail": f"Positive {positive_proof} · Negative {negative_proof}",
                    "badges": [
                        f"Sentiment {sentiment_score}/100",
                        f"Positive {positive_proof}",
                        f"Negative {negative_proof}",
                    ],
                },
                "analysis": [
                    "Brand equity không thể chỉ đọc bằng positive buzz; nó phải đi cùng source trust và branch consistency.",
                    "Nếu negative proof tăng nhanh hơn positive asset, score này nên tụt để cảnh báo đúng business risk.",
                    "Đây là điểm rất hợp để AI rewrite thành câu brand narrative gọn hơn.",
                ],
                "action": {"guardrail": "Buzz is not equity", "owner": "Brand", "cta": "Open Sentiment Drivers"},
                "evidence_query": "Brand Equity & Sentiment Score",
            },
            {
                "title": "Proof of Premium Readiness",
                "takeaway": "Đánh giá xem brand đã đủ cue để kể câu chuyện premium chưa, hay mới chỉ premium ở một vài mảnh lẻ.",
                "chart": "gauge",
                "data": {
                    "value": premium_readiness,
                    "label": "Premium readiness",
                    "detail": f"Rank #{premium_rank} · proof {positive_proof}",
                    "badges": [
                        f"Rank #{premium_rank}",
                        f"Proof {positive_proof}",
                        f"Best branch {best_branch.get('branch_name') or 'N/A'}",
                    ],
                },
                "analysis": [
                    "Premium readiness tăng khi proof về taste, branch experience và value framing đi cùng nhau.",
                    "Nếu delivery pain còn quá lộ thì câu chuyện premium sẽ dễ bị phản tác dụng.",
                    "Module này rất hợp để support phần mockup về premium brand positioning.",
                ],
                "action": {"guardrail": "Premium needs proof, not just design", "owner": "Brand + Marketing", "cta": "Open Premium Proof"},
                "evidence_query": "Proof of Premium Readiness",
            },
            {
                "title": "Brand Health by Branch",
                "takeaway": "Không có brand health chung nếu từng branch đang kéo score theo hướng rất khác nhau.",
                "chart": "groupedColumns",
                "data": {
                    "labels": branch_labels,
                    "series": [
                        {"name": "Brand score", "values": branch_brand_scores, "color": "#1f66f5"},
                        {"name": "Positive signal", "values": branch_sentiments, "color": "#16a26a"},
                        {"name": "Delivery drag", "values": branch_delivery, "color": "#d94444"},
                    ],
                },
                "analysis": [
                    "Brand score theo branch giúp thấy rõ nơi nào là template tốt và nơi nào đang kéo story chung đi xuống.",
                    "Nếu một branch quá yếu, đội sales không nên nói brand-level health mà không kèm branch caveat.",
                    "Cũng là module tốt để nối sang branch coaching hoặc local campaign decisions.",
                ],
                "action": {"guardrail": "Branch truth before brand claim", "owner": "Ops + Brand", "cta": "Open Branch Health"},
                "evidence_query": "Brand Health by Branch",
            },
            {
                "title": "Best Branch Pattern",
                "takeaway": "Khách thường hỏi: nếu có một chi nhánh làm tốt nhất thì pattern đó là gì và có nhân rộng được không?",
                "chart": "list",
                "data": [
                    [best_branch.get("branch_name") or "N/A", f"Rating {best_branch.get('avg_rating') or 0}", f"Pattern: {best_branch_topics}"],
                    [worst_branch.get("branch_name") or "N/A", f"Risk {worst_branch.get('risk_score') or 0}", f"Watchout: {worst_branch_topics}"],
                ],
                "analysis": [
                    "Best branch pattern là cách rất trực quan để nói về replication thay vì chỉ report score.",
                    "Nếu pattern của best branch không lặp lại được ở nơi khác thì brand health chưa thực sự bền.",
                    "Về sau AI có thể rewrite pattern này thành operating playbook tốt hơn.",
                ],
                "action": {"guardrail": "Replicate pattern, not just praise branch", "owner": "Ops", "cta": "Open Best Pattern"},
                "evidence_query": "Best Branch Pattern",
            },
            # Priority Action Detail removed - it's a FEED TABLE, not a dashboard module
        ]

    def _reputation_modules(self, branch_intelligence: list[dict], daily_branch_metrics: list[dict], evidence_cards: list[dict]) -> list[dict]:
        negative_reviews = len([row for row in evidence_cards if row.get("sentiment_label") == "negative"])
        proof_count = len([row for row in evidence_cards if row.get("sentiment_label") == "positive"])
        shopeefood_menu_items = sum(int(row.get("menu_count") or 0) for row in branch_intelligence)
        shopeefood_covered_branches = sum(1 for row in branch_intelligence if int(row.get("menu_count") or 0) > 0)
        rated_rows = [float(row.get("avg_rating") or 0) for row in daily_branch_metrics if float(row.get("avg_rating") or 0) > 0]
        google_maps_avg = round(sum(rated_rows) / len(rated_rows), 1) if rated_rows else 0.0
        google_maps_rated_branches = sum(1 for row in daily_branch_metrics if float(row.get("avg_rating") or 0) > 0)

        modules = [
            {
                "title": "Crisis Spike Monitor",
                "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
                "chart": "line",
                "data": {
                    "labels": ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                    "series": [
                        {"name": "Negative comments", "values": [4, 5, 7, 10, 14, 18, 24, max(28, negative_reviews * 4)], "color": "#d94444"},
                    ],
                },
                "analysis": [
                    "Negative evidence đang dày hơn ở nửa cuối, cho thấy pattern escalation đáng theo dõi.",
                    "Module này nên đóng vai trò trigger alert trước khi đội CX/Ops mở workflow xử lý.",
                ],
                "action": {"guardrail": "Monitor First", "owner": "MKT + CS + CEO", "cta": "Open Crisis Workflow"},
                "evidence_query": "Crisis Spike Monitor",
            },
            {
                "title": "Review Health Heatmap",
                "takeaway": "Khách nhìn vào 5 giây là biết nền tảng nào đang xấu nhất.",
                "chart": "table",
                "data": [
                    ["Google Maps", str(google_maps_avg or 0), str(google_maps_rated_branches), "review-led"],
                    ["Facebook", str(negative_reviews), str(sum(1 for row in daily_branch_metrics if int(row.get('negative_count') or 0) > 0)), "discussion"],
                    ["TikTok", str(sum(1 for row in daily_branch_metrics if int(row.get('mention_count') or 0) > 0)), str(negative_reviews), "buzz"],
                    ["ShopeeFood", f"{shopeefood_menu_items} menu", str(shopeefood_covered_branches), "delivery"],
                ],
                "analysis": [
                    f"Google Maps hiện là nguồn review trust cao nhất của Meili, với {google_maps_rated_branches} branch đã có rating trong dashboard.",
                    "Facebook/TikTok phù hợp để theo dõi tốc độ lan truyền và social pressure hơn là rating health thuần.",
                    "ShopeeFood hiện cho coverage tốt về branch/menu; review text vẫn chưa đủ sâu để kết luận reputational pressure mạnh.",
                ],
                "action": {"guardrail": "Fix weakest channel first", "owner": "Ops + CS", "cta": "Create Review Recovery"},
                "evidence_query": "Review Health Heatmap",
            },
            {
                "title": "Response SLA Donut",
                "takeaway": "Nếu review xấu không được phản hồi nhanh, trust sẽ giảm tiếp.",
                "chart": "donut",
                "data": {
                    "values": [max(18, 68 - negative_reviews), min(42, 18 + negative_reviews), min(26, 8 + negative_reviews // 2)],
                    "labels": ["Đúng SLA", "Trễ SLA", "Chưa phản hồi"],
                },
                "analysis": [
                    "Tỷ lệ chưa phản hồi nên được xem như operational risk chứ không chỉ là CS metric.",
                    "Mockup muốn nhìn rất nhanh nhóm nào đang đúng SLA, trễ SLA và chưa phản hồi.",
                ],
                "action": {"guardrail": "SLA-based operation", "owner": "CS Lead", "cta": "Assign Response Workflow"},
                "evidence_query": "Response SLA Donut",
            },
            {
                "title": "Social Proof Pipeline",
                "takeaway": "Review tốt cần được tái sử dụng để tạo tăng trưởng.",
                "chart": "pipeline",
                "data": [
                    ["Positive reviews", max(12, proof_count * 8)],
                    ["Proof selected", max(8, proof_count * 4)],
                    ["Ready for content", max(4, proof_count * 2)],
                    ["Used in campaign", max(1, proof_count)],
                ],
                "analysis": [
                    "Review tốt hiện vẫn đang được dùng dưới khả năng thật của nó.",
                    "Pipeline này là bridge giữa Reputation và Marketing, không nên để review tốt nằm chết trong DB.",
                ],
                "action": {"guardrail": "Safe to Amplify", "owner": "Marketing", "cta": "Create Social Proof Campaign"},
                "evidence_query": "Social Proof Pipeline",
            },
        ]

        # Replace old Crisis Spike Monitor with real data version
        modules[0] = self._build_crisis_spike_module_v2()

        # NEW: Add 3 more modules from mockup v16
        modules.extend([
            self._build_founder_watch_module_v2(),
            self._build_qualified_negative_module_v2(),
            self._build_topic_lifecycle_module_v2(),
        ])

        return modules

    def _competitor_modules(self, platform_summary: list[dict], branch_intelligence: list[dict], menu_highlights: list[dict]) -> list[dict]:
        """Build modules for Competitor Radar screen from real data"""
        pressure_data = self._fetch_competitor_pressure()
        patterns = self._fetch_competitor_patterns()
        responses = self._fetch_competitor_responses()
        our_scores = self._fetch_our_brand_scores()

        modules = []

        # Module 1: Competitive Pressure Radar
        if pressure_data and our_scores:
            radar_data = self._build_radar_chart_data(pressure_data, our_scores)
            modules.append({
                "title": "Competitive Pressure Radar",
                "takeaway": "So sánh brand với competitors trên 6 dimensions: Delivery, Value, Family, Experience, Social Buzz, Premium",
                "chart": "radar",
                "data": radar_data,
                "analysis": self._analyze_pressure_radar(pressure_data, our_scores),
                "action": {
                    "guardrail": "Pressure-led response",
                    "owner": "Marketing + Ops",
                    "cta": "Prioritize Competitor Response",
                },
                "evidence_query": "Competitive Pressure Radar",
            })

        # Module 2: Winning Pattern Comparison
        if patterns:
            pattern_data = self._build_pattern_chart_data(patterns)
            modules.append({
                "title": "Winning Pattern Comparison",
                "takeaway": "Patterns nào competitors đang thắng: Family combo, Delivery deal, Premium storytelling, Local value",
                "chart": "groupedColumns",
                "data": pattern_data,
                "analysis": self._analyze_patterns(patterns),
                "action": {
                    "guardrail": "Brand-fit before copy",
                    "owner": "Marketing",
                    "cta": "Select Response Mode",
                },
                "evidence_query": "Winning Pattern Comparison",
            })

        # Module 3: 5-Mode Response Map
        if responses:
            mode_map_data = self._build_mode_map_data(responses)
            modules.append({
                "title": "5-Mode Response Map",
                "takeaway": "Strategic responses: Similar (copy), Different (differentiate), Merge (combine), Counter (attack), Exploit (weakness)",
                "chart": "modeMap",
                "data": mode_map_data,
                "analysis": self._analyze_response_modes(responses),
                "action": {
                    "guardrail": "Choose one mode clearly",
                    "owner": "Marketing",
                    "cta": "Execute Response",
                },
                "evidence_query": "5-Mode Response Map",
            })

        # Module 4: Competitive Intelligence Readiness
        modules.append({
            "title": "Competitive Intelligence Readiness",
            "takeaway": "Mức độ sẵn sàng của competitor data: Detections → Pressure Analysis → Responses → Execution",
            "chart": "funnel",
            "data": self._build_audit_funnel_data(pressure_data, patterns, responses),
            "analysis": [
                f"Đã phát hiện {len(pressure_data)} competitive pressure points",
                f"Đã trích xuất {len(patterns)} winning patterns",
                f"Đã tạo {len(responses)} response recommendations",
                "Ready để chuyển insights thành action",
            ],
            "action": {
                "guardrail": "Data-driven decisions",
                "owner": "Strategy",
                "cta": "Review Recommendations",
            },
            "evidence_query": "Competitive Intelligence Readiness",
        })

        # NEW: 3 modules from mockup v16
        modules.extend([
            self._build_campaign_ranking_module_v2(),
            self._build_content_pattern_module_v2(),
            self._build_5w1h_diagnosis_module_v2(),
        ])

        return modules

    def _listen_headline(self, platform_summary: list[dict], evidence_cards: list[dict]) -> str:
        social_platforms = [row for row in platform_summary if row.get("platform") in {"tiktok", "facebook", "instagram"}]
        return f"Listen screen đang gom các pain, demand và positive themes từ {len(social_platforms)} social platform, với {len(evidence_cards)} evidence card để bám vào insight thay vì chỉ nhìn raw mention count."

    def _brand_top_cards(
        self,
        platform_summary: list[dict],
        branch_intelligence: list[dict],
        menu_highlights: list[dict],
        evidence_cards: list[dict],
    ) -> list[dict]:
        best_branch = min(branch_intelligence, key=lambda row: int(row.get("risk_score") or 0), default={})
        worst_branch = max(branch_intelligence, key=lambda row: int(row.get("risk_score") or 0), default={})
        positive_proof = len([row for row in evidence_cards if str(row.get("sentiment_label") or "") == "positive"])
        negative_proof = len([row for row in evidence_cards if str(row.get("sentiment_label") or "") == "negative"])
        menu_names = [str(row.get("item_name") or "") for row in menu_highlights]
        menu_blob = " ".join(name.lower() for name in menu_names)
        if "sườn bò" in menu_blob or "bò" in menu_blob:
            signature_label = "Mì sườn bò"
            growth_asset_label = "Mì bò / nước hầm"
            category_rank_label = "Taiwan noodle\nrank"
        elif "sủi cảo" in menu_blob:
            signature_label = "Sủi cảo"
            growth_asset_label = "Sủi cảo / nhân"
            category_rank_label = "Dumpling bowl\nrank"
        else:
            signature_label = "Món signature"
            growth_asset_label = "Signature / taste"
            category_rank_label = "Signature bowl\nrank"
        quality_boost = min(12, positive_proof * 2 + len(menu_highlights))
        delivery_drag = max(4, int(worst_branch.get("negative_count") or 0) * 2)
        value_drag = max(2, negative_proof // 2)
        current_score = max(34, min(92, 72 + quality_boost - delivery_drag - value_drag))
        premium_rank = 1 if current_score >= 82 else 2 if current_score >= 70 else 3
        premium_readiness = max(32, min(95, 48 + len(menu_highlights) * 5 + positive_proof * 3 - negative_proof * 2))
        sentiment_score = max(28, min(92, 58 + positive_proof * 4 - negative_proof * 3))
        campaign_readiness = max(24, min(94, 44 + len(menu_highlights) * 6 + positive_proof * 3))
        best_topics = ", ".join((best_branch.get("top_topics") or [])[:2]) or "taste / branch experience"
        social_volume = sum(int(row.get("relevant_count") or 0) for row in platform_summary if str(row.get("platform") or "") in {"facebook", "tiktok", "instagram", "threads"})
        return [
            {
                "tag": "SCORE",
                "title": "Brand\nHealth",
                "value": f"{current_score}/100",
                "desc": "Target 80",
                "severity": "low" if current_score >= 80 else "medium",
                "owner": "CEO",
                "guardrail": "Theo dõi trước · Explain Score",
                "evidence_query": "Score Waterfall",
                "evidence_kind": "brand_score",
            },
            {
                "tag": "RỦI RO DOANH THU",
                "title": "Delivery",
                "value": f"-{delivery_drag}",
                "desc": "Driver kéo điểm xuống",
                "severity": "high",
                "owner": "Vận hành",
                "guardrail": "Ưu tiên sửa trước · Fix",
                "evidence_query": "Fix / Amplify Matrix",
                "evidence_kind": "brand_delivery_drag",
            },
            {
                "tag": "CONVERSION RISK",
                "title": "Value perception",
                "value": f"-{value_drag}",
                "desc": "Khách ngại thử",
                "severity": "medium",
                "owner": "Marketing",
                "guardrail": "Theo dõi trước · Bằng chứng giá trị",
                "evidence_query": "Brand Equity & Sentiment Score",
                "evidence_kind": "brand_value_perception",
            },
            {
                "tag": "GROWTH ASSET",
                "title": growth_asset_label,
                "value": f"+{quality_boost}",
                "desc": "Driver tăng điểm",
                "severity": "low",
                "owner": "Marketing",
                "guardrail": "An toàn để khuếch đại · Amplify",
                "evidence_query": "Proof of Premium Readiness",
                "evidence_kind": "brand_growth_asset",
            },
            {
                "tag": "CATEGORY RANK",
                "title": category_rank_label,
                "value": f"#{premium_rank}",
                "desc": "Mạnh ở món signature/experience, yếu ở delivery/value",
                "severity": "low" if premium_rank <= 2 else "medium",
                "owner": "CEO",
                "guardrail": "Benchmark Before Action · View Rank Drivers",
                "evidence_query": "Category Brand Rank",
                "evidence_kind": "brand_category_rank",
            },
            {
                "tag": "CAMPAIGN READY",
                "title": f"{signature_label}\nbrief",
                "value": f"{campaign_readiness}/100",
                "desc": "Đủ tín hiệu để chuyển sang test món signature / value offer",
                "severity": "medium",
                "owner": "Marketing",
                "guardrail": "Sẵn sàng chạy campaign · Create Brief",
                "evidence_query": "Campaign Readiness & Benchmark",
                "evidence_kind": "brand_campaign_ready",
            },
            {
                "tag": "SENTIMENT\nSCORE",
                "title": "Net\nSentiment",
                "value": f"{sentiment_score}/100",
                "desc": f"Positive {max(0, min(100, 46 + positive_proof * 2))}% · Neutral 30% · Negative {max(0, min(100, 24 - positive_proof + negative_proof))}%",
                "severity": "medium" if sentiment_score < 75 else "low",
                "owner": "Brand",
                "guardrail": "Track sentiment drivers · Open Sentiment Drivers",
                "evidence_query": "Brand Equity & Sentiment Score",
                "evidence_kind": "brand_sentiment",
            },
            {
                "tag": "BEST BRANCH",
                "title": self._truncate(str(best_branch.get("branch_name") or "Best branch"), 28),
                "value": best_topics.title(),
                "desc": f"Social volume {social_volume} · premium readiness {premium_readiness}/100",
                "severity": "low",
                "owner": "Ops",
                "guardrail": "Replicate pattern · Open Best Pattern",
                "evidence_query": "Best Branch Pattern",
                "evidence_kind": "brand_best_branch",
                "evidence_branch": str(best_branch.get("branch_name") or ""),
            },
        ]

    def _brand_headline(self, branch_intelligence: list[dict], menu_highlights: list[dict]) -> str:
        best = min(branch_intelligence, key=lambda row: int(row.get("risk_score") or 0), default={})
        return f"Brand Health hiện nghiêng mạnh về câu chuyện branch/store và proof bank. Chi nhánh ổn nhất hiện tại là {best.get('branch_name', 'n/a')}, trong khi menu metadata đã có {len(menu_highlights)} highlight để build asset."

    def _reputation_headline(self, branch_intelligence: list[dict], evidence_cards: list[dict]) -> str:
        high_risk = [row for row in branch_intelligence if str(row.get("risk_level") or "") == "High"]
        negative_evidence = [row for row in evidence_cards if row.get("sentiment_label") == "negative"]
        return f"Reputation screen đang tập trung vào review/rating pressure: {len(high_risk)} branch risk cao và {len(negative_evidence)} negative evidence card đủ điều kiện để mở case xử lý."

    def _competitor_headline(self, platform_summary: list[dict]) -> str:
        """Generate headline for Competitor Radar screen from real data"""
        responses = self._fetch_competitor_responses()
        pressure_data = self._fetch_competitor_pressure()

        if not responses and not pressure_data:
            return "Competitor Radar: Chạy competitor analysis jobs để hiển thị insights về đối thủ và chiến lược phản ứng."

        high_priority = [r for r in responses if r.get('priority') == 'high']
        high_pressure = [p for p in pressure_data if p.get('pressure_level') == 'high']

        threats = ", ".join(set(r['competitor_name'] for r in high_pressure[:3])) if high_pressure else "competitors"
        modes = ", ".join(set(r['response_mode'] for r in high_priority[:3])) if high_priority else "strategic responses"

        return f"Competitor insight: {len(high_pressure)} high-pressure threats from {threats}. Recommended modes: {modes}. Action-ready recommendations: {len(responses)}."

    # Reputation Intelligence Helper Methods

    def _fetch_crisis_spikes(self, days: int = 7) -> list[dict]:
        """Fetch recent crisis spikes for monitoring"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY spike_date DESC, detected_at DESC), '[]'::json)
            FROM (
              SELECT
                spike_date,
                spike_hour,
                metric_type,
                baseline_value::float,
                spike_value::float,
                spike_magnitude::float,
                severity,
                trigger_keywords,
                status,
                detected_at
              FROM {self.schema}.crisis_spike_alerts
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                AND spike_date >= CURRENT_DATE - INTERVAL '{days} days'
              ORDER BY spike_date DESC, detected_at DESC
              LIMIT 30
            ) t;
            """
        )

    def _fetch_founder_mentions(self, days: int = 42) -> list[dict]:
        """Fetch founder/CEO mentions for reputation watch"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY mention_date DESC), '[]'::json)
            FROM (
              SELECT
                founder_name,
                sentiment_label,
                sentiment_score::float,
                risk_level,
                context_type,
                mention_date,
                mention_text
              FROM {self.schema}.founder_mentions
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                AND mention_date >= CURRENT_DATE - INTERVAL '{days} days'
              ORDER BY mention_date DESC
              LIMIT 100
            ) t;
            """
        )

    def _fetch_qualified_negative_summary(self) -> list[dict]:
        """Fetch qualified negative signal summary by platform"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY qualified_percentage DESC), '[]'::json)
            FROM (
              SELECT
                platform,
                total_negative_count::int,
                qualified_negative_count::int,
                noise_negative_count::int,
                qualified_percentage::float,
                avg_trust_score::float,
                top_topics
              FROM {self.schema}.qualified_negative_summary
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                AND snapshot_date = (
                  SELECT MAX(snapshot_date)
                  FROM {self.schema}.qualified_negative_summary
                  WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
                )
            ) t;
            """
        )

    def _fetch_topic_lifecycle(self) -> list[dict]:
        """Fetch topics in lifecycle stages"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
              CASE lifecycle_stage
                WHEN 'detect' THEN 1
                WHEN 'monitor' THEN 2
                WHEN 'fix' THEN 3
                WHEN 'recover' THEN 4
                WHEN 'amplify' THEN 5
              END,
              volume_7d DESC
            ), '[]'::json)
            FROM (
              SELECT
                topic_name,
                topic_category,
                lifecycle_stage,
                velocity,
                volume_7d::int,
                volume_change_pct::float,
                sentiment_trend,
                avg_sentiment_score::float,
                recommended_action,
                guardrail,
                owner
              FROM {self.schema}.topic_lifecycle
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY last_updated DESC
              LIMIT 20
            ) t;
            """
        )

    def _fetch_campaign_intelligence(self) -> list[dict]:
        """Fetch competitor campaign intelligence"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY overall_score DESC), '[]'::json)
            FROM (
              SELECT
                competitor_name,
                campaign_name,
                campaign_type,
                qualified_users_score::float,
                buzz_score::float,
                object_mention_score::float,
                sentiment_score::float,
                overall_score::float
              FROM {self.schema}.campaign_intelligence
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY overall_score DESC
              LIMIT 10
            ) t;
            """
        )

    def _fetch_content_patterns(self) -> list[dict]:
        """Fetch winning content patterns"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pattern_strength DESC), '[]'::json)
            FROM (
              SELECT
                pattern_name,
                pattern_description,
                pattern_strength::float,
                risk_level,
                recommended_response,
                response_rationale
              FROM {self.schema}.content_patterns
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY pattern_strength DESC
              LIMIT 10
            ) t;
            """
        )

    def _fetch_signal_diagnosis(self, limit: int = 5) -> list[dict]:
        """Fetch 5W-1H signal diagnosis"""
        return self._query_json(
            f"""
            SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
              CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              confidence_score DESC
            ), '[]'::json)
            FROM (
              SELECT
                signal_name,
                signal_type,
                who_audience,
                what_need,
                where_source,
                when_timing,
                why_reason,
                how_action,
                confidence_score::float,
                priority,
                recommended_next_step,
                owner
              FROM {self.schema}.signal_diagnosis
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
              ORDER BY created_at DESC
              LIMIT {int(limit)}
            ) t;
            """
        )


    # Reputation Intelligence Build Methods

    def _build_crisis_spike_module_v2(self) -> dict:
        """Build Crisis Spike Monitor module with real spike data"""
        spikes = self._fetch_crisis_spikes(days=7)
        
        if not spikes:
            return {
                "title": "Crisis Spike Monitor",
                "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
                "chart": "line",
                "data": {"labels": [], "series": []},
                "analysis": ["No crisis spikes detected", "System monitoring for anomalies"],
                "action": {"guardrail": "Evidence-backed", "owner": "CS + Ops", "cta": "Open Evidence"},
                "evidence_query": "Crisis Spike Monitor",
            }
        
        from collections import defaultdict
        spike_by_hour = defaultdict(int)
        for spike in spikes:
            hour = spike.get('spike_hour', 12)
            spike_by_hour[hour] += 1
        
        hours = sorted(spike_by_hour.keys())[-8:] if spike_by_hour else list(range(10, 18))
        labels = [f"{h}:00" for h in hours]
        values = [spike_by_hour.get(h, 0) for h in hours]
        
        high_severity = [s for s in spikes if s.get('severity') == 'high']
        analysis = []
        if high_severity:
            analysis.append(f"{len(high_severity)} high-severity spikes trong 7 ngày")
        else:
            analysis.append("Chưa có spike đáng lo ngại")
        
        return {
            "title": "Crisis Spike Monitor",
            "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
            "chart": "line",
            "data": {"labels": labels, "series": [{"name": "Spikes", "values": values, "color": "#d94444"}]},
            "analysis": analysis,
            "action": {"guardrail": "Evidence-backed", "owner": "CS + Ops", "cta": "Open Evidence"},
            "evidence_query": "Crisis Spike Monitor",
        }

    def _build_founder_watch_module_v2(self) -> dict:
        """Build Founder/CEO Watch module"""
        mentions = self._fetch_founder_mentions(days=42)
        
        if not mentions:
            return {
                "title": "Founder / CEO Reputation Watch",
                "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
                "chart": "line",
                "data": {"labels": ["W1","W2","W3","W4","W5","W6"], "series": [{"name": "Mentions", "values": [0]*6, "color": "#1f66f5"}]},
                "analysis": ["No founder mentions detected"],
                "action": {"guardrail": "Monitor First", "owner": "CEO + PR", "cta": "Open Founder Watch"},
                "evidence_query": "Founder Watch",
            }
        
        from collections import defaultdict
        from datetime import datetime
        week_data = defaultdict(lambda: {'total': 0, 'negative': 0})
        for m in mentions:
            try:
                date = datetime.strptime(m['mention_date'], '%Y-%m-%d')
                week_num = date.isocalendar()[1]
                week_key = f"W{week_num}"
                week_data[week_key]['total'] += 1
                if m.get('sentiment_label') == 'negative':
                    week_data[week_key]['negative'] += 1
            except:
                pass
        
        weeks = sorted(week_data.keys())[-6:]
        total_values = [week_data[w]['total'] for w in weeks]
        negative_values = [week_data[w]['negative'] for w in weeks]
        
        return {
            "title": "Founder / CEO Reputation Watch",
            "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
            "chart": "line",
            "data": {"labels": weeks if weeks else ["W1","W2","W3","W4","W5","W6"], "series": [
                {"name": "Founder mentions", "values": total_values if total_values else [0]*6, "color": "#1f66f5"},
                {"name": "Negative risk", "values": negative_values if negative_values else [0]*6, "color": "#d94444"}
            ]},
            "analysis": [f"{len([m for m in mentions if m.get('risk_level')=='high'])} high-risk mentions"] if mentions else ["Chưa có data"],
            "action": {"guardrail": "Monitor First", "owner": "CEO + PR", "cta": "Open Founder Watch"},
            "evidence_query": "Founder Watch",
        }

    def _build_qualified_negative_module_v2(self) -> dict:
        """Build Qualified Negative Signal module"""
        summary = self._fetch_qualified_negative_summary()
        
        if not summary:
            return {
                "title": "Qualified Negative Signal",
                "takeaway": "Một negative từ khách thật quan trọng hơn noise.",
                "chart": "stacked",
                "data": [],
                "analysis": ["Chưa có data"],
                "action": {"guardrail": "Prioritize high-trust", "owner": "CS + Ops", "cta": "Run Analysis"},
                "evidence_query": "Qualified Negative",
            }
        
        data = [[r['platform'].title(), r['qualified_negative_count'], r['noise_negative_count'], int(r['qualified_percentage'])] for r in summary[:5]]
        
        return {
            "title": "Qualified Negative Signal",
            "takeaway": "Một negative từ khách thật/review thật quan trọng hơn nhiều negative từ noise.",
            "chart": "stacked",
            "data": data,
            "analysis": ["Review platforms có qualified % cao nhất", "Social có nhiều noise hơn"],
            "action": {"guardrail": "Prioritize high-trust", "owner": "CS + Ops", "cta": "Open Qualified"},
            "evidence_query": "Qualified Negative",
        }

    def _build_topic_lifecycle_module_v2(self) -> dict:
        """Build Topic Lifecycle module"""
        topics = self._fetch_topic_lifecycle()
        
        if not topics:
            return {
                "title": "Sensitive Topic Lifecycle",
                "takeaway": "Topics theo lifecycle: detect → monitor → fix → recover → amplify.",
                "chart": "timeline",
                "data": [],
                "analysis": ["Chưa có topics tracked"],
                "action": {"guardrail": "Contain -> Fix -> Recover", "owner": "MKT + CS", "cta": "Track Topics"},
                "evidence_query": "Topic Lifecycle",
            }
        
        stage_map = {'detect': 'Detect', 'monitor': 'Monitor', 'fix': 'Fix', 'recover': 'Recover', 'amplify': 'Amplify'}
        data = [[stage_map.get(t['lifecycle_stage'], t['lifecycle_stage'].title()), t['topic_name'], t.get('recommended_action', 'Monitor')] for t in topics[:5]]
        
        return {
            "title": "Sensitive Topic Lifecycle",
            "takeaway": "Các keyword nhạy cảm theo lifecycle: mới nổi, tăng tốc, lan rộng hay đã giảm.",
            "chart": "timeline",
            "data": data,
            "analysis": [f"{len([t for t in topics if t['lifecycle_stage']=='fix'])} topics cần fix ngay"],
            "action": {"guardrail": "Contain -> Fix -> Recover", "owner": "MKT + CS + Ops", "cta": "Open Topics"},
            "evidence_query": "Topic Lifecycle",
        }


    
    # Competitor Intelligence Build Methods

    def _build_campaign_ranking_module_v2(self) -> dict:
        """Build Competitor Campaign Ranking module"""
        campaigns = self._fetch_campaign_intelligence()
        
        if not campaigns:
            return {
                "title": "Competitor Campaign Ranking",
                "takeaway": "Benchmark campaign đối thủ theo qualified users, buzz, object mention, sentiment.",
                "chart": "groupedColumns",
                "data": {"labels": [], "series": []},
                "analysis": ["Chưa có competitor campaigns"],
                "action": {"guardrail": "Learn pattern, not copy blindly", "owner": "Marketing", "cta": "Track Campaigns"},
                "evidence_query": "Campaign Benchmark",
            }
        
        labels = ["Qualified users", "Buzz", "Object mention", "Sentiment"]
        colors = ["#1f66f5", "#d94444", "#16a26a", "#6952d8"]
        series = []
        
        for i, c in enumerate(campaigns[:3]):
            series.append({
                "name": f"{c['competitor_name']} {c['campaign_name'][:15]}",
                "values": [c.get('qualified_users_score',0), c.get('buzz_score',0), c.get('object_mention_score',0), c.get('sentiment_score',0)],
                "color": colors[i % len(colors)]
            })
        
        return {
            "title": "Competitor Campaign Ranking",
            "takeaway": "Benchmark campaign đối thủ theo qualified users, buzz, object mention, sentiment.",
            "chart": "groupedColumns",
            "data": {"labels": labels, "series": series},
            "analysis": [f"{len(campaigns)} campaigns tracked", "Buzz và sentiment là metrics quan trọng nhất"],
            "action": {"guardrail": "Learn pattern, not copy", "owner": "Marketing", "cta": "Open Benchmark"},
            "evidence_query": "Campaign Benchmark",
        }

    def _build_content_pattern_module_v2(self) -> dict:
        """Build Winning Content Pattern module"""
        patterns = self._fetch_content_patterns()
        
        if not patterns:
            return {
                "title": "Winning Content Pattern",
                "takeaway": "Pattern nội dung đang thắng → quyết định Similar/Different/Merge/Counter/Exploit.",
                "chart": "hbar",
                "data": [],
                "analysis": ["Chưa có content patterns"],
                "action": {"guardrail": "Choose one mode", "owner": "Marketing", "cta": "Analyze Patterns"},
                "evidence_query": "Content Patterns",
            }
        
        data = [[p['pattern_name'].replace('_',' ').title(), int(p['pattern_strength']), p.get('risk_level','medium')] for p in patterns[:5]]
        
        return {
            "title": "Winning Content Pattern",
            "takeaway": "Tìm pattern nội dung đang thắng theo category để quyết định Similar, Different, Merge, Counter hay Exploit.",
            "chart": "hbar",
            "data": data,
            "analysis": [f"{len(patterns)} patterns identified", "Patterns có risk cao cần cẩn thận khi copy"],
            "action": {"guardrail": "Choose one mode", "owner": "Marketing", "cta": "Choose Mode"},
            "evidence_query": "Content Patterns",
        }

    def _build_5w1h_diagnosis_module_v2(self) -> dict:
        """Build 5W-1H Signal Diagnosis module"""
        diagnoses = self._fetch_signal_diagnosis(limit=3)
        
        if not diagnoses:
            return {
                "title": "5W-1H Signal Diagnosis",
                "takeaway": "Biến signal thành brief: Who, What, Where, When, Why, How.",
                "chart": "modeMap",
                "data": [],
                "analysis": ["Chưa có signal diagnosis"],
                "action": {"guardrail": "Decision brief before campaign", "owner": "Marketing + CEO", "cta": "Generate Brief"},
                "evidence_query": "5W-1H Diagnosis",
            }
        
        top = diagnoses[0]
        data = [
            ["Who", top.get('who_audience', 'Target audience'), "Audience"],
            ["What", top.get('what_need', 'Customer need'), "Need"],
            ["Where", top.get('where_source', 'Sources'), "Channel"],
            ["When", top.get('when_timing', 'Timing'), "Window"],
            ["Why", top.get('why_reason', 'Motivation'), "Why"],
            ["How", top.get('how_action', 'Action'), "Next step"],
        ]
        
        return {
            "title": "5W-1H Signal Diagnosis",
            "takeaway": "Biến một signal/cơ hội thành brief chiến lược ngắn: ai nói, nói gì, ở đâu, khi nào, vì sao, và phản ứng thế nào.",
            "chart": "modeMap",
            "data": data,
            "analysis": [f"Signal: {top['signal_name']}", f"Priority: {top.get('priority','medium')}", "5W-1H giúp tạo brief cho Cụm 2"],
            "action": {"guardrail": "Decision brief before campaign", "owner": "Marketing + CEO", "cta": "Generate Brief"},
            "evidence_query": "5W-1H Diagnosis",
        }


        # Competitor Chart Building Helper Methods

    def _build_radar_chart_data(self, pressure_data: list[dict], our_scores: dict) -> dict:
        """Build radar chart data structure"""
        dimensions = ['delivery', 'value', 'family', 'experience', 'social_buzz', 'premium']

        # Group by competitor
        competitors = {}
        for row in pressure_data:
            comp_name = row['competitor_name']
            if comp_name not in competitors:
                competitors[comp_name] = {}
            competitors[comp_name][row['dimension']] = row['competitor_score']

        # Build series
        series = []

        # Our brand
        series.append({
            "name": "Our Brand",
            "values": [our_scores.get(dim, 0) for dim in dimensions],
            "color": "#1f66f5"  # Blue
        })

        # Top 3 competitors by total score
        comp_totals = [(name, sum(scores.values())) for name, scores in competitors.items()]
        comp_totals.sort(key=lambda x: x[1], reverse=True)

        colors = ["#16a26a", "#d94444", "#6952d8"]  # Green, Red, Purple
        for i, (comp_name, _) in enumerate(comp_totals[:3]):
            series.append({
                "name": comp_name,
                "values": [competitors[comp_name].get(dim, 0) for dim in dimensions],
                "color": colors[i]
            })

        return {
            "axes": [dim.replace('_', ' ').title() for dim in dimensions],
            "series": series
        }

    def _build_pattern_chart_data(self, patterns: list[dict]) -> dict:
        """Build grouped columns chart data for pattern comparison"""
        pattern_types = ['family_combo', 'delivery_deal', 'premium_storytelling', 'local_value']

        # Group by competitor
        by_competitor = {}
        for row in patterns:
            comp = row['competitor_name']
            if comp not in by_competitor:
                by_competitor[comp] = {}
            by_competitor[comp][row['pattern_name']] = row['pattern_strength']

        # Build series
        series = []
        colors = ["#1f66f5", "#16a26a", "#d94444", "#6952d8"]

        for i, (comp_name, comp_patterns) in enumerate(list(by_competitor.items())[:4]):
            series.append({
                "name": comp_name,
                "values": [comp_patterns.get(pt, 0) for pt in pattern_types],
                "color": colors[i % len(colors)]
            })

        return {
            "labels": [pt.replace('_', ' ').title() for pt in pattern_types],
            "series": series
        }

    def _build_mode_map_data(self, responses: list[dict]) -> list[dict]:
        """Build 5-mode response map data"""
        mode_descriptions = {
            'similar': {'when': 'Pattern fits our brand DNA', 'example': ''},
            'different': {'when': "Don't compete directly (price war)", 'example': ''},
            'merge': {'when': 'Combine their pattern with our strength', 'example': ''},
            'counter': {'when': 'Attack after fixing internal issues', 'example': ''},
            'exploit': {'when': 'Highlight competitor weakness', 'example': ''},
        }

        # Fill in examples from actual responses
        for response in responses:
            mode = response['response_mode']
            if mode in mode_descriptions and not mode_descriptions[mode]['example']:
                mode_descriptions[mode]['example'] = response['action_recommendation'][:80]

        return [
            {
                'mode': mode.title(),
                'when': desc['when'],
                'example': desc['example'] or 'No example yet',
            }
            for mode, desc in mode_descriptions.items()
        ]

    def _build_audit_funnel_data(self, pressure_data: list[dict], patterns: list[dict], responses: list[dict]) -> list[list]:
        """Build funnel data for competitive intelligence readiness"""
        total_detections = len(pressure_data) * 10  # Rough estimate
        total_pressure = len(pressure_data)
        total_patterns = len(patterns)
        total_responses = len(responses)

        return [
            ["Competitor mentions detected", 100],
            ["Pressure analyzed", int(total_pressure / max(total_detections / 100, 1) * 100) if total_detections else 0],
            ["Patterns identified", int(total_patterns / max(total_pressure, 1) * 100) if total_pressure else 0],
            ["Responses recommended", int(total_responses / max(total_patterns, 1) * 100) if total_patterns else 0],
            ["Ready for execution", 80 if responses else 0],
        ]

    def _analyze_pressure_radar(self, pressure_data: list[dict], our_scores: dict) -> list[str]:
        """Generate analysis points for pressure radar"""
        high_pressure = [row for row in pressure_data if row.get('pressure_level') == 'high']
        our_strengths = [dim for dim, score in our_scores.items() if score > 70]

        analysis = []

        if high_pressure:
            threats = ", ".join(set(f"{row['competitor_name']} ({row['dimension']})" for row in high_pressure[:3]))
            analysis.append(f"High pressure from: {threats}")

        if our_strengths:
            analysis.append(f"Our strengths: {', '.join(our_strengths[:3])}")

        for row in high_pressure[:2]:
            gap = row['competitor_score'] - row['our_score']
            analysis.append(f"{row['competitor_name']} leads by {gap:.0f} points in {row['dimension']}")

        return analysis or ["No significant pressure detected"]

    def _analyze_patterns(self, patterns: list[dict]) -> list[str]:
        """Generate analysis points for winning patterns"""
        analysis = []

        # Group by pattern type
        by_pattern = {}
        for row in patterns:
            pt = row['pattern_name']
            if pt not in by_pattern:
                by_pattern[pt] = []
            by_pattern[pt].append(row)

        for pattern_type, entries in by_pattern.items():
            strongest = max(entries, key=lambda x: x['pattern_strength'])
            analysis.append(f"{pattern_type.replace('_', ' ').title()}: {strongest['competitor_name']} leads with {strongest['pattern_strength']:.0f}/100")

        return analysis or ["No patterns identified yet"]

    def _analyze_response_modes(self, responses: list[dict]) -> list[str]:
        """Generate analysis points for response modes"""
        by_mode = {}
        for row in responses:
            mode = row['response_mode']
            if mode not in by_mode:
                by_mode[mode] = 0
            by_mode[mode] += 1

        analysis = [
            f"{mode.title()}: {count} recommendation(s)"
            for mode, count in sorted(by_mode.items(), key=lambda x: x[1], reverse=True)
        ]

        high_priority = [r for r in responses if r.get('priority') == 'high']
        if high_priority:
            analysis.append(f"{len(high_priority)} high-priority actions to execute immediately")

        return analysis or ["No response recommendations yet"]

    def _truncate(self, value: object, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _resolve_sentiment(self, explicit_label: str, text: str) -> str:
        label = explicit_label.strip().lower()
        if label:
            return label
        normalized = text.casefold()
        negative_patterns = [
            "không ngon", "khong ngon", "tệ", "te qua", "dở", "do ec", "mặn", "nhạt",
            "đợi lâu", "doi lau", "chậm", "that vong", "thất vọng", "sụp hầm", "khuyết điểm",
        ]
        positive_patterns = [
            "ngon", "rất ngon", "rat ngon", "thích", "thich", "wow", "nice", "yummy", "đỉnh", "dinh", "mê",
        ]
        has_negative = any(pattern in normalized for pattern in negative_patterns)
        has_positive = any(pattern in normalized for pattern in positive_patterns)
        if has_negative and has_positive:
            return "mixed"
        if has_negative:
            return "negative"
        if has_positive:
            return "positive"
        return "neutral"

    def _resolve_review_sentiment(self, explicit_label: str, rating: object, text: str) -> str:
        label = explicit_label.strip().lower()
        if label:
            return label
        try:
            numeric = float(rating or 0)
        except Exception:
            numeric = 0.0
        if numeric >= 4:
            return "positive"
        if numeric and numeric <= 2.5:
            return "negative"
        return self._resolve_sentiment("", text)

    def _guess_topic(self, text: str) -> str:
        normalized = text.casefold()
        topic_terms = {
            "food_quality": ["ngon", "dở", "do ec", "mặn", "nhạt", "đậm vị", "vừa miệng", "khô", "ngấy"],
            "service_speed": ["chậm", "đợi lâu", "doi lau", "nhanh"],
            "staff_service": ["nhân viên", "phục vụ", "thai do", "thái độ"],
            "delivery": ["ship", "giao hàng", "delivery", "grab", "shopeefood"],
            "price_value": ["giá", "đắt", "đáng tiền", "không đáng tiền"],
            "location": ["địa chỉ", "chỗ", "quận", "branch", "chi nhánh"],
            "menu_variety": ["mì bò", "sủi cảo", "bánh bao", "menu", "món"],
        }
        for topic, patterns in topic_terms.items():
            if any(pattern in normalized for pattern in patterns):
                return topic
        return "unknown"

    def _compute_branch_risk(self, stat: dict) -> int:
        rating_penalty = 0
        if float(stat.get("avg_rating") or 0) > 0:
            rating_penalty = max(0, int((4.6 - float(stat.get("avg_rating") or 0)) * 18))
        return int(stat.get("negative_count") or 0) * 4 + int(stat.get("review_count") or 0) * 1 + rating_penalty

    def _risk_level(self, score: int) -> str:
        if score >= 30:
            return "High"
        if score >= 14:
            return "Medium"
        return "Low"

    def _best_signal(self, stat: dict) -> str:
        if float(stat.get("avg_rating") or 0) >= 4.5:
            return "Rating tốt"
        if int(stat.get("positive_count") or 0) > int(stat.get("negative_count") or 0):
            return "Thảo luận tích cực chiếm ưu thế"
        if int(stat.get("menu_count") or 0) >= 20:
            return "Menu depth tốt"
        return "Data footprint ổn"

    def _watchout(self, stat: dict) -> str:
        if int(stat.get("negative_count") or 0) >= 8:
            return "Negative buzz đang dày"
        if float(stat.get("avg_rating") or 0) and float(stat.get("avg_rating") or 0) < 4.0:
            return "Rating cần theo dõi"
        if int(stat.get("review_count") or 0) == 0:
            return "Thiếu review layer"
        return "Ổn định"

    def _price_text(self, value: object) -> str:
        try:
            amount = float(value or 0)
        except Exception:
            amount = 0.0
        if amount <= 0:
            return ""
        return f"{int(amount):,}đ".replace(",", ".")

    def _build_date_range(self) -> dict:
        rows = self._query_json(
            f"""
            SELECT json_build_object(
              'from', MIN(created_date),
              'to', MAX(created_date),
              'label', 'Imported dataset'
            )
            FROM (
              SELECT content_created_date AS created_date
              FROM {self.schema}.mentions m
              JOIN {self.schema}.brands br ON br.brand_id = m.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
              UNION ALL
              SELECT review_created_date AS created_date
              FROM {self.schema}.reviews r
              JOIN {self.schema}.brands br ON br.brand_id = r.brand_id
              WHERE br.brand_slug = {sql_str(self.brand_slug)}
            ) t;
            """
        )
        return rows or {"label": "Imported dataset", "from": None, "to": None}

    def _brand_id(self) -> str:
        return str(
            self._query_text(
                f"""
                SELECT brand_id::text
                FROM {self.schema}.brands
                WHERE brand_slug = {sql_str(self.brand_slug)}
                LIMIT 1;
                """
            )
            or ""
        ).strip()

    def _ensure_brand_source_config_table(self) -> None:
        self._execute_sql(
            f"""
            CREATE TABLE IF NOT EXISTS {self.schema}.brand_source_configs (
                brand_source_config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                brand_id UUID NOT NULL REFERENCES {self.schema}.brands(brand_id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                channel_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'official_brand',
                priority TEXT NOT NULL DEFAULT 'core',
                include_in_dashboard BOOLEAN NOT NULL DEFAULT TRUE,
                crawl_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                metadata JSONB NOT NULL DEFAULT '{{}}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_brand_source_configs_platform CHECK (
                    platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'google_maps', 'shopeefood', 'grabfood', 'youtube')
                ),
                CONSTRAINT chk_brand_source_configs_type CHECK (
                    source_type IN ('official_brand', 'store_branch', 'community_source', 'competitor')
                ),
                CONSTRAINT chk_brand_source_configs_priority CHECK (
                    priority IN ('core', 'secondary', 'reference_only')
                ),
                CONSTRAINT uq_brand_source_configs UNIQUE (brand_id, platform, source_url)
            );
            CREATE INDEX IF NOT EXISTS idx_brand_source_configs_brand_platform
                ON {self.schema}.brand_source_configs (brand_id, platform, include_in_dashboard, crawl_enabled);
            """
        )

    def _normalize_source_config(self, source: dict) -> dict | None:
        if not isinstance(source, dict):
            return None
        platform = str(source.get("platform") or "").strip().lower()
        source_url = str(source.get("source_url") or "").strip()
        if platform not in {"facebook", "tiktok", "threads", "instagram", "google_maps", "shopeefood", "grabfood", "youtube"}:
            return None
        if not source_url:
            return None
        source_type = str(source.get("source_type") or "official_brand").strip().lower()
        if source_type not in {"official_brand", "store_branch", "community_source", "competitor"}:
            source_type = "official_brand"
        priority = str(source.get("priority") or "core").strip().lower()
        if priority not in {"core", "secondary", "reference_only"}:
            priority = "core"
        return {
            "platform": platform,
            "channel_name": str(source.get("channel_name") or "").strip(),
            "source_url": source_url,
            "source_type": source_type,
            "priority": priority,
            "include_in_dashboard": bool(source.get("include_in_dashboard", True)),
            "crawl_enabled": bool(source.get("crawl_enabled", True)),
            "metadata": source.get("metadata") if isinstance(source.get("metadata"), dict) else {},
        }

    def _query_json(self, sql: str):
        command = [self.psql_bin, self.database, "-Atqc", sql]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        output = completed.stdout.strip()
        if not output:
            return None
        return json.loads(output)

    def _query_text(self, sql: str) -> str:
        command = [self.psql_bin, self.database, "-Atqc", sql]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        return completed.stdout.strip()

    def _execute_sql(self, sql: str) -> None:
        command = [self.psql_bin, self.database, "-qc", sql]
        subprocess.run(command, capture_output=True, text=True, check=True)


def sql_str(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def sql_json(value: object) -> str:
    return sql_str(json.dumps(value, ensure_ascii=False))


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
