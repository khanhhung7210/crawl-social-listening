"""Facebook album photo URLs must not create post-level buzz mentions."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_listening.review_utils import is_facebook_album_photo_url


def test_pcb_album_photo_url():
    assert is_facebook_album_photo_url(
        "https://www.facebook.com/photo/?fbid=2555415988258694&set=pcb.2555416228258670"
    )


def test_photo_php_url():
    assert is_facebook_album_photo_url("https://www.facebook.com/photo.php?fbid=1&set=a.2")


def test_real_post_urls_are_not_album_photos():
    assert not is_facebook_album_photo_url(
        "https://www.facebook.com/galaxycinema/posts/pfbid0abc"
    )
    assert not is_facebook_album_photo_url(
        "https://www.facebook.com/permalink.php?fbid=123"
    )
    assert not is_facebook_album_photo_url("https://www.instagram.com/p/abc/")
