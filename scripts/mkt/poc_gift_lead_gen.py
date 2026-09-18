#!/usr/bin/env python3
"""POC — Gift Lead Gen (standalone, does NOT touch production crawlers/DB).

Goal: find 1–2 real public posts with bulk gift BUYING INTENT.

  PYTHONPATH=src python3 scripts/mkt/poc_gift_lead_gen.py
  PYTHONPATH=src python3 scripts/mkt/poc_gift_lead_gen.py --live-fb
  PYTHONPATH=src python3 scripts/mkt/poc_gift_lead_gen.py --raw-dir data/facebook/raw/galaxy_cinema/20260915
  PYTHONPATH=src python3 scripts/mkt/poc_gift_lead_gen.py --web-search

Outputs printed to stdout + saved under data/gift_lead_poc/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

OUT_DIR = PROJECT_ROOT / "data" / "gift_lead_poc"
MIN_LEAD_SCORE = 5

# ---------------------------------------------------------------------------
# Queries (priority combinations — not blind single keywords)
# ---------------------------------------------------------------------------

PRIORITY_QUERIES: list[str] = [
    "cần đặt quà số lượng lớn công ty",
    "cần báo giá quà doanh nghiệp",
    "tìm đơn vị làm quà tặng nhân viên",
    "có bên nào nhận làm quà Tết doanh nghiệp",
    "đặt quà số lượng lớn cho khách hàng",
    "cần hộp quà doanh nghiệp số lượng lớn",
    "xin báo giá 200 hộp quà tặng",
    "công ty cần đặt quà cuối năm cho nhân viên",
    "tìm nhà cung cấp quà tặng đối tác",
    "báo giá quà tặng doanh nghiệp số lượng lớn",
    "cần 500 phần quà Tết cho nhân viên",
    "ai nhận làm hộp quà doanh nghiệp",
]

# ---------------------------------------------------------------------------
# Scoring / filters (POC rules — independent from production gift_leads.py)
# ---------------------------------------------------------------------------

BUYING_INTENT = ["cần", "tìm", "đặt", "mua", "báo giá", "xin giá", "xin báo giá", "order"]
BUSINESS_CTX = ["công ty", "doanh nghiệp", "khách hàng", "đối tác", "nhân viên", "sự kiện", "chi nhánh"]
BULK_QTY = [
    "số lượng lớn",
    "100 phần",
    "200 phần",
    "500 phần",
    "hàng trăm",
    "nhiều phần",
    "đặt nhiều",
    "mua nhiều",
    "sỉ",
]
SUPPLIER_SEEK = ["có bên nào", "bên nào nhận", "tìm đơn vị", "tìm nhà cung cấp", "ai nhận làm", "nhận làm"]
PRODUCT = ["hộp quà", "set quà", "giỏ quà", "quà tết", "quà doanh nghiệp", "phần quà", "combo quà"]

SELLER_NOISE = [
    "cửa hàng chúng tôi",
    "shop chúng tôi",
    "xưởng sản xuất",
    "nhận order ngay",
    "giá chỉ từ",
    "inbox đặt hàng",
    "hotline",
    "zalo order",
    "sỉ lẻ toàn quốc",
    "chuyên cung cấp",
    "cung cấp sỉ",
    "bảng giá",
    "catalog",
    "lookbook",
]
CINEMA_NOISE = ["cgv", "galaxy cinema", "bhd", "lotte cinema", "đặt vé", "suất chiếu", "fan screening"]
VANITY_NOISE = ["đẹp quá", "xịn quá", "xinh quá", "yêu thích", "top 10", "review"]


@dataclass
class Candidate:
    platform: str
    author: str
    text: str
    url: str
    published: str
    query: str
    source: str
    score: int = 0
    matched: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    reject_reason: str = ""


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def score_candidate(text: str) -> tuple[int, list[str], list[str]]:
    blob = normalize(text)
    score = 0
    matched: list[str] = []
    why: list[str] = []

    def hit(terms: list[str], points: int, label: str) -> bool:
        nonlocal score
        found = [t for t in terms if t in blob]
        if found:
            score += points
            matched.extend(found)
            why.append(f"+{points} {label}: {', '.join(found[:4])}")
            return True
        return False

    hit(BUYING_INTENT, 2, "buying_intent")
    hit(BUSINESS_CTX, 2, "business_context")
    hit(BULK_QTY, 2, "bulk_quantity")
    hit(SUPPLIER_SEEK, 1, "supplier_seeking")
    hit(PRODUCT, 1, "product")

    # Extra quantity pattern: "500 phần", "200 hộp"
    if re.search(r"\b\d{2,4}\s*(phần|hộp|set|giỏ|suất)\b", blob):
        if "qty_number" not in matched:
            score += 2
            matched.append("qty_number")
            why.append("+2 bulk_quantity: numeric quantity")

    return score, sorted(set(matched)), why


def reject_reason(text: str, score: int) -> str:
    blob = normalize(text)
    if score < MIN_LEAD_SCORE:
        return f"score {score} < {MIN_LEAD_SCORE}"
    if any(t in blob for t in CINEMA_NOISE):
        return "cinema/brand noise"
    if any(t in blob for t in SELLER_NOISE) and not any(t in blob for t in ["cần đặt", "cần mua", "xin báo giá", "cần tìm"]):
        return "looks like seller/ad"
    if any(t in blob for t in VANITY_NOISE) and not any(t in blob for t in ["cần", "đặt", "báo giá", "tìm bên"]):
        return "vanity/review without buying intent"
    if re.search(r"(theo báo|thị trường quà|xu hướng quà|bài viết)", blob) and "cần đặt" not in blob:
        return "news/general article"
    # Must have some buying signal beyond product mention
    if not any(t in blob for t in BUYING_INTENT + SUPPLIER_SEEK):
        return "no buying intent / supplier-seeking phrase"
    if len(blob) < 40:
        return "text too short / low evidence"
    return ""


def evaluate(text: str, **meta) -> Candidate:
    c = Candidate(
        platform=str(meta.get("platform") or "unknown"),
        author=str(meta.get("author") or ""),
        text=(text or "").strip(),
        url=str(meta.get("url") or ""),
        published=str(meta.get("published") or ""),
        query=str(meta.get("query") or ""),
        source=str(meta.get("source") or ""),
    )
    c.score, c.matched, c.reasons = score_candidate(c.text)
    c.reject_reason = reject_reason(c.text, c.score)
    return c


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def load_from_raw_dir(raw_dir: Path) -> list[Candidate]:
    out: list[Candidate] = []
    if not raw_dir.is_dir():
        return out
    for path in sorted(raw_dir.glob("search_*.jsonl")):
        query = path.stem.replace("search_", "").replace("_", " ")
        for line in path.open(encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = str(obj.get("message") or obj.get("story") or "").strip()
            url = str(obj.get("permalink_url") or "")
            published = str(obj.get("created_time") or obj.get("published_at") or "")
            author = ""
            m = re.search(r"facebook\.com/([^/]+)/", url)
            if m:
                author = m.group(1)
            if message:
                out.append(
                    evaluate(
                        message,
                        platform="facebook",
                        author=author,
                        url=url,
                        published=published,
                        query=query,
                        source=f"raw:{path.name}",
                    )
                )
            comments = (obj.get("comments") or {}).get("data") or []
            if isinstance(comments, list):
                for cmt in comments:
                    ctext = str((cmt or {}).get("message") or "").strip()
                    if ctext:
                        out.append(
                            evaluate(
                                ctext,
                                platform="facebook",
                                author=author,
                                url=url,
                                published=str((cmt or {}).get("created_time") or published),
                                query=query,
                                source=f"raw_comment:{path.name}",
                            )
                        )
    return out


def bing_search(query: str, limit: int = 8) -> list[Candidate]:
    """Public Bing HTML search — best-effort for POC (no API key)."""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=vi-vn&cc=VN"
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[web] bing failed query={query!r}: {exc}", flush=True)
        return []

    out: list[Candidate] = []
    # Prefer social permalinks in SERP HTML
    social_links = re.findall(
        r'href="(https?://(?:www\.)?(?:facebook|tiktok|instagram|threads|youtube)\.[^"]+)"',
        html,
        flags=re.I,
    )
    # Fallback: classic b_algo title links
    algo = re.findall(
        r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>\s*</h2>',
        html,
        flags=re.I | re.S,
    )
    seen: set[str] = set()
    for href in social_links + [h for h, _ in algo]:
        if href in seen:
            continue
        seen.add(href)
        # Grab nearby plaintext window
        idx = html.find(href)
        window = re.sub(r"<[^>]+>", " ", html[max(0, idx - 120) : idx + 420])
        window = re.sub(r"\s+", " ", window).strip()
        title = ""
        for h, t in algo:
            if h == href:
                title = re.sub(r"<[^>]+>", "", t)
                break
        text = f"{title}. {window}".strip(" .")
        if len(text) < 40:
            continue
        platform = "web"
        host = urlparse(href).netloc.lower()
        if "facebook.com" in host:
            platform = "facebook"
        elif "tiktok.com" in host:
            platform = "tiktok"
        elif "instagram.com" in host:
            platform = "instagram"
        elif "threads.net" in host:
            platform = "threads"
        elif "youtube.com" in host or "youtu.be" in host:
            platform = "youtube"
        out.append(
            evaluate(
                text[:1200],
                platform=platform,
                author=host,
                url=href,
                published="",
                query=query,
                source="bing",
            )
        )
        if len(out) >= limit:
            break
    return out


def duckduckgo_search(query: str, limit: int = 8) -> list[Candidate]:
    """Deprecated for bots — keep as thin wrapper to bing."""
    return bing_search(query, limit=limit)


def ensure_facebook_chrome(debugger: str = "127.0.0.1:9226") -> bool:
    from social_listening.chromedriver_utils import _chrome_bin, chrome_debugger_ready
    import subprocess

    if chrome_debugger_ready(debugger):
        return True
    host, port = debugger.rsplit(":", 1)
    profile = PROJECT_ROOT / "runtime" / "chrome" / "facebook"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        _chrome_bin(),
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={host}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    print(f"[live-fb] starting Chrome on {debugger}", flush=True)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(25):
        time.sleep(1)
        if chrome_debugger_ready(debugger):
            return True
    return False


def live_facebook_search(queries: list[str], max_per_query: int = 12) -> list[Candidate]:
    """Optional live FB search via existing Chrome debug profile (read-only attach)."""
    debugger = os.getenv("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9226")
    try:
        from social_listening.crawl_reliability import attach_debugger_chrome, recover_stuck_debug_chrome
    except Exception as exc:
        print(f"[live-fb] helpers unavailable: {exc}", flush=True)
        return []

    if not ensure_facebook_chrome(debugger):
        print(f"[live-fb] Chrome debug not ready at {debugger} — skip live FB", flush=True)
        return []

    recover_stuck_debug_chrome(debugger)
    driver = attach_debugger_chrome(debugger)
    out: list[Candidate] = []
    try:
        from selenium.webdriver.common.by import By

        for query in queries:
            search_url = f"https://www.facebook.com/search/posts?q={quote_plus(query)}"
            print(f"[live-fb] query={query!r}", flush=True)
            driver.get(search_url)
            time.sleep(5)
            for _ in range(5):
                driver.execute_script("window.scrollBy(0, 1600);")
                time.sleep(1.3)

            # Prefer article-like blocks
            articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            if not articles:
                articles = driver.find_elements(By.CSS_SELECTOR, "div[data-ad-preview='message']")

            seen_text: set[str] = set()
            for art in articles[: max_per_query * 3]:
                try:
                    text = (art.text or "").strip()
                    if len(text) < 50:
                        continue
                    key = normalize(text)[:180]
                    if key in seen_text:
                        continue
                    seen_text.add(key)
                    href = ""
                    author = ""
                    try:
                        links = art.find_elements(By.CSS_SELECTOR, "a[href*='/posts/'], a[href*='permalink'], a[href*='story_fbid']")
                        if links:
                            href = links[0].get_attribute("href") or ""
                    except Exception:
                        pass
                    if href:
                        m = re.search(r"facebook\.com/([^/]+)/", href)
                        if m:
                            author = m.group(1)
                    out.append(
                        evaluate(
                            text[:2000],
                            platform="facebook",
                            author=author,
                            url=(href.split("?")[0] if href else ""),
                            published="",
                            query=query,
                            source="live_fb",
                        )
                    )
                    if sum(1 for c in out if c.query == query) >= max_per_query:
                        break
                except Exception:
                    continue
            time.sleep(1.2)
    finally:
        pass
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def dedupe(cands: list[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for c in cands:
        key = (c.url or "") + "|" + normalize(c.text)[:160]
        prev = best.get(key)
        if prev is None or c.score > prev.score:
            best[key] = c
    return list(best.values())


def format_lead(n: int, c: Candidate) -> str:
    why = "; ".join(c.reasons) if c.reasons else "matched buying + context signals"
    return f"""---------------------------------------
