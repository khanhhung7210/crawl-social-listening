from __future__ import annotations

import re


USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{2,}$", re.IGNORECASE)
RELATIVE_TIME_PATTERN = re.compile(
    r"^(?:\d+\s*[smhdw]|\d+\s*(?:giây|phút|giờ|ngày|tuần)\s*trước|\d+\s*(?:seconds?|minutes?|hours?|days?|weeks?)\s*ago)$",
    re.IGNORECASE,
)
ABSOLUTE_DATE_PATTERN = re.compile(
    r"^(?:[A-Z][a-z]+ \d{1,2}(?:, \d{4})?|\d{1,2} [A-Z][a-z]{2} \d{4})$"
)
SKIP_LINE_PATTERN = re.compile(
    r"^(?:\d[\d.,]*\s+likes?|\d[\d.,]*\s+like|reply|see translation|view all .* replies?|liked by .*|more posts from .*|meta|meta ai|about|blog|jobs|help|api|privacy|terms|locations|popular|instagram lite|threads|contact uploading(?: &| and) non-users|meta verified)$",
    re.IGNORECASE,
)
FOOTER_LINE_PATTERN = re.compile(
    r"^(?:more posts from .*|meta|meta ai|about|blog|jobs|help|api|privacy|terms|locations|popular|instagram lite|threads|contact uploading(?: &| and) non-users|english|afrikaans|العربية|čeština|dansk|deutsch)$",
    re.IGNORECASE,
)


def extract_instagram_comments_from_body_text(body_text: str, post_url: str) -> list[dict]:
    lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return []

    comments: list[dict] = []
    seen_ids: set[str] = set()
    skipped_caption = False
    index = 0

    while index + 2 < len(lines):
        author = lines[index]
        created_at_label = lines[index + 1]
        if not _looks_like_comment_start(lines, index):
            index += 1
            continue

        if not skipped_caption:
            skipped_caption = True
            index += 3
            continue

        text_parts = [lines[index + 2]]
        cursor = index + 3
        while cursor < len(lines):
            line = lines[cursor]
            if _looks_like_comment_start(lines, cursor):
                break
            if FOOTER_LINE_PATTERN.match(line) or _looks_like_absolute_date(line):
                break
            if SKIP_LINE_PATTERN.match(line):
                cursor += 1
                continue
            if line.isdigit():
                cursor += 1
                continue
            text_parts.append(line)
            cursor += 1

        text = " ".join(part.strip() for part in text_parts if part.strip()).strip()
        if text:
            raw_id = f"{author}|{created_at_label}|{text[:80]}".strip().casefold()
            external_id = f"comment:{re.sub(r'[^a-z0-9._|:-]+', '-', raw_id)}"
            if external_id not in seen_ids:
                seen_ids.add(external_id)
                comments.append(
                    {
                        "external_id": external_id,
                        "record_type": "comment",
                        "author": author,
                        "text": text,
                        "created_at": "",
                        "created_at_label": created_at_label,
                        "parent_comment_id": "",
                        "keyword_match": False,
                        "url": f"{post_url}#comment-{len(comments) + 1}",
                        "source": "body_text",
                    }
                )

        index = max(cursor, index + 1)

    return comments


def _looks_like_comment_start(lines: list[str], index: int) -> bool:
    if index + 2 >= len(lines):
        return False
    author = lines[index]
    created_at_label = lines[index + 1]
    text = lines[index + 2]
    if not USERNAME_PATTERN.match(author):
        return False
    if not (_looks_like_relative_time(created_at_label) or _looks_like_absolute_date(created_at_label)):
        return False
    if not text or SKIP_LINE_PATTERN.match(text):
        return False
    return True


def _looks_like_relative_time(label: str) -> bool:
    return bool(RELATIVE_TIME_PATTERN.match(label.strip()))


def _looks_like_absolute_date(label: str) -> bool:
    return bool(ABSOLUTE_DATE_PATTERN.match(label.strip()))
