from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from social_listening.text_utils import normalize_text

POSITIVE_TERMS = (
    "hay",
    "rất hay",
    "tuyệt",
    "tuyệt vời",
    "đỉnh",
    "xịn",
    "ổn",
    "ổn áp",
    "hấp dẫn",
    "mãn nhãn",
    "mong chờ",
    "đáng xem",
    "thích",
    "thích quá",
    "love",
    "good",
    "great",
    "xuất sắc",
)

NEGATIVE_TERMS = (
    "dở",
    "quá dở",
    "tệ",
    "quá tệ",
    "nhảm",
    "chán",
    "không hay",
    "dở ẹc",
    "khó hiểu",
    "thất vọng",
    "fail",
    "phèn",
    "cringe",
    "yếu",
    "không ổn",
    "tào lao",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "General": ("phim", "review", "xem", "ra rạp", "chiếu", "ending", "nội dung", "plot"),
    "Film": ("kịch bản", "trailer", "reel", "review phim", "cgi", "visual", "cảnh", "vfx"),
    "Character": ("diễn viên", "nhân vật", "cast", "vai diễn", "ryan gosling", "main", "actor", "actress"),
    "Brand image": ("brand", "campaign", "poster", "marketing", "truyền thông", "hình ảnh", "thương hiệu"),
}

MEDIA_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "Paid": ("agency", "booking", "ads", "quảng cáo", "book vé", "đặt vé", "sponsor"),
    "Owned": ("official", "studio", "galaxy", "cinema", "phim", "movie", "trailer", "teaser", "poster"),
    "Earned": (),
}


def build_dashboard_report(
    film_title: str,
    sentiment_rows: list[dict],
    social_rows: list[dict],
    available_films: list[str],
) -> dict:
    film_title = (film_title or "").strip()
    normalized_title = normalize_text(film_title)
    title_terms = tuple(token for token in normalized_title.split() if len(token) >= 3)

    sentiment_overview = summarize_sentiment(sentiment_rows)
    platform_breakdown = summarize_platforms(sentiment_rows, social_rows)
    source_breakdown = summarize_sources(social_rows, normalized_title, title_terms)
    media_type_breakdown = summarize_media_types(source_breakdown)
    platform_share = summarize_platform_share(social_rows)
    comment_analytics = summarize_comment_analytics(social_rows, normalized_title, title_terms)

    total_posts = len(social_rows)
    total_comments = sum(len(get_comments(row)) for row in social_rows)
    total_mentions = sum(item["buzz_volume"] for item in source_breakdown)
    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "film_title": film_title,
        "available_films": available_films,
        "generated_at": generated_at,
        "totals": {
            "posts": total_posts,
            "comments": total_comments,
            "mentions": total_mentions,
            "sources": len(source_breakdown),
        },
        "sentiment_overview": sentiment_overview,
        "platform_breakdown": platform_breakdown,
        "platform_share": platform_share,
        "media_type_breakdown": media_type_breakdown,
        "top_sources": source_breakdown[:8],
        "sentiment_by_topic": comment_analytics["topic_breakdown"],
        "feedback_examples": comment_analytics["feedback_examples"],
        "real_feedback_summary": comment_analytics["real_feedback_summary"],
        "methodology": {
            "positive_rules": [
                "Khen chất lượng phim, trailer, trải nghiệm xem hoặc đề xuất người khác đi xem.",
                "Bày tỏ mong muốn xem phim, quan tâm tới cast hoặc hoạt động truyền thông của phim.",
                "Bênh vực thương hiệu/phim bằng lập luận tích cực hoặc chia sẻ trải nghiệm tốt.",
            ],
            "negative_rules": [
                "Chê nội dung, diễn xuất, nhịp phim, kỹ xảo hoặc trải nghiệm truyền thông.",
                "Thể hiện ý định không xem, không ủng hộ hoặc so sánh bất lợi với phim khác.",
                "Chia sẻ lại nội dung tiêu cực, công kích cast/thương hiệu hoặc phản ứng khó chịu rõ ràng.",
            ],
        },
    }


