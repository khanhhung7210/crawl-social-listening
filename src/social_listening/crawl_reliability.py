"""Crawl reliability helpers: timed Chrome attach, session gates, heartbeats."""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from social_listening.chromedriver_utils import chrome_debugger_ready, resolve_chromedriver_path


def chrome_attach_timeout_seconds() -> float:
    return float(os.getenv("CHROME_ATTACH_TIMEOUT_SECONDS", "90") or "90")


def attach_debugger_chrome(
    address: str,
    *,
    timeout_s: float | None = None,
    resolve_driver: bool = True,
) -> webdriver.Chrome:
    """
    Attach Selenium to an existing debug Chrome with a hard timeout.

    Without this, webdriver.Chrome(debugger_address=...) can hang for hours
    when the port answers /json/version but DevTools handshake stalls
    (common when MKT+DIS fight the same browser, or Chrome is mid-navigation).
    """
    addr = (address or "").strip()
    if not addr:
        raise ValueError("debugger address is required")
    ready = chrome_debugger_ready(addr, timeout=3.0)
    if not ready:
        raise RuntimeError(
            f"Chrome debug not ready at {addr}. "
            f"Check: curl http://{addr}/json/version"
        )

    limit = chrome_attach_timeout_seconds() if timeout_s is None else float(timeout_s)
    limit = max(15.0, limit)
    print(
        f"[chrome] attaching Selenium to {addr} (timeout={limit:.0f}s) "
        f"browser={ready.get('Browser', '?')}",
        flush=True,
    )

    def _connect() -> webdriver.Chrome:
        options = Options()
        options.debugger_address = addr
        try:
            return webdriver.Chrome(options=options)
        except SessionNotCreatedException:
            if not resolve_driver:
                raise
            driver_path = resolve_chromedriver_path()
            if driver_path:
                return webdriver.Chrome(service=Service(driver_path), options=options)
            return webdriver.Chrome(options=options)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_connect)
        try:
            driver = fut.result(timeout=limit)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(
                f"Selenium attach to {addr} timed out after {limit:.0f}s — "
                "Chrome may be stuck, captcha, or another crawler holds the session. "
                "Fix: refresh the tab, re-login, kill orphan run_full_pipeline, retry."
            ) from exc
        except SessionNotCreatedException as exc:
            raise RuntimeError(
                f"Cannot attach Selenium to Chrome at {addr}. "
                f"Check: curl http://{addr}/json/version"
            ) from exc

    print(f"[chrome] attached OK {addr}", flush=True)
    return driver


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def diagnose_social_session(driver: webdriver.Chrome, platform: str) -> str | None:
    """
    Return a human error if the open tab looks like login/captcha/block.
    None means "looks usable enough to try crawling".
    """
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException as exc:
        return f"cannot read browser state: {exc}"

    blob = _norm(f"{url} {title}")
    plat = (platform or "").lower().strip()

    login_tokens = (
        "login",
        "log in",
        "sign in",
        "signin",
        "signup",
        "sign-up",
        "đăng nhập",
        "accounts.google.com",
        "checkpoint",
        "captcha",
        "challenge",
        "verify",
        "unusual traffic",
        "auth_platform",
    )
    if any(tok in blob for tok in login_tokens):
        return f"{plat} session blocked/login wall: url={url!r} title={title!r}"

    # Empty/new tab is OK — crawler will navigate. Wrong product host is not.
    host_ok = {
        "tiktok": ("tiktok.com", "about:blank", "chrome://"),
        "instagram": ("instagram.com", "about:blank", "chrome://"),
        "facebook": ("facebook.com", "fb.com", "about:blank", "chrome://"),
        "threads": ("threads.net", "threads.com", "about:blank", "chrome://"),
        "youtube": ("youtube.com", "about:blank", "chrome://"),
    }.get(plat)
    if host_ok and url.startswith("http"):
        if not any(h in url.lower() for h in host_ok if "://" not in h):
            # soft warn only when clearly on another social
            foreign = ("tiktok.com", "instagram.com", "facebook.com", "threads.net", "youtube.com")
            if any(h in url.lower() for h in foreign):
                return (
                    f"{plat} Chrome is on wrong site url={url!r} — "
                    f"open the correct site on this debug profile first"
                )
    return None


def assert_social_session(driver: webdriver.Chrome, platform: str) -> None:
    problem = diagnose_social_session(driver, platform)
    if problem:
        raise RuntimeError(problem)


class CrawlHeartbeat:
    """Daemon thread that prints progress so hangs are visible in live logs."""

    def __init__(self, label: str, every_s: float | None = None):
        self.label = label
        self.every_s = float(
            every_s
            if every_s is not None
            else (os.getenv("CRAWL_HEARTBEAT_SECONDS", "60") or "60")
        )
        self.every_s = max(15.0, self.every_s)
        self._msg = "starting"
        self._detail = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"hb-{label}", daemon=True)
        self._started = time.monotonic()

    def update(self, msg: str, detail: str = "") -> None:
        self._msg = msg
        self._detail = detail

    def start(self) -> "CrawlHeartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=2.0)
        except RuntimeError:
            pass

    def _run(self) -> None:
        while not self._stop.wait(self.every_s):
            elapsed = int(time.monotonic() - self._started)
            extra = f" {self._detail}" if self._detail else ""
            print(
                f"[{self.label}] heartbeat t+{elapsed}s state={self._msg}{extra}",
                flush=True,
            )


def with_heartbeat(label: str, fn: Callable[[CrawlHeartbeat], int]) -> int:
    hb = CrawlHeartbeat(label).start()
    try:
        return fn(hb)
    finally:
        hb.stop()
