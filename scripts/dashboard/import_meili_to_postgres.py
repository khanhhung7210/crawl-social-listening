from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import load_keyword_payload


BRAND_SLUG = "meili-mi-bo-dai-loan"
SCHEMA = "meili_dashboard"
PGDATABASE = os.getenv("PGDATABASE", "meili_dashboard")
PSQL_BIN = os.getenv("PSQL_BIN", "psql")
DEFAULT_KEYWORD_FILE = PROJECT_ROOT / "data" / "shared" / "social_keywords_meili_mi_bo_dai_loan.json"
SHOPEEFOOD_SIMULATOR_FULL_FILE = (
    PROJECT_ROOT / "data" / "shopeefood" / "raw" / "meili_mi_bo_dai_loan" / "shopeefood_simulator_full.json"
)


def main() -> int:
    keyword_payload = load_keyword_payload(DEFAULT_KEYWORD_FILE)
    social_mentions = []
    social_mentions.extend(load_json_array(PROJECT_ROOT / "data" / "facebook" / "processed" / "meili_mi_bo_dai_loan" / "facebook_keyword_mentions.json"))
    social_mentions.extend(load_json_array(PROJECT_ROOT / "data" / "tiktok" / "processed" / "meili_mi_bo_dai_loan" / "tiktok_keyword_mentions.json"))
    social_mentions.extend(load_json_array(PROJECT_ROOT / "data" / "threads" / "processed" / "meili_mi_bo_dai_loan" / "threads_keyword_mentions.json"))
    social_mentions.extend(load_json_array(PROJECT_ROOT / "data" / "instagram" / "processed" / "meili_mi_bo_dai_loan" / "instagram_keyword_mentions.json"))
    google_maps_mentions = load_json_array(
        PROJECT_ROOT / "data" / "google_maps" / "processed" / "meili_mi_bo_dai_loan" / "google_maps_keyword_mentions.json"
    )
    social_mentions.extend(google_maps_mentions)
    shopeefood_simulator_records = load_json_array(SHOPEEFOOD_SIMULATOR_FULL_FILE)

    branch_rows = build_branch_rows(keyword_payload, google_maps_mentions)
    branch_rows = merge_shopeefood_branch_data(branch_rows)
    branch_rows = merge_google_maps_branch_data(branch_rows, google_maps_mentions)
    sql = build_sql(branch_rows, social_mentions, shopeefood_simulator_records)
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
        handle.write(sql)
        sql_path = Path(handle.name)

    try:
        run_psql(sql_path)
    finally:
        try:
            sql_path.unlink()
        except FileNotFoundError:
            pass

    print(
        json.dumps(
            {
                "pg_database": PGDATABASE,
                "brand_slug": BRAND_SLUG,
                "branches": len(branch_rows),
                "social_mentions": len(social_mentions),
                "shopeefood_simulator_records": len(shopeefood_simulator_records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def load_json_array(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def build_branch_rows(keyword_payload: dict, google_maps_mentions: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    url_by_slug: dict[str, str] = {}
    for url in keyword_payload.get("shopeefood_urls") or []:
        slug = branch_slug_from_url(url)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        url_by_slug[slug] = str(url)
        rows.append(
            {
                "branch_slug": slug,
                "branch_name": humanize_branch_slug(slug),
                "external_branch_key": slug,
                "district": "",
                "city": "TP. HCM",
                "google_maps_url": "",
                "shopeefood_url": str(url),
                "aliases": [humanize_branch_slug(slug)],
            }
        )
    for item in google_maps_mentions:
        slug = map_google_maps_branch_slug(item)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append(
            {
                "branch_slug": slug,
                "branch_name": humanize_branch_slug(slug),
                "external_branch_key": slug,
                "district": "",
                "city": "TP. HCM",
                "google_maps_url": str(item.get("post_url") or ""),
                "shopeefood_url": url_by_slug.get(slug, ""),
                "aliases": [humanize_branch_slug(slug)],
            }
        )
    return rows


def merge_shopeefood_branch_data(branch_rows: list[dict]) -> list[dict]:
    payload = load_json_array(Path("/private/tmp/meili_shopeefood_all_shops.json"))
    if not payload:
        return branch_rows
    by_slug = {row["branch_slug"]: row for row in branch_rows}
    for item in payload:
        url = str(item.get("url") or "").strip()
        slug = branch_slug_from_url(url)
        if not slug or slug not in by_slug:
            continue
        metadata = item.get("shop_metadata") or {}
        api_payloads = item.get("api_payloads") or {}
        from_url_reply = (api_payloads.get("from_url") or {}).get("reply") or {}
        detail_reply = (api_payloads.get("detail") or {}).get("reply") or {}
        delivery_detail = detail_reply.get("delivery_detail") or {}

        row = by_slug[slug]
        row["branch_name"] = clean_branch_name(
            str(delivery_detail.get("name") or metadata.get("title") or row["branch_name"])
        )
        address = str(delivery_detail.get("address") or metadata.get("address") or "").strip()
        if address:
            row["address_line"] = address
            row["district"] = extract_district(address)
            row["city"] = extract_city(address) or row.get("city") or "TP. HCM"
        row["metadata"] = {
            "restaurant_id": from_url_reply.get("restaurant_id"),
            "delivery_id": from_url_reply.get("delivery_id") or ((item.get("api_hints") or {}).get("request_id")),
        }
    return list(by_slug.values())


def merge_google_maps_branch_data(branch_rows: list[dict], google_maps_mentions: list[dict]) -> list[dict]:
    by_slug = {row["branch_slug"]: row for row in branch_rows}
    for item in google_maps_mentions:
        slug = map_google_maps_branch_slug(item)
        if not slug or slug not in by_slug:
            continue
        row = by_slug[slug]
        page_name = clean_branch_name(str(item.get("page_name") or ""))
        if page_name:
            row["google_maps_url"] = str(item.get("post_url") or row.get("google_maps_url") or "")
            aliases = list(row.get("aliases") or [])
            if page_name not in aliases:
                aliases.append(page_name)
            row["aliases"] = aliases
    return list(by_slug.values())


def build_sql(branch_rows: list[dict], social_mentions: list[dict], shopeefood_simulator_records: list[dict]) -> str:
    statements = [
        f"SET search_path TO {SCHEMA}, public;",
        upsert_brand_sql(),
    ]
    for row in branch_rows:
        statements.append(upsert_branch_sql(row))
        if row.get("shopeefood_url"):
            statements.append(
                upsert_branch_platform_ref_sql(
                    branch_slug=row["branch_slug"],
                    platform="shopeefood",
                    platform_url=row["shopeefood_url"],
                    platform_entity_id=(row.get("metadata") or {}).get("delivery_id"),
                    platform_entity_name=row["branch_name"],
                )
            )
        if row.get("google_maps_url"):
            statements.append(
                upsert_branch_platform_ref_sql(
                    branch_slug=row["branch_slug"],
                    platform="google_maps",
                    platform_url=row["google_maps_url"],
                    platform_entity_id=row["branch_slug"],
                    platform_entity_name=row["branch_name"],
                )
            )
    for item in social_mentions:
        statements.extend(build_social_sql(item))
    for record in shopeefood_simulator_records:
        statements.extend(build_shopeefood_simulator_sql(record, branch_rows))
    return "\n".join(statement for statement in statements if statement.strip()) + "\n"


def upsert_brand_sql() -> str:
    return f"""
INSERT INTO {SCHEMA}.brands (brand_slug, brand_name, vertical, timezone_name)
VALUES ('{BRAND_SLUG}', 'Meili 美丽 - Mì Bò Đài Loan', 'fnb', 'Asia/Ho_Chi_Minh')
ON CONFLICT (brand_slug) DO UPDATE
SET brand_name = EXCLUDED.brand_name,
    updated_at = NOW();
""".strip()


def upsert_branch_sql(row: dict) -> str:
    metadata = row.get("metadata") or {}
    return f"""
INSERT INTO {SCHEMA}.branches (
  brand_id, branch_slug, branch_name, external_branch_key, address_line, district, city,
  google_maps_url, shopeefood_url, aliases, metadata
)
SELECT
  brand_id,
  {sql_str(row['branch_slug'])},
  {sql_str(row['branch_name'])},
  {sql_str(row['external_branch_key'])},
  {sql_str(row.get('address_line', ''))},
  {sql_str(row.get('district', ''))},
  {sql_str(row.get('city', ''))},
  {sql_str(row.get('google_maps_url', ''))},
  {sql_str(row.get('shopeefood_url', ''))},
  {sql_json(row.get('aliases', []))},
  {sql_json(metadata)}
FROM {SCHEMA}.brands
WHERE brand_slug = '{BRAND_SLUG}'
ON CONFLICT (brand_id, branch_slug) DO UPDATE
SET branch_name = EXCLUDED.branch_name,
    address_line = EXCLUDED.address_line,
    district = EXCLUDED.district,
    city = EXCLUDED.city,
    google_maps_url = EXCLUDED.google_maps_url,
    shopeefood_url = EXCLUDED.shopeefood_url,
    aliases = EXCLUDED.aliases,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();
""".strip()


def upsert_branch_platform_ref_sql(branch_slug: str, platform: str, platform_url: str, platform_entity_id: object, platform_entity_name: str) -> str:
    return f"""
INSERT INTO {SCHEMA}.branch_platform_refs (
  branch_id, platform, platform_entity_id, platform_entity_name, platform_url, metadata
)
SELECT
  b.branch_id,
  {sql_str(platform)},
  {sql_str(platform_entity_id)},
  {sql_str(platform_entity_name)},
  {sql_str(platform_url)},
  '{{}}'::jsonb
FROM {SCHEMA}.branches b
JOIN {SCHEMA}.brands br ON br.brand_id = b.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}' AND b.branch_slug = {sql_str(branch_slug)}
ON CONFLICT (branch_id, platform, platform_url) DO UPDATE
SET platform_entity_id = EXCLUDED.platform_entity_id,
    platform_entity_name = EXCLUDED.platform_entity_name,
    updated_at = NOW();
""".strip()


def build_social_sql(item: dict) -> list[str]:
    platform = str(item.get("platform") or "").strip()
    post_id = str(item.get("post_id") or "").strip()
    if not platform or not post_id:
        return []
    statements = [upsert_raw_document_sql(item, platform=platform, document_kind="mention_post", natural_key=f"{platform}:post:{post_id}")]
    statements.append(
        upsert_mention_sql(
            item=item,
            platform=platform,
            content_type="post",
            external_post_id=post_id,
            external_parent_id="",
            author_name=str(item.get("page_name") or ""),
            content_text=str(item.get("post_text") or ""),
            content_created_at=str(item.get("post_created_at") or ""),
            post_url=str(item.get("post_url") or ""),
            raw_payload=item,
            branch_slug=None,
        )
    )
    for comment in item.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        external_id = str(comment.get("external_id") or "").strip()
        if not external_id:
            continue
        statements.append(
            upsert_mention_sql(
                item=item,
                platform=platform,
                content_type=str(comment.get("record_type") or "comment"),
                external_post_id=external_id,
                external_parent_id=str(comment.get("parent_comment_id") or post_id),
                author_name=str(comment.get("author") or ""),
                content_text=str(comment.get("text") or ""),
                content_created_at=str(comment.get("created_at") or ""),
                post_url=str(comment.get("url") or item.get("post_url") or ""),
                raw_payload=comment,
                branch_slug=None,
            )
        )
        if platform == "google_maps" and str(comment.get("record_type") or "").strip().lower() == "review":
            statements.append(upsert_google_review_sql(item, comment))
    return statements


def build_shopeefood_sql(item: dict) -> list[str]:
    url = str(item.get("url") or "").strip()
    branch_slug = branch_slug_from_url(url)
    if not branch_slug:
        return []
    api_payloads = item.get("api_payloads") or {}
    from_url_reply = (api_payloads.get("from_url") or {}).get("reply") or {}
    detail_reply = (api_payloads.get("detail") or {}).get("reply") or {}
    delivery_detail = detail_reply.get("delivery_detail") or {}
    title = clean_branch_name(str(delivery_detail.get("name") or (item.get("shop_metadata") or {}).get("title") or ""))
    text_parts = [title, str(delivery_detail.get("address") or (item.get("shop_metadata") or {}).get("address") or "")]
    review_status = (item.get("review_status") or {}).get("status") or ""

    statements = [
        upsert_raw_document_sql(item, platform="shopeefood", document_kind="delivery_store", natural_key=f"shopeefood:store:{url or branch_slug}")
    ]
    statements.append(
        upsert_mention_sql(
            item={
                "platform": "shopeefood",
                "page_name": title,
                "page_id": str(from_url_reply.get("restaurant_id") or ""),
                "post_text": " | ".join(part for part in text_parts if part),
                "post_created_at": str(item.get("crawled_at") or ""),
                "post_url": url,
                "post_keyword_match": True,
                "parent_keyword_match": True,
                "fnb_relevance": {"is_relevant_fnb": True},
                "stats": {"review_status": review_status},
            },
            platform="shopeefood",
            content_type="post",
            external_post_id=str(from_url_reply.get("delivery_id") or branch_slug),
            external_parent_id="",
            author_name=title,
            content_text=" | ".join(part for part in text_parts if part),
            content_created_at=str(item.get("crawled_at") or ""),
            post_url=url,
            raw_payload=item,
            branch_slug=branch_slug,
            source_type="delivery_review",
        )
    )
    dishes_payload = ((api_payloads.get("dishes") or {}).get("reply") or {}).get("menu_infos") or []
    for menu in dishes_payload:
        for dish in menu.get("dishes") or []:
            statements.append(upsert_menu_item_sql(branch_slug, dish, item))
    return statements


def build_shopeefood_simulator_sql(record: dict, branch_rows: list[dict]) -> list[str]:
    branch_slug = map_shopeefood_branch_slug(record)
    if not branch_slug:
        return []
    branch_row = next((row for row in branch_rows if row.get("branch_slug") == branch_slug), None)
    branch_url = str((branch_row or {}).get("shopeefood_url") or "")
    name = str(record.get("name") or "").strip()
    if not is_meili_shopeefood_name(name):
        return []

    statements = [
        upsert_raw_document_sql(
            record,
            platform="shopeefood",
            document_kind="delivery_store",
            natural_key=f"shopeefood:simulator:{branch_slug}",
        ),
        upsert_mention_sql(
            item={
                "platform": "shopeefood",
                "page_name": name,
                "page_id": branch_slug,
                "post_text": name,
                "post_created_at": str(record.get("crawled_at") or ""),
                "post_url": branch_url,
                "post_keyword_match": True,
                "parent_keyword_match": True,
                "fnb_relevance": {"is_relevant_fnb": True},
                "stats": {
                    "rating": record.get("rating"),
                    "review_count": record.get("review_count"),
                    "review_screen_opened": record.get("review_screen_opened"),
                },
            },
            platform="shopeefood",
            content_type="post",
            external_post_id=f"simulator:{branch_slug}",
            external_parent_id="",
            author_name=name,
            content_text=name,
            content_created_at=str(record.get("crawled_at") or ""),
            post_url=branch_url,
            raw_payload=record,
            branch_slug=branch_slug,
            source_type="delivery_review",
        ),
    ]
    for dish in record.get("dishes") or []:
        if not isinstance(dish, dict):
            continue
        statements.append(upsert_simulator_menu_item_sql(branch_slug, dish, record))
    for review in record.get("reviews") or []:
        if not isinstance(review, dict):
            continue
        statements.append(upsert_shopeefood_review_sql(branch_slug, review, record, branch_url))
    return statements


def upsert_google_review_sql(item: dict, comment: dict) -> str:
    branch_slug = map_google_maps_branch_slug(item)
    branch_join = (
        f"LEFT JOIN {SCHEMA}.branches b ON b.brand_id = br.brand_id AND b.branch_slug = {sql_str(branch_slug)}"
        if branch_slug
        else f"LEFT JOIN {SCHEMA}.branches b ON FALSE"
    )
    external_review_id = str(comment.get("external_id") or "").strip()
    return f"""
INSERT INTO {SCHEMA}.reviews (
  brand_id, branch_id, platform, external_review_id, external_post_id, reviewer_name, review_url,
  review_text, rating, review_created_at, raw_payload
)
SELECT
  br.brand_id,
  b.branch_id,
  'google_maps',
  {sql_str(external_review_id)},
  {sql_str(item.get('post_id'))},
  {sql_str(comment.get('author'))},
  {sql_str(comment.get('url') or item.get('post_url') or '')},
  {sql_str(comment.get('text'))},
  {sql_num(comment.get('rating'))},
  {sql_timestamptz(comment.get('created_at'))},
  {sql_json(comment)}
FROM {SCHEMA}.brands br
{branch_join}
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (platform, external_review_id, COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)) DO UPDATE
SET external_post_id = EXCLUDED.external_post_id,
    reviewer_name = EXCLUDED.reviewer_name,
    review_url = EXCLUDED.review_url,
    review_text = EXCLUDED.review_text,
    rating = EXCLUDED.rating,
    review_created_at = EXCLUDED.review_created_at,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW();
""".strip()


def upsert_shopeefood_review_sql(branch_slug: str, review: dict, record: dict, branch_url: str) -> str:
    external_review_id = build_shopeefood_review_id(branch_slug, review)
    return f"""
INSERT INTO {SCHEMA}.reviews (
  brand_id, branch_id, platform, external_review_id, external_post_id, reviewer_name, review_url,
  review_text, rating, review_created_at, raw_payload
)
SELECT
  br.brand_id,
  b.branch_id,
  'shopeefood',
  {sql_str(external_review_id)},
  {sql_str(f"simulator:{branch_slug}")},
  {sql_str(review.get('author'))},
  {sql_str(branch_url)},
  {sql_str(review.get('text'))},
  {sql_num(review.get('star_bucket'))},
  {sql_timestamptz(review.get('created_at') or review.get('crawled_at') or record.get('crawled_at'))},
  {sql_json(review)}
FROM {SCHEMA}.brands br
JOIN {SCHEMA}.branches b ON b.brand_id = br.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}' AND b.branch_slug = {sql_str(branch_slug)}
ON CONFLICT (platform, external_review_id, COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)) DO UPDATE
SET external_post_id = EXCLUDED.external_post_id,
    reviewer_name = EXCLUDED.reviewer_name,
    review_url = EXCLUDED.review_url,
    review_text = EXCLUDED.review_text,
    rating = EXCLUDED.rating,
    review_created_at = EXCLUDED.review_created_at,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW();
""".strip()


def upsert_raw_document_sql(payload: dict, platform: str, document_kind: str, natural_key: str) -> str:
    source_url = payload.get("post_url") or payload.get("url") or payload.get("current_url") or ""
    captured_at = payload.get("post_created_at") or payload.get("crawled_at") or ""
    content_text = payload.get("post_text") or payload.get("title") or ""
    return f"""
INSERT INTO {SCHEMA}.raw_documents (
  brand_id, source_type, platform, document_kind, natural_key, source_url, captured_at, payload, content_text
)
SELECT
  brand_id,
  {sql_str(resolve_source_type(platform))},
  {sql_str(platform)},
  {sql_str(document_kind)},
  {sql_str(natural_key)},
  {sql_str(source_url)},
  {sql_timestamptz(captured_at)},
  {sql_json(payload)},
  {sql_str(content_text)}
FROM {SCHEMA}.brands
WHERE brand_slug = '{BRAND_SLUG}'
ON CONFLICT (platform, document_kind, natural_key) DO UPDATE
SET source_url = EXCLUDED.source_url,
    captured_at = EXCLUDED.captured_at,
    payload = EXCLUDED.payload,
    content_text = EXCLUDED.content_text;
""".strip()


def upsert_mention_sql(
    item: dict,
    platform: str,
    content_type: str,
    external_post_id: str,
    external_parent_id: str,
    author_name: str,
    content_text: str,
    content_created_at: str,
    post_url: str,
    raw_payload: dict,
    branch_slug: str | None,
    source_type: str | None = None,
) -> str:
    branch_join = (
        f"LEFT JOIN {SCHEMA}.branches b ON b.brand_id = br.brand_id AND b.branch_slug = {sql_str(branch_slug)}"
        if branch_slug
        else f"LEFT JOIN {SCHEMA}.branches b ON FALSE"
    )
    fnb_relevance = item.get("fnb_relevance") or {}
    engagement = item.get("stats") or {}
    return f"""
INSERT INTO {SCHEMA}.mentions (
  brand_id, branch_id, source_type, platform, content_type, external_post_id, external_parent_id,
  page_id, page_name, author_name, post_url, content_text, content_created_at,
  post_keyword_match, parent_keyword_match, engagement, raw_payload
)
SELECT
  br.brand_id,
  b.branch_id,
  {sql_str(source_type or resolve_source_type(platform))},
  {sql_str(platform)},
  {sql_str(normalize_content_type(content_type))},
  {sql_str(external_post_id)},
  {sql_str(external_parent_id)},
  {sql_str(item.get('page_id'))},
  {sql_str(item.get('page_name'))},
  {sql_str(author_name)},
  {sql_str(post_url)},
  {sql_str(content_text)},
  {sql_timestamptz(content_created_at)},
  {sql_bool(item.get('post_keyword_match'))},
  {sql_bool(item.get('parent_keyword_match'))},
  {sql_json(engagement)},
  {sql_json(raw_payload)}
FROM {SCHEMA}.brands br
{branch_join}
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (platform, content_type, external_post_id, COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)) DO UPDATE
SET external_parent_id = EXCLUDED.external_parent_id,
    page_id = EXCLUDED.page_id,
    page_name = EXCLUDED.page_name,
    author_name = EXCLUDED.author_name,
    post_url = EXCLUDED.post_url,
    content_text = EXCLUDED.content_text,
    content_created_at = EXCLUDED.content_created_at,
    post_keyword_match = EXCLUDED.post_keyword_match,
    parent_keyword_match = EXCLUDED.parent_keyword_match,
    engagement = EXCLUDED.engagement,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW();

INSERT INTO {SCHEMA}.mention_enrichments (
  mention_id, brand_id, branch_id, is_relevant_fnb, relevance_score, relevance_reason, enriched_at
)
SELECT
  m.mention_id,
  m.brand_id,
  m.branch_id,
  {sql_bool(fnb_relevance.get('is_relevant_fnb', True))},
  {sql_num(fnb_relevance.get('relevance_score', 0))},
  {sql_json({
      "positive_hits": fnb_relevance.get("positive_hits", []),
      "negative_hits": fnb_relevance.get("negative_hits", []),
      "branch_hits": fnb_relevance.get("branch_hits", []),
      "explicit_brand_hits": fnb_relevance.get("explicit_brand_hits", [])
  })},
  NOW()
FROM {SCHEMA}.mentions m
JOIN {SCHEMA}.brands br ON br.brand_id = m.brand_id
LEFT JOIN {SCHEMA}.branches b ON b.branch_id = m.branch_id
WHERE br.brand_slug = '{BRAND_SLUG}'
  AND m.platform = {sql_str(platform)}
  AND m.content_type = {sql_str(normalize_content_type(content_type))}
  AND m.external_post_id = {sql_str(external_post_id)}
  AND (({sql_str(branch_slug)} IS NULL AND m.branch_id IS NULL) OR (b.branch_slug = {sql_str(branch_slug)}))
ON CONFLICT (mention_id) DO UPDATE
SET is_relevant_fnb = EXCLUDED.is_relevant_fnb,
    relevance_score = EXCLUDED.relevance_score,
    relevance_reason = EXCLUDED.relevance_reason,
    enriched_at = NOW();
""".strip()


def upsert_menu_item_sql(branch_slug: str, dish: dict, payload: dict) -> str:
    price_text = str(dish.get("display_price") or ((dish.get("price") or {}).get("text")) or "").strip()
    return f"""
INSERT INTO {SCHEMA}.menu_items (
  brand_id, branch_id, platform, external_item_id, item_name, normalized_item_name,
  item_description, price_amount, price_currency, captured_at, raw_payload
)
SELECT
  br.brand_id,
  b.branch_id,
  'shopeefood',
  {sql_str(dish.get('id'))},
  {sql_str(dish.get('name'))},
  {sql_str(normalize_name(dish.get('name')))},
  {sql_str(dish.get('description'))},
  {sql_num(parse_price(price_text))},
  'VND',
  {sql_timestamptz(payload.get('crawled_at'))},
  {sql_json(dish)}
FROM {SCHEMA}.brands br
JOIN {SCHEMA}.branches b ON b.brand_id = br.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}' AND b.branch_slug = {sql_str(branch_slug)}
ON CONFLICT (platform, COALESCE(external_item_id, normalized_item_name, item_name), COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)) DO UPDATE
SET item_description = EXCLUDED.item_description,
    price_amount = EXCLUDED.price_amount,
    captured_at = EXCLUDED.captured_at,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW();
""".strip()


def upsert_simulator_menu_item_sql(branch_slug: str, dish: dict, payload: dict) -> str:
    return f"""
INSERT INTO {SCHEMA}.menu_items (
  brand_id, branch_id, platform, external_item_id, item_name, normalized_item_name,
  item_description, price_amount, price_currency, captured_at, raw_payload
)
SELECT
  br.brand_id,
  b.branch_id,
  'shopeefood',
  NULL,
  {sql_str(dish.get('name'))},
  {sql_str(normalize_name(dish.get('name')))},
  {sql_str(dish.get('description'))},
  {sql_num(parse_price(str(dish.get('price') or '')))},
  'VND',
  {sql_timestamptz(payload.get('crawled_at'))},
  {sql_json(dish)}
FROM {SCHEMA}.brands br
JOIN {SCHEMA}.branches b ON b.brand_id = br.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}' AND b.branch_slug = {sql_str(branch_slug)}
ON CONFLICT (platform, COALESCE(external_item_id, normalized_item_name, item_name), COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)) DO UPDATE
SET item_description = EXCLUDED.item_description,
    price_amount = EXCLUDED.price_amount,
    captured_at = EXCLUDED.captured_at,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW();
""".strip()


def run_psql(sql_path: Path) -> None:
    command = [PSQL_BIN, PGDATABASE, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)]
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


def branch_slug_from_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    path = unquote(urlparse(text).path or "").strip("/")
    if not path:
        return ""
    last = path.split("/")[-1]
    for slug in ("nhieu-tu", "ung-van-khiem", "mai-van-vinh", "nguyen-van-khoi"):
        if slug in last:
            return slug
    return ""


def map_google_maps_branch_slug(item: dict) -> str:
    page_name = str(item.get("page_name") or "").lower()
    address = str((item.get("stats") or {}).get("address") or "").lower()
    haystack = f"{page_name} {address}"
    if "gò vấp" in haystack or "go vap" in haystack or "nguyễn văn khối" in haystack or "nguyen van khoi" in haystack:
        return "nguyen-van-khoi"
    if "quận 7" in haystack or "quan 7" in haystack or "mai văn vĩnh" in haystack or "mai van vinh" in haystack:
        return "mai-van-vinh"
    if "phú nhuận" in haystack or "phu nhuan" in haystack or "nhiêu tứ" in haystack or "nhieu tu" in haystack:
        return "nhieu-tu"
    if "bình thạnh" in haystack or "binh thanh" in haystack or "ung văn khiêm" in haystack or "ung van khiem" in haystack:
        return "ung-van-khiem"
    return ""


def map_shopeefood_branch_slug(record: dict) -> str:
    search_query = str(record.get("search_query") or "").lower()
    name = str(record.get("name") or "").lower()
    haystack = f"{search_query} {name}"
    if "nguyễn văn khối" in haystack or "nguyen van khoi" in haystack or "gò vấp" in haystack or "go vap" in haystack:
        return "nguyen-van-khoi"
    if "mai văn vĩnh" in haystack or "mai van vinh" in haystack or "quận 7" in haystack or "quan 7" in haystack:
        return "mai-van-vinh"
    if "nhiêu tứ" in haystack or "nhieu tu" in haystack or "phú nhuận" in haystack or "phu nhuan" in haystack:
        return "nhieu-tu"
    if "ung văn khiêm" in haystack or "ung van khiem" in haystack or "bình thạnh" in haystack or "binh thanh" in haystack:
        return "ung-van-khiem"
    return ""


def humanize_branch_slug(slug: str) -> str:
    mapping = {
        "nhieu-tu": "Nhiêu Tứ",
        "ung-van-khiem": "Ung Văn Khiêm",
        "mai-van-vinh": "Mai Văn Vĩnh",
        "nguyen-van-khoi": "Nguyễn Văn Khối",
    }
    return mapping.get(slug, slug.replace("-", " ").title())


def clean_branch_name(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"\s*-\s*Google Maps$", "", text, flags=re.I)
    return text


def is_meili_shopeefood_name(name: str) -> bool:
    lower = str(name or "").casefold()
    return "meili" in lower or "mì bò đài loan" in lower or "mi bo dai loan" in lower


def extract_district(address: str) -> str:
    for pattern in (r"(Phú Nhuận)", r"(Bình Thạnh)", r"(Quận\s*7)", r"(Gò Vấp)"):
        match = re.search(pattern, address, re.I)
        if match:
            return match.group(1)
    return ""


def extract_city(address: str) -> str:
    match = re.search(r"(TP\.\s*HCM|Hồ Chí Minh|Ho Chi Minh)", address, re.I)
    return match.group(1) if match else ""


def normalize_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def parse_price(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def build_shopeefood_review_id(branch_slug: str, review: dict) -> str:
    basis = "|".join(
        [
            branch_slug,
            str(review.get("author") or "").strip(),
            str(review.get("created_at") or "").strip(),
            str(review.get("text") or "").strip(),
            str(review.get("star_bucket") or "").strip(),
        ]
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()
    return f"shopeefood:{branch_slug}:{digest}"


def resolve_source_type(platform: str) -> str:
    if platform in {"google_maps", "shopeefood"}:
        return "delivery_review" if platform == "shopeefood" else "maps"
    return "social"


def normalize_content_type(value: str) -> str:
    text = str(value or "post").strip().lower()
    if text in {"comment", "reply", "review", "post"}:
        return text
    return "post"


def sql_str(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def sql_json(value: object) -> str:
    return sql_str(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def sql_timestamptz(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "NULL"
    return sql_str(text) + "::timestamptz"


def sql_bool(value: object) -> str:
    return "TRUE" if bool(value) else "FALSE"


def sql_num(value: object) -> str:
    if value in (None, ""):
        return "NULL"
    try:
        return str(float(value))
    except Exception:
        return "NULL"


if __name__ == "__main__":
    raise SystemExit(main())
