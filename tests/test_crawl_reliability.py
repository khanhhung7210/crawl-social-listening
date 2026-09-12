from __future__ import annotations

from social_listening.crawl_reliability import diagnose_social_session


class _FakeDriver:
    def __init__(self, url: str, title: str = ""):
        self.current_url = url
        self.title = title


def test_diagnose_login_wall():
    msg = diagnose_social_session(_FakeDriver("https://www.tiktok.com/login"), "tiktok")
    assert msg and "login" in msg.lower()


def test_diagnose_ok_blank():
    assert diagnose_social_session(_FakeDriver("about:blank"), "tiktok") is None


def test_diagnose_wrong_site():
    msg = diagnose_social_session(
        _FakeDriver("https://www.instagram.com/"),
        "tiktok",
    )
    assert msg and "wrong site" in msg.lower()