def summarize_sentiment(sentiment_rows: list[dict]) -> dict:
    if sentiment_rows:
        positive = sum(int(row.get("positive") or 0) for row in sentiment_rows)
        negative = sum(int(row.get("negative") or 0) for row in sentiment_rows)
        neutral = sum(int(row.get("neutral") or 0) for row in sentiment_rows)
    else:
        positive = negative = neutral = 0
    total = positive + negative + neutral
    return {
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "total": total,
        "positive_ratio": safe_ratio(positive, total),
        "negative_ratio": safe_ratio(negative, total),
        "neutral_ratio": safe_ratio(neutral, total),
    }


def summarize_platforms(sentiment_rows: list[dict], social_rows: list[dict]) -> list[dict]:
    sentiment_by_platform = {
        normalize_text(str(row.get("platform") or "")): {
            "platform": str(row.get("platform") or "").strip(),
            "positive": int(row.get("positive") or 0),
            "negative": int(row.get("negative") or 0),
            "neutral": int(row.get("neutral") or 0),
            "total_comments": int(row.get("total_comments") or 0),
            "buzz_score": float(row.get("buzz_score") or 0),
        }
        for row in sentiment_rows
        if str(row.get("platform") or "").strip()
    }

    posts_by_platform = Counter(normalize_text(str(row.get("platform") or "")) for row in social_rows if row.get("platform"))
    platforms = sorted(set(posts_by_platform) | set(sentiment_by_platform))
    results: list[dict] = []
    for key in platforms:
        sentiment = sentiment_by_platform.get(key, {})
        total_comments = int(sentiment.get("total_comments") or 0)
        positive = int(sentiment.get("positive") or 0)
        negative = int(sentiment.get("negative") or 0)
        neutral = int(sentiment.get("neutral") or max(total_comments - positive - negative, 0))
        results.append(
            {
                "platform": sentiment.get("platform") or key,
                "posts": posts_by_platform.get(key, 0),
                "total_comments": total_comments,
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
                "positive_ratio": safe_ratio(positive, total_comments),
                "negative_ratio": safe_ratio(negative, total_comments),
                "buzz_score": float(sentiment.get("buzz_score") or 0),
            }
        )
    return sorted(results, key=lambda item: item["total_comments"], reverse=True)


def summarize_platform_share(social_rows: list[dict]) -> list[dict]:
    counts = Counter(str(row.get("platform") or "").strip() for row in social_rows if row.get("platform"))
    total = sum(counts.values())
    rows = [
        {"platform": platform, "count": count, "ratio": safe_ratio(count, total)}
        for platform, count in counts.items()
        if platform
    ]
    return sorted(rows, key=lambda item: item["count"], reverse=True)


