"""Film alias matching for Distribution (mention → film_id).

Detection layer (v1.3) — per-film keyword sets:
  - core_keywords / title / film-specific aliases: direct film identifiers
  - discovery / person / cast crawl keywords: used to FIND posts only — never
    assign film_id unless content also has a core film signal
  - ambiguous_keywords: need movie/franchise context
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

# Term match modes for FilmDetectConfig.terms
MODE_CORE = "core"  # direct accept
MODE_CONTEXT = "context"  # needs movie/franchise context
MODE_DISCOVERY = "discovery"  # needs a core film signal in the same text


def normalize(text: str) -> str:
    blob = (text or "").lower().replace("đ", "d").replace("Đ", "d")
    blob = unicodedata.normalize("NFD", blob)
    blob = "".join(ch for ch in blob if unicodedata.category(ch) != "Mn")
    blob = re.sub(r"[^a-z0-9#\s]+", " ", blob)
    return re.sub(r"\s+", " ", blob).strip()


def term_in_text(term: str, blob: str) -> bool:
    """True if normalized term appears in blob; single tokens use word boundaries."""
    t = normalize(term)
    if not t or not blob:
        return False
    if t.startswith("#"):
        bare = t.lstrip("#")
        return t in blob or (bare and bare in blob)
    if " " in t:
        return t in blob
    return bool(re.search(rf"(?<![a-z0-9#]){re.escape(t)}(?![a-z0-9])", blob))


@dataclass
class FilmDetectConfig:
    slug: str
    # (raw, norm, mode) — mode in {MODE_CORE, MODE_CONTEXT, MODE_DISCOVERY}
    terms: list[tuple[str, str, str]] = field(default_factory=list)
    core_norms: set[str] = field(default_factory=set)
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


def _protected_identifier_norms(title: str, aliases: list[str]) -> set[str]:
    """Norms that must remain film identifiers (title + film-specific aliases).

    Multi-word aliases (e.g. "Dear You") protect their compact hashtag form
    (#DearYou). Bare cast hashtags like #HuynhLap are intentionally excluded.
    """
    prot: set[str] = set()

    def _add(raw: str) -> None:
        n = normalize(raw)
        if not n:
            return
        prot.add(n)
        bare = n.lstrip("#").replace(" ", "")
        if bare:
            prot.add(bare)
            prot.add(f"#{bare}")

    _add(title)
    title_norm = normalize(title)
    title_compact = title_norm.replace(" ", "")
    title_tokens = [t for t in title_norm.split() if len(t) >= 4]

    for raw in aliases:
        n = normalize(raw)
        if not n:
            continue
        bare = n.lstrip("#").replace(" ", "")
        if " " in n or any(m in n for m in ("phim", "movie", "film", "trailer", "review")):
            _add(raw)
            continue
        if re.fullmatch(r"phim.+\d{4}", bare) or re.search(r"movie\s*\d+", n):
            _add(raw)
            continue
        if title_compact and len(bare) >= 6 and (bare in title_compact or title_compact in bare):
            _add(raw)
            continue
        if title_norm and (title_norm in n or (len(n) >= 6 and n in title_norm)):
            _add(raw)
            continue
        if any(t in n or t in bare for t in title_tokens):
            _add(raw)
            continue
        # Skip bare cast/person hashtags and names — not protected
    return prot


def _is_cast_discovery_term(raw: str, title: str, protected: set[str]) -> bool:
    """True for person/cast tokens that must not identify a film alone.

    Uses only string shape + title overlap — no external data. Protected norms
    (title + film-specific aliases like "Dear You" / #DearYou) are kept.
    """
    norm = normalize(raw)
    if not norm:
        return False
    bare = norm.lstrip("#").replace(" ", "")
    if norm in protected or bare in protected or (f"#{bare}" in protected):
        return False

    title_norm = normalize(title)
    title_compact = title_norm.replace(" ", "")
    if title_norm and (norm == title_norm or title_norm in norm or (len(norm) >= 6 and norm in title_norm)):
        return False
    if title_compact and len(bare) >= 6 and (bare in title_compact or title_compact in bare):
        return False
    title_tokens = [t for t in title_norm.split() if len(t) >= 4]
    if any(t in norm or t in bare for t in title_tokens):
        return False

    if any(m in norm for m in ("phim", "movie", "film", "trailer", "review", "cinema")):
        return False
    if re.fullmatch(r"phim.+\d{4}", bare):
        return False
    if re.search(r"movie\s*\d+", norm):
        return False

    # Cast hashtag without film title tokens (#HuynhLap, #ThuTrang, …)
    if norm.startswith("#") and bare.isalpha() and 4 <= len(bare) <= 28:
        return True

    # Bare person name (2–3 alpha tokens) that is not the film title
    words = [w for w in norm.split() if w]
    if 2 <= len(words) <= 3 and all(w.isalpha() and 2 <= len(w) <= 14 for w in words):
        if title_tokens and not any(t in words for t in title_tokens):
            return True
    return False


def _has_core_signal(blob: str, core_norms: set[str]) -> bool:
    return any(term_in_text(core, blob) for core in core_norms)


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

    alias_list = [str(a).strip() for a in (aliases or []) if str(a).strip()]
    protected = _protected_identifier_norms(title, alias_list)
    discovery_listed = {
        normalize(x) for x in (payload.get("discovery_keywords") or []) if str(x).strip()
    }

    raw_core = _uniq(
        list(payload.get("core_keywords") or [])
        + ([title] if title else [])
        + alias_list
    )
    # Drop cast/person tokens even if they were wrongly stored as core/aliases
    core = [
        c
        for c in raw_core
        if normalize(c) not in discovery_listed
        and not _is_cast_discovery_term(c, title, protected)
    ]
    if title and title not in core:
        core = _uniq([title] + core)

    ambiguous = set(normalize(x) for x in (payload.get("ambiguous_keywords") or []) if str(x).strip())
    crawl_terms = _uniq(
        list(payload.get("keywords") or [])
        + list(payload.get("sub_keywords") or [])
        + list(payload.get("hashtags") or [])
        + list(payload.get("listening_keywords") or [])
        + list(payload.get("boost_keywords") or [])
        + list(payload.get("discovery_keywords") or [])
        + [c for c in raw_core if c not in core]  # demoted cast terms still crawlable for detection mode
    )

    context = _uniq(list(payload.get("context_keywords") or []) + DEFAULT_MOVIE_CONTEXT)
    amb_context = _uniq(list(payload.get("ambiguous_context_keywords") or []))
    exclude = _uniq(list(payload.get("exclude_keywords") or []))
    soft_exclude = _uniq(list(payload.get("soft_exclude_keywords") or []))
    require_context = bool(payload.get("require_context", False))
    listening_from = str(payload.get("listening_from") or "").strip() or None

    core_norms = {normalize(x) for x in core if normalize(x)}
    # Short/franchise tokens keep core_norms for discovery checks but need context to match
    context_required_core = {
        n for n in core_norms if n in ambiguous or _is_auto_ambiguous(n)
    }

    seen: set[str] = set()
    terms: list[tuple[str, str, str]] = []

    def _add(raw: str, mode: str) -> None:
        raw = str(raw or "").strip()
        if not raw:
            return
        norm = normalize(raw)
        if len(norm) < 2 or norm in seen:
            return
        seen.add(norm)
        terms.append((raw, norm, mode))

    for raw in core:
        norm = normalize(raw)
        if norm in context_required_core:
            _add(raw, MODE_CONTEXT)
        else:
            _add(raw, MODE_CORE)

    for raw in list(payload.get("ambiguous_keywords") or []):
        norm = normalize(raw)
        if not norm or norm in core_norms:
            continue
        _add(raw, MODE_CONTEXT)

    # Discovery / person crawl terms — never accept without a core film signal
    for raw in crawl_terms:
        raw = str(raw or "").strip()
        if not raw:
            continue
        norm = normalize(raw)
        if len(norm) < 2 or norm in seen or norm in core_norms:
            continue
        if norm in ambiguous or _is_auto_ambiguous(norm):
            _add(raw, MODE_CONTEXT)
            continue
        if (
            norm in discovery_listed
            or _is_cast_discovery_term(raw, title, protected)
            or require_context
        ):
            _add(raw, MODE_DISCOVERY)
            continue
        # Remaining crawl phrases (e.g. "xem Nghỉ Hè…") — still require core
        # signal so person+generic-movie chatter cannot claim the film.
        _add(raw, MODE_DISCOVERY)

    terms.sort(key=lambda t: len(t[1]), reverse=True)
    return FilmDetectConfig(
        slug=slug,
        terms=terms,
        core_norms=core_norms,
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
    source = str(os.getenv("SOCIAL_CONFIG_SOURCE") or "auto").strip().lower()
    if source in {"db", "auto"}:
        try:
            configs = _load_film_detect_configs_from_db()
            if configs or source == "db":
                return configs
        except Exception:
            if source == "db":
                raise
    return _load_film_detect_configs_from_files()


def _context_ok(blob: str, context_terms: list[str], *, strict: bool = False) -> bool:
    """True if any context term hits (word-boundary safe)."""
    if not context_terms:
        return False
    if any(term_in_text(w, blob) for w in context_terms):
        return True
    if strict:
        return False
    return any(term_in_text(w, blob) for w in DEFAULT_MOVIE_CONTEXT)


def _excluded(blob: str, cfg: FilmDetectConfig) -> bool:
    return any(term_in_text(ex, blob) for ex in cfg.exclude)


def get_film_detect_config(slug: str) -> FilmDetectConfig | None:
    target = slug.strip().lower()
    for cfg in load_film_detect_configs():
        if cfg.slug == target:
            return cfg
    return None


def has_core_film_signal(text: str, slug: str) -> bool:
    cfg = get_film_detect_config(slug)
    if not cfg or not cfg.core_norms:
        return False
    blob = normalize(text)
    return _has_core_signal(blob, cfg.core_norms)


def match_is_core_identifier(match: str, slug: str | None = None) -> bool:
    """True when a crawl keyword match is itself a direct film identifier."""
    blob = normalize(match)
    if not blob:
        return False
    configs = load_film_detect_configs()
    if slug:
        configs = [c for c in configs if c.slug == slug.strip().lower()]
    for cfg in configs:
        if _has_core_signal(blob, cfg.core_norms) or blob in cfg.core_norms:
            return True
    return False


def film_relevant_for_slug(text: str, slug: str, *, strict: bool = False) -> bool:
    """True when normalized text is about the given film slug."""
    target = slug.strip().lower()
    if not target:
        return False
    found = detect_film_slugs(text or "", None)
    if target not in [s.lower() for s in found]:
        return False
    if not strict:
        return True
    return has_core_film_signal(text, target)


def detect_film_slugs(text: str, matches: list[str] | None = None) -> list[str]:
    """Detect film slugs from content (+ core crawl keyword matches only).

    Discovery/person keyword matches are NOT folded into the text blob — a hit
    on "Huỳnh Lập" alone must not assign the film.
    """
    blob = normalize(text)
    configs = load_film_detect_configs()

    core_match_bits: list[str] = []
    for m in matches or []:
        if not m:
            continue
        m_norm = normalize(str(m))
        if not m_norm:
            continue
        if any(m_norm in cfg.core_norms or _has_core_signal(m_norm, cfg.core_norms) for cfg in configs):
            core_match_bits.append(str(m))
    if core_match_bits:
        extra = normalize(" ".join(core_match_bits))
        if extra:
            blob = f"{blob} {extra}".strip()

    found: list[str] = []
    for cfg in configs:
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
        core_ok = _has_core_signal(blob, cfg.core_norms)

        for _raw, alias_norm, mode in cfg.terms:
            if not term_in_text(alias_norm, blob):
                continue
            if mode == MODE_CORE:
                matched = True
                break
            if mode == MODE_CONTEXT:
                ok = amb_ctx if cfg.ambiguous_context else general_ctx
                if not ok:
                    continue
                matched = True
                break
            if mode == MODE_DISCOVERY:
                # Person/cast discovery keyword: require core film signal in content
                if not core_ok:
                    continue
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
        for raw, norm, mode in cfg.terms:
            rows.append((cfg.slug, raw, norm, mode != MODE_CORE, tuple(cfg.context)))
    return rows