GIFT LEAD #{n}

Platform: {c.platform}
Author/Page: {c.author or '—'}
Post text: {c.text[:600]}
URL: {c.url or '—'}
Published date: {c.published or '—'}
Matched keywords: {', '.join(c.matched) if c.matched else '—'}
Lead score: {c.score}
Why this is a lead: {why}
Query/source: {c.query} / {c.source}
---------------------------------------"""


def format_rejected(cands: list[Candidate]) -> str:
    lines = ["No genuine Gift Lead found.", "", "Nearest 5 candidates + reject reasons:", ""]
    for i, c in enumerate(cands[:5], 1):
        lines.append(f"{i}. score={c.score} reject={c.reject_reason}")
        lines.append(f"   platform={c.platform} author={c.author or '—'}")
        lines.append(f"   text={c.text[:180].replace(chr(10), ' ')}")
        lines.append(f"   url={c.url or '—'}")
        lines.append(f"   query/source={c.query} / {c.source}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        default=str(PROJECT_ROOT / "data" / "facebook" / "raw" / "galaxy_cinema" / "20260915"),
        help="Optional existing FB raw jsonl dir to score (read-only)",
    )
    parser.add_argument("--web-search", action="store_true", help="Also search DuckDuckGo public HTML")
    parser.add_argument("--live-fb", action="store_true", help="Also live-search Facebook via Chrome :9226")
    parser.add_argument("--max-queries", type=int, default=8)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queries = PRIORITY_QUERIES[: max(1, args.max_queries)]
    print("POC Gift Lead Gen — standalone (no DB / no production crawler writes)")
    print(f"Queries ({len(queries)}):")
    for q in queries:
        print(f"  - {q}")

    candidates: list[Candidate] = []

    raw_dir = Path(args.raw_dir)
    if not raw_dir.is_absolute():
        raw_dir = PROJECT_ROOT / raw_dir
    raw_cands = load_from_raw_dir(raw_dir)
    print(f"[raw] loaded={len(raw_cands)} from {raw_dir}")
    candidates.extend(raw_cands)

    if args.web_search:
        for q in queries:
            got = duckduckgo_search(q)
            print(f"[web] query={q!r} hits={len(got)}")
            candidates.extend(got)
            time.sleep(1.0)

    if args.live_fb:
        candidates.extend(live_facebook_search(queries, max_per_query=10))

    candidates = dedupe(candidates)
    leads = [c for c in candidates if not c.reject_reason]
    leads.sort(key=lambda c: c.score, reverse=True)
    rejected = sorted(
        [c for c in candidates if c.reject_reason],
        key=lambda c: c.score,
        reverse=True,
    )

    print(f"\nCandidates total={len(candidates)} leads={len(leads)} rejected={len(rejected)}")

    report_lines: list[str] = []
    if leads:
        for i, lead in enumerate(leads[:2], 1):
            block = format_lead(i, lead)
            print(block)
            report_lines.append(block)
    else:
        block = format_rejected(rejected)
        print(block)
        report_lines.append(block)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = OUT_DIR / f"poc_results_{stamp}.json"
    out_txt = OUT_DIR / f"poc_report_{stamp}.txt"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "candidate_count": len(candidates),
        "lead_count": len(leads),
        "leads": [asdict(c) for c in leads[:5]],
        "nearest_rejected": [asdict(c) for c in rejected[:5]],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_txt.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nSaved: {out_json}")
    print(f"Saved: {out_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
