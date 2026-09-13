"""Crawl reliability helpers: timed Chrome attach, session gates, heartbeats."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from social_listening.chromedriver_utils import chrome_debugger_ready, resolve_chromedriver_path


def chrome_attach_timeout_seconds() -> float:
    return float(os.getenv("CHROME_ATTACH_TIMEOUT_SECONDS", "90") or "90")


def chrome_attach_retries() -> int:
    return max(1, int(os.getenv("CHROME_ATTACH_RETRIES", "3") or "3"))


def _env_flag(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def kill_orphaned_chromedrivers(*, parent_pid: int | None = None) -> int:
    """
    Kill chromedriver processes that are children of *parent_pid* (default: us).

    Attach timeouts often leave a hung chromedriver holding the DevTools port,
    so the next round fails the same way. Only children of this process are
    targeted so parallel platform terminals are not wiped.
    """
    if not _env_flag("CHROME_ATTACH_KILL_ORPHAN_DRIVER", True):
        return 0
    parent = int(parent_pid or os.getpid())
    killed = 0
    try:
        if sys.platform == "win32":
            # ParentProcessId match keeps other platforms' drivers alive.
            ps = (
                "$ppid=%d; $n=0; "
                "Get-CimInstance Win32_Process -Filter \"Name='chromedriver.exe'\" "
                "| Where-Object { $_.ParentProcessId -eq $ppid } "
                "| ForEach-Object { "
                "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; "
                "Write-Output $n"
            ) % parent
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            out = (result.stdout or "").strip().splitlines()
            if out and out[-1].isdigit():
                killed = int(out[-1])
        else:
            result = subprocess.run(
                ["pgrep", "-P", str(parent), "-f", "chromedriver"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            pids = [int(x) for x in (result.stdout or "").split() if x.strip().isdigit()]
            for pid in pids:
                try:
                    os.kill(pid, 9)
                    killed += 1
                except OSError:
                    pass
    except Exception as exc:
        print(f"[chrome] orphan chromedriver cleanup skipped: {exc}", flush=True)
        return 0
    if killed:
        print(
            f"[chrome] killed {killed} orphan chromedriver child(ren) of pid={parent}",
            flush=True,
        )
    return killed


def recover_stuck_debug_chrome(address: str) -> None:
    """
    Unstick a debug Chrome that answers /json/version but refuses Selenium attach.

    Opens about:blank via DevTools HTTP and closes surplus page targets so the
    next chromedriver handshake is not blocked on a hung YouTube/captcha tab.
    """
    addr = (address or "").strip()
    if not addr:
        return
    print(f"[chrome] recovering stuck debug Chrome at {addr}", flush=True)
    try:
        blank = "about:blank"
        url = f"http://{addr}/json/new?{urllib.parse.quote(blank, safe='')}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            resp.read()
        print("[chrome] opened about:blank via /json/new", flush=True)
    except Exception as exc:
        print(f"[chrome] /json/new about:blank failed: {exc}", flush=True)

    try:
        with urllib.request.urlopen(f"http://{addr}/json/list", timeout=8) as resp:
            tabs = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not isinstance(tabs, list):
            return
        pages = [t for t in tabs if isinstance(t, dict) and t.get("type") == "page"]
        # Keep the newest blank-ish tab; close older pages that may be wedged.
        keep_id = None
        for t in reversed(pages):
            u = str(t.get("url") or "")
            if u.startswith("about:blank") or u in {"", "chrome://newtab/"}:
                keep_id = t.get("id")
                break
        if keep_id is None and pages:
            keep_id = pages[-1].get("id")
        closed = 0
        for t in pages:
            tid = t.get("id")
            if not tid or tid == keep_id:
                continue
            try:
                with urllib.request.urlopen(f"http://{addr}/json/close/{tid}", timeout=5) as resp:
                    resp.read()
                closed += 1
            except Exception:
                pass
        if closed:
            print(f"[chrome] closed {closed} surplus page target(s)", flush=True)
        if keep_id:
            try:
                with urllib.request.urlopen(f"http://{addr}/json/activate/{keep_id}", timeout=5) as resp:
                    resp.read()
            except Exception:
                pass
    except Exception as exc:
        print(f"[chrome] recover list/close failed: {exc}", flush=True)


def _attach_debugger_chrome_once(
    address: str,
    *,
    timeout_s: float,
    resolve_driver: bool = True,
) -> webdriver.Chrome:
    addr = (address or "").strip()
    if not addr:
        raise ValueError("debugger address is required")
    ready = chrome_debugger_ready(addr, timeout=3.0)
    if not ready:
        raise RuntimeError(
            f"Chrome debug not ready at {addr}. "
            f"Check: curl http://{addr}/json/version"
        )

    limit = max(15.0, float(timeout_s))
    print(
        f"[chrome] attaching Selenium to {addr} (timeout={limit:.0f}s) "
        f"browser={ready.get('Browser', '?')}",
        flush=True,
    )

    def _connect() -> webdriver.Chrome:
        options = Options()
        options.debugger_address = addr
        # Avoid hanging on a forever-loading YouTube/captcha document.
        try:
            options.page_load_strategy = "eager"
        except Exception:
            pass
        driver_path = resolve_chromedriver_path() if resolve_driver else ""
        if driver_path:
            return webdriver.Chrome(service=Service(driver_path), options=options)
        try:
            return webdriver.Chrome(options=options)
        except SessionNotCreatedException:
            if not resolve_driver:
                raise
            driver_path = resolve_chromedriver_path()
            if driver_path:
                return webdriver.Chrome(service=Service(driver_path), options=options)
            return webdriver.Chrome(options=options)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_connect)
    try:
        try:
            driver = fut.result(timeout=limit)
        except concurrent.futures.TimeoutError as exc:
            fut.cancel()
            kill_orphaned_chromedrivers()
            raise RuntimeError(
                f"Selenium attach to {addr} timed out after {limit:.0f}s — "
                "Chrome may be stuck, captcha, or another crawler holds the session. "
                "Orphan chromedriver children were killed; refresh the YouTube/social "
                "tab if the next round still fails."
            ) from exc
        except SessionNotCreatedException as exc:
            kill_orphaned_chromedrivers()
            raise RuntimeError(
                f"Cannot attach Selenium to Chrome at {addr}. "
                f"Check: curl http://{addr}/json/version"
            ) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    print(f"[chrome] attached OK {addr}", flush=True)
    return driver


def attach_debugger_chrome(
    address: str,
    *,
    timeout_s: float | None = None,
    resolve_driver: bool = True,
    retries: int | None = None,
) -> webdriver.Chrome:
    """
    Attach Selenium to an existing debug Chrome with a hard timeout + retries.

    Without this, webdriver.Chrome(debugger_address=...) can hang for hours
    when the port answers /json/version but DevTools handshake stalls
    (common when MKT+DIS fight the same browser, or Chrome is mid-navigation).

    On timeout: kill orphan chromedriver children, recover via CDP /json/new,
    then retry attach before failing the round.
    """
    addr = (address or "").strip()
    if not addr:
        raise ValueError("debugger address is required")
    limit = chrome_attach_timeout_seconds() if timeout_s is None else float(timeout_s)
    attempts = chrome_attach_retries() if retries is None else max(1, int(retries))
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return _attach_debugger_chrome_once(
                addr,
                timeout_s=limit,
                resolve_driver=resolve_driver,
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"[chrome] attach attempt {attempt}/{attempts} failed: {exc}",
                flush=True,
            )
            kill_orphaned_chromedrivers()
            if attempt >= attempts:
                break
            recover_stuck_debug_chrome(addr)
            time.sleep(2.0)

    assert last_exc is not None
    raise last_exc


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
        "recaptcha",
        "i'm not a robot",
        "không phải robot",
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