def summarize_sources(social_rows: list[dict], normalized_title: str, title_terms: tuple[str, ...]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for row in social_rows:
        source = str(row.get("page_name") or row.get("source") or "Unknown source").strip()
        platform = str(row.get("platform") or "").strip()
        post_text = str(row.get("post_text") or "").strip()
        comments = get_comments(row)
        analyzable_texts = [post_text, *comments]
        mention_hits = sum(1 for text in analyzable_texts if is_brand_mention(text, normalized_title, title_terms))
        key_message_hits = sum(1 for text in analyzable_texts if is_key_message(text))
        buzz_volume = len(comments) + (1 if post_text else 0)
        entry = buckets.setdefault(
            source,
            {
                "source": source,
                "platform": platform,
                "page_type": infer_page_type(platform, source),
                "media_type": infer_media_type(source, post_text),
                "buzz_volume": 0,
                "posts": 0,
                "audience_scale": 0,
                "brand_hits": 0,
                "key_message_hits": 0,
                "analyzable_items": 0,
            },
        )
        entry["buzz_volume"] += buzz_volume
        entry["posts"] += 1
        entry["audience_scale"] += buzz_volume + max(len(post_text) // 120, 1 if post_text else 0)
        entry["brand_hits"] += mention_hits
        entry["key_message_hits"] += key_message_hits
        entry["analyzable_items"] += len([text for text in analyzable_texts if text.strip()])

    rows = []
    for entry in buckets.values():
        analyzable = entry.pop("analyzable_items")
        brand_hits = entry.pop("brand_hits")
        key_hits = entry.pop("key_message_hits")
        entry["brand_mention_rate"] = safe_ratio(brand_hits, analyzable)
        entry["key_message_rate"] = safe_ratio(key_hits, analyzable)
        rows.append(entry)

    return sorted(rows, key=lambda item: (item["buzz_volume"], item["posts"]), reverse=True)


def summarize_media_types(source_breakdown: list[dict]) -> list[dict]:
    counts = Counter(item["media_type"] for item in source_breakdown if item["media_type"])
    total = sum(counts.values())
    rows = [{"type": media_type, "count": count, "ratio": safe_ratio(count, total)} for media_type, count in counts.items()]
    return sorted(rows, key=lambda item: item["count"], reverse=True)


def summarize_comment_analytics(social_rows: list[dict], normalized_title: str, title_terms: tuple[str, ...]) -> dict:
    topic_counter: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[dict]] = {"positive": [], "negative": []}

    for row in social_rows:
        platform = str(row.get("platform") or "").strip()
        source = str(row.get("page_name") or row.get("source") or "Unknown source").strip()
        for text in get_comments(row):
            sentiment = detect_sentiment(text)
            topic = classify_topic(text)
            topic_counter[topic][sentiment] += 1
            topic_counter[topic]["total"] += 1
            if sentiment in ("positive", "negative") and len(examples[sentiment]) < 6:
                examples[sentiment].append(
                    {
                        "text": text,
                        "platform": platform,
                        "source": source,
                        "topic": topic,
                        "brand_match": is_brand_mention(text, normalized_title, title_terms),
                    }
                )

    topic_rows = []
    for topic, counter in topic_counter.items():
        topic_rows.append(
            {
                "topic": topic,
                "positive": counter.get("positive", 0),
                "negative": counter.get("negative", 0),
                "neutral": counter.get("neutral", 0),
                "total": counter.get("total", 0),
            }
        )
    topic_rows.sort(key=lambda item: item["total"], reverse=True)

    return {
        "topic_breakdown": topic_rows,
        "feedback_examples": examples,
        "real_feedback_summary": {
            "positive": sum(item["positive"] for item in topic_rows),
            "negative": sum(item["negative"] for item in topic_rows),
            "neutral": sum(item["neutral"] for item in topic_rows),
        },
    }


def get_comments(row: dict) -> list[str]:
    comments = row.get("comments_") or []
    if not isinstance(comments, list):
        return []
    return [str(comment).strip() for comment in comments if str(comment).strip()]


def infer_media_type(source: str, post_text: str) -> str:
    haystack = normalize_text(f"{source} {post_text}")
    for label, hints in MEDIA_TYPE_HINTS.items():
        if hints and any(hint in haystack for hint in hints):
            return label
    return "Earned"


def infer_page_type(platform: str, source: str) -> str:
    platform_key = normalize_text(platform)
    source_key = normalize_text(source)
    if "official" in source_key:
        return "Official channel"
    if platform_key == "facebook":
        return "Facebook page"
    if platform_key == "threads":
        return "Community page"
    if platform_key == "tiktok":
        return "TikTok account"
    if platform_key == "youtube":
        return "YouTube channel"
    return "Community source"


def classify_topic(text: str) -> str:
    haystack = normalize_text(text)
    best_topic = "General"
    best_hits = 0
    for topic, hints in TOPIC_KEYWORDS.items():
        hits = sum(1 for hint in hints if hint in haystack)
        if hits > best_hits:
            best_topic = topic
            best_hits = hits
    return best_topic


def detect_sentiment(text: str) -> str:
    haystack = normalize_text(text)
    positive_hits = sum(1 for term in POSITIVE_TERMS if term in haystack)
    negative_hits = sum(1 for term in NEGATIVE_TERMS if term in haystack)
    if positive_hits > negative_hits:
        return "positive"
    if negative_hits > positive_hits:
        return "negative"
    return "neutral"


def is_brand_mention(text: str, normalized_title: str, title_terms: Iterable[str]) -> bool:
    haystack = normalize_text(text)
    if normalized_title and normalized_title in haystack:
        return True
    return any(term in haystack for term in title_terms)


def is_key_message(text: str) -> bool:
    haystack = normalize_text(text)
    key_terms = ("ra rạp", "xem", "trailer", "review", "đáng xem", "mới", "chiếu", "phim")
    return any(term in haystack for term in key_terms)


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)
