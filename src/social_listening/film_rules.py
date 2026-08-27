"""Film alias matching for Distribution (mention → film_id).

Detection layer (v1.2) — per-film keyword sets:
  - core_keywords / ambiguous_keywords (+ legacy crawl fields)
  - context_keywords: required when term is ambiguous OR film.require_context
  - exclude_keywords: drop film if noise brand/phrase present
  - Word-boundary match for short single tokens
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from social_listening.film_classify import has_movie_context
from social_listening.paths import DATA_DIR

CATALOG_PATH = DATA_DIR / "distribution" / "film_catalog.json"
FILMS_DIR = DATA_DIR / "distribution" / "films"

AMBIGUOUS_MAX_LEN = 8
DEFAULT_MOVIE_CONTEXT = [
    "rap",
    "chieu",
    "ve",
    "trailer",
    "phim",
    "review",
    "suat",
    "cinema",
    "movie",
    "film",
    "imax",
    "bom tan",
    "watch",
]


def normalize(text: str) -> str:
    blob = (text or "").lower().replace("đ", "d").replace("Đ", "d")
    blob = unicodedata.normalize("NFD", blob)
    blob = "".join(ch for ch in blob if unicodedata.category(ch) != "Mn")
    blob = re.sub(r"[^a-z0-9#\s]+", " ", blob)
    return re.sub(r"\s+", " ", blob).strip()


def term_in_text(term: str, blob: str) -> bool:
    """True if normalized term appears in blob; short tokens use word boundaries."""
    t = normalize(term)
    if not t or not blob:
        return False
    if t.startswith("#") or " " in t or len(t) >= 5:
        return t in blob
    return bool(re.search(rf"(?<![a-z0-9#]){re.escape(t)}(?![a-z0-9])", blob))


@dataclass
class FilmDetectConfig:
    slug: str
    # (raw, norm, requires_context)
    terms: list[tuple[str, str, bool]] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    ambiguous_context: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    require_context: bool = False
    soft_exclude: list[str] = field(default_factory=list)
    listening_from: str | None = None


def _uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        t = str(v or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def _load_keyword_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _is_auto_ambiguous(norm: str) -> bool:
    if " " in norm or norm.startswith("#"):
        return False
    if len(norm) <= 4:
        return True
    return norm in {"minion", "minions", "odyssey", "spiderman", "spider"}


def _build_detect_config(
    slug: str,
    *,
    title: str = "",
    aliases: list[str] | None = None,
    payload: dict | None = None,
) -> FilmDetectConfig | None:
    payload = payload or {}
    if not slug:
        return None

    core = _uniq(
        list(payload.get("core_keywords") or [])
        + ([title] if title else [])
        + list(aliases or [])
    )
    ambiguous = set(normalize(x) for x in (payload.get("ambiguous_keywords") or []) if str(x).strip())
    crawl_terms = _uniq(
        list(payload.get("keywords") or [])
        + list(payload.get("sub_keywords") or [])
        + list(payload.get("hashtags") or [])
        + list(payload.get("listening_keywords") or [])
        + list(payload.get("boost_keywords") or [])
    )

    context = _uniq(list(payload.get("context_keywords") or []) + DEFAULT_MOVIE_CONTEXT)
    amb_context = _uniq(list(payload.get("ambiguous_context_keywords") or []))
    exclude = _uniq(list(payload.get("exclude_keywords") or []))
    soft_exclude = _uniq(list(payload.get("soft_exclude_keywords") or []))
    require_context = bool(payload.get("require_context", False))
    listening_from = str(payload.get("listening_from") or "").strip() or None

    seen: set[str] = set()
    terms: list[tuple[str, str, bool]] = []
    for raw in core + crawl_terms + list(payload.get("ambiguous_keywords") or []):
        raw = str(raw or "").strip()
        if not raw:
            continue
        norm = normalize(raw)
        if len(norm) < 2 or norm in seen:
            continue
        seen.add(norm)
        listed_amb = norm in ambiguous
        needs_ctx = require_context or listed_amb or _is_auto_ambiguous(norm)
        if (
            not require_context
            and not listed_amb
            and not _is_auto_ambiguous(norm)
            and raw in core
        ):
            needs_ctx = False
        terms.append((raw, norm, needs_ctx))

    terms.sort(key=lambda t: len(t[1]), reverse=True)
    return FilmDetectConfig(
        slug=slug,
        terms=terms,
        context=context,
        ambiguous_context=amb_context,
        exclude=exclude,
        require_context=require_context,
        soft_exclude=soft_exclude,
        listening_from=listening_from,
    )


def _load_film_detect_configs_from_db() -> list[FilmDetectConfig]:
    from social_listening.config.db_source import list_film_keyword_payloads_from_db

    configs: list[FilmDetectConfig] = []
    for payload in list_film_keyword_payloads_from_db(active_only=True):
        slug = str(payload.get("film_slug") or "").strip()
        title = str(payload.get("film_title") or "").strip()
        cfg = _build_detect_config(slug, title=title, aliases=[], payload=payload)
        if cfg:
            configs.append(cfg)
    return configs


def _load_film_detect_configs_from_files() -> list[FilmDetectConfig]:
    if not CATALOG_PATH.exists():
        return []
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    configs: list[FilmDetectConfig] = []

    for film in catalog.get("films") or []:
        if film.get("active") is False:
            continue
        slug = str(film.get("slug") or "").strip()
        if not slug:
            continue

        kw_rel = str(film.get("keyword_file") or f"films/{slug}.json")
        payload = _load_keyword_payload(DATA_DIR / "distribution" / kw_rel)
        cfg = _build_detect_config(
            slug,
            title=str(film.get("title") or ""),
            aliases=[str(a) for a in (film.get("aliases") or [])],
            payload=payload,
        )
        if cfg:
            configs.append(cfg)
    return configs


@lru_cache(maxsize=1)
def load_film_detect_configs() -> list[FilmDetectConfig]:
    if str(os.getenv("SOCIAL_CONFIG_SOURCE") or "file").strip().lower() == "db":
        try:
            configs = _load_film_detect_configs_from_db()
            if configs:
                return configs
        except Exception:
            pass
    return _load_film_detect_configs_from_files()


def _context_ok(blob: str, context_terms: list[str], *, strict: bool = False) -> bool:
    """True if any context term hits. strict=True → only listed terms (no DEFAULT movie words)."""
    if not context_terms:
        return False
    if any(term_in_text(w, blob) for w in context_terms):
        return True
    if strict:
        return False
    return has_movie_context(blob, context_terms)


def _excluded(blob: str, cfg: FilmDetectConfig) -> bool:
    return any(term_in_text(ex, blob) for ex in cfg.exclude)


def detect_film_slugs(text: str, matches: list[str] | None = None) -> list[str]:
    """Detect film slugs from content + matched crawl keywords."""
    blob = normalize(text)
    extra = normalize(" ".join(str(m) for m in (matches or []) if m))
    if extra:
        blob = f"{blob} {extra}".strip()

    found: list[str] = []
    for cfg in load_film_detect_configs():
        if _excluded(blob, cfg):
            continue

        matched = False
        general_ctx = _context_ok(blob, cfg.context, strict=False)
        # Franchise guards (Conan, Spider-Man…) must NOT pass on bare "movie/phim"
        amb_ctx = (
            _context_ok(blob, cfg.ambiguous_context, strict=True)
            if cfg.ambiguous_context
            else general_ctx
        )

        for _raw, alias_norm, needs_ctx in cfg.terms:
            if not term_in_text(alias_norm, blob):
                continue
            if needs_ctx or cfg.require_context:
                ok = amb_ctx if cfg.ambiguous_context else general_ctx
                if cfg.require_context:
                    ok = general_ctx
                if not ok:
                    continue
                matched = True
                break
            matched = True
            break

        if not matched:
            continue

        if cfg.soft_exclude and any(term_in_text(s, blob) for s in cfg.soft_exclude):
            film_specific = cfg.ambiguous_context or [
                c for c in cfg.context if len(normalize(c)) >= 6
            ]
            if not any(term_in_text(c, blob) for c in film_specific):
                continue

        if cfg.slug not in found:
            found.append(cfg.slug)
    return found


def film_listening_from(slug: str) -> str | None:
    for cfg in load_film_detect_configs():
        if cfg.slug == slug:
            return cfg.listening_from
    return None


def film_slug_from_path(path: Path) -> str | None:
    """Infer film slug from data/<platform>/processed/<film_slug>/..."""
    parts = [p.lower() for p in path.parts]
    try:
        idx = parts.index("processed")
        if idx + 1 < len(parts):
            candidate = parts[idx + 1]
            if candidate and candidate not in {"default_film"}:
                return candidate
    except ValueError:
        pass
    return None


def clear_alias_cache() -> None:
    load_film_detect_configs.cache_clear()


def load_film_alias_index():
    rows = []
    for cfg in load_film_detect_configs():
        for raw, norm, needs_ctx in cfg.terms:
            rows.append((cfg.slug, raw, norm, needs_ctx, tuple(cfg.context)))
    return rows
