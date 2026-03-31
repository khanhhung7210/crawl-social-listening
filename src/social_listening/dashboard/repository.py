from __future__ import annotations

from pymongo.collection import Collection

from social_listening.mongodb_sync import build_mongo_client


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
