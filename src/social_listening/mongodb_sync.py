from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from pymongo import MongoClient, UpdateOne


@dataclass(frozen=True)
class MongoSyncConfig:
    input_file: Path
    input_label: str
    film_title: str


def describe_mongo_target() -> dict[str, object]:
    mongo_uri = os.getenv("MONGO_URI", "").strip()
    db_name = os.getenv("MONGO_DB", "CRM")
    collection_name = os.getenv("MONGO_COLLECTION", "")
    if mongo_uri:
        redacted_uri = redact_mongo_uri(mongo_uri)
        return {
            "mode": "uri",
            "uri": redacted_uri,
            "db": db_name,
            "collection": collection_name,
        }

    host = os.getenv("MONGO_HOST", "localhost").strip()
    port = int(os.getenv("MONGO_PORT", "27018"))
    user = os.getenv("MONGO_USER", "konis")
    password = os.getenv("MONGO_PASSWORD", "")
    auth_source = os.getenv("MONGO_AUTH_SOURCE", db_name)
    return {
        "mode": "host_port",
        "host": host,
        "port": port,
        "db": db_name,
        "collection": collection_name,
        "auth_source": auth_source if user and password else "",
        "has_auth": bool(user and password),
    }


def sync_json_file(config: MongoSyncConfig) -> int:
    if not config.input_file.exists():
        raise RuntimeError(f"Missing input file: {config.input_file}")

    payload = json.loads(config.input_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"{config.input_label} must be a JSON array")

    documents = [build_mongo_document(item, config.film_title) for item in payload if isinstance(item, dict)]
    documents = [doc for doc in documents if doc]
    if not documents:
        print("no documents to sync")
        return 0

    db_name = os.getenv("MONGO_DB", "CRM")
    collection_name = os.getenv("MONGO_COLLECTION", "social")
    client = build_mongo_client()
    collection = client[db_name][collection_name]

    operations = [
        UpdateOne(
            {"platform": doc["platform"], "post_id": doc["post_id"]},
            {"$set": doc},
            upsert=True,
        )
        for doc in documents
    ]
    result = collection.bulk_write(operations, ordered=False)
    print(
        "synced "
        f"{len(documents)} docs to {db_name}.{collection_name} "
        f"(upserted={result.upserted_count}, modified={result.modified_count}, matched={result.matched_count})"
    )
    return 0


def sync_preformatted_json_file(config: MongoSyncConfig) -> int:
    if not config.input_file.exists():
        raise RuntimeError(f"Missing input file: {config.input_file}")

    payload = json.loads(config.input_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"{config.input_label} must be a JSON array")

    documents = [normalize_preformatted_document(item, config.film_title) for item in payload if isinstance(item, dict)]
    documents = [doc for doc in documents if doc]
    if not documents:
        print("no documents to sync")
        return 0

    db_name = os.getenv("MONGO_DB", "CRM")
    collection_name = os.getenv("MONGO_COLLECTION", "social")
    client = build_mongo_client()
    collection = client[db_name][collection_name]

    operations = [
        UpdateOne(
            {"platform": doc["platform"], "post_id": doc["post_id"]},
            {"$set": doc},
            upsert=True,
        )
        for doc in documents
    ]
    result = collection.bulk_write(operations, ordered=False)
    print(
        "synced "
        f"{len(documents)} docs to {db_name}.{collection_name} "
        f"(upserted={result.upserted_count}, modified={result.modified_count}, matched={result.matched_count})"
    )
    return 0


def build_mongo_client() -> MongoClient:
    mongo_uri = os.getenv("MONGO_URI", "").strip()
    host = os.getenv("MONGO_HOST", "localhost").strip()
    port = int(os.getenv("MONGO_PORT", "27018"))
    db_name = os.getenv("MONGO_DB", "CRM")
    user = os.getenv("MONGO_USER", "konis")
    password = os.getenv("MONGO_PASSWORD", "")
    auth_source = os.getenv("MONGO_AUTH_SOURCE", db_name)
    app_name = os.getenv("MONGO_APP_NAME", "mongosh+1.8.0")

    if mongo_uri:
        return MongoClient(mongo_uri, serverSelectionTimeoutMS=10000, directConnection=True)

    if user and password:
        uri = (
            f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/"
            f"?directConnection=true&appName={quote_plus(app_name)}&authSource={quote_plus(auth_source)}"
        )
        return MongoClient(uri, directConnection=True, serverSelectionTimeoutMS=10000)

    uri = f"mongodb://{host}:{port}/?directConnection=true&appName={quote_plus(app_name)}"
    return MongoClient(uri, directConnection=True, serverSelectionTimeoutMS=10000)


def redact_mongo_uri(uri: str) -> str:
    return quote_password_placeholder(uri)


def quote_password_placeholder(uri: str) -> str:
    match = uri.split("://", 1)
    if len(match) != 2:
        return uri
    scheme, rest = match
    if "@" not in rest or ":" not in rest.split("@", 1)[0]:
        return uri
    creds, tail = rest.split("@", 1)
    user, _password = creds.split(":", 1)
    return f"{scheme}://{user}:***@{tail}"


def normalize_preformatted_document(item: dict, film_title: str) -> dict:
    platform = stringify(item.get("platform"))
    post_id = item.get("post_id")
    if not platform or post_id in (None, ""):
        return {}

    document = {key: value for key, value in item.items() if key != "_id"}
    if not stringify(document.get("film_title")) and film_title:
        document["film_title"] = film_title
    return document


def build_mongo_document(item: dict, film_title: str) -> dict:
    platform = stringify(item.get("platform"))
    post_id = stringify(item.get("post_id"))
    if not platform or not post_id:
        return {}

    comments = [comment for comment in item.get("comments") or [] if isinstance(comment, dict)]
    comment_texts = [stringify(comment.get("text")) for comment in comments if stringify(comment.get("text"))]

    return {
        "id": stable_numeric_id(platform, post_id),
        "platform": platform,
        "post_id": post_id,
        "page_id": stringify(item.get("page_id")),
        "page_name": stringify(item.get("page_name")),
        "post_text": stringify(item.get("post_text")),
        "comments_": comment_texts,
        "comments": comments,
        "created_at_comment": pick_latest_comment_timestamp(comments),
        "post_created_at": stringify(item.get("post_created_at")),
        "film_title": film_title or normalize_film_title(platform, stringify(item.get("post_text"))),
        "post_url": stringify(item.get("post_url")),
        "source": stringify(item.get("source")),
        "source_file": stringify(item.get("source_file")),
        "parent_keyword_match": bool(item.get("parent_keyword_match")),
        "post_keyword_match": bool(item.get("post_keyword_match")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def stringify(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def pick_latest_comment_timestamp(comments: list[dict]) -> str:
    values: list[datetime] = []
    for comment in comments:
        created_at = stringify(comment.get("created_at"))
        if not created_at:
            continue
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        values.append(dt.astimezone(timezone.utc))
    if not values:
        return ""
    return max(values).isoformat()


def stable_numeric_id(platform: str, post_id: str) -> int:
    digest = hashlib.sha1(f"{platform}:{post_id}".encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)


def normalize_film_title(source: str, post_text: str) -> str:
    value = source or post_text
    normalized = unicodedata.normalize("NFD", value)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = " ".join(normalized.upper().split())
    return normalized[:80]
