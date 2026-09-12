"""Chrome debug attach + chromedriver path helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_DRIVER = _PROJECT_ROOT / "runtime" / "bin" / "chromedriver"
_DEFAULT_USER_DATA = Path("/tmp/chrome-codex-google-maps")
_DEFAULT_DEBUGGER = "127.0.0.1:9227"


def resolve_chromedriver_path() -> str:
    env = (os.getenv("CHROMEDRIVER_PATH") or "").strip()
    if env and Path(env).is_file():
        return env
    # Skip bundled runtime driver on Windows — often stale vs installed Chrome.
    if os.name != "nt" and _RUNTIME_DRIVER.is_file():
        return str(_RUNTIME_DRIVER)

    roots = [
        Path.home() / ".wdm" / "drivers" / "chromedriver" / "mac-arm64",
        Path.home() / ".wdm" / "drivers" / "chromedriver" / "mac64",
        Path.home() / ".wdm" / "drivers" / "chromedriver" / "mac-x64",
    ]
    patterns = (
        "*/chromedriver-mac-arm64/chromedriver",
        "*/chromedriver-mac-x64/chromedriver",
        "*/chromedriver/chromedriver",
    )
    for cache_root in roots:
        if not cache_root.exists():
            continue
        for pattern in patterns:
            candidates = sorted(cache_root.glob(pattern), reverse=True)
            for candidate in candidates:
                if candidate.is_file():
                    return str(candidate)
    return ""


def debugger_address() -> str:
    return (os.getenv("GOOGLE_MAPS_DEBUGGER_ADDRESS") or _DEFAULT_DEBUGGER).strip()


def chrome_debugger_ready(address: str | None = None, timeout: float = 2.0) -> dict | None:
    addr = address or debugger_address()
    url = f"http://{addr}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl"):
            return payload
    except Exception:
        return None
    return None


def _chrome_bin() -> str:
    env = (os.getenv("CHROME_BIN") or "").strip()
    if env and Path(env).is_file():
        return env
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac).is_file():
        return mac
    found = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")
    if found:
        return found
    raise RuntimeError("Không tìm thấy Google Chrome. Cài Chrome hoặc set CHROME_BIN.")


def ensure_debug_chrome(address: str | None = None) -> dict:
    """Attach to existing debug Chrome, or start a dedicated profile on 9227."""
    addr = address or debugger_address()
    ready = chrome_debugger_ready(addr)
    if ready:
        print(f"[chrome] debugger ready {addr} browser={ready.get('Browser')}")
        return ready

    host, port_s = addr.rsplit(":", 1)
    port = int(port_s)
    user_data = Path(os.getenv("GOOGLE_MAPS_CHROME_USER_DATA") or _DEFAULT_USER_DATA)
    user_data.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_bin()
    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={host}",
        f"--user-data-dir={user_data}",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=vi-VN",
        "--accept-lang=vi-VN,vi,en-US,en",
        "https://www.google.com/maps?hl=vi",
    ]
    print(f"[chrome] starting debug Chrome on {addr}")
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(25):
        time.sleep(0.6)
        ready = chrome_debugger_ready(addr)
        if ready:
            print(f"[chrome] debugger ready {addr} browser={ready.get('Browser')}")
            return ready
    raise RuntimeError(
        f"Chrome debug không lên {addr}. Mở Chrome bằng:\n"
        f"{chrome} --remote-debugging-port={port} "
        f"--remote-debugging-address={host} --user-data-dir={user_data}"
    )


def build_attached_chrome(address: str | None = None) -> webdriver.Chrome:
    """Selenium attach. Uses Selenium Manager (matches installed Chrome), not stale runtime driver."""
    addr = address or debugger_address()
    ensure_debug_chrome(addr)
    return build_debugger_chrome(addr)


def build_debugger_chrome(address: str) -> webdriver.Chrome:
    """Attach to Chrome already listening on a remote-debugging port (timed)."""
    from social_listening.crawl_reliability import attach_debugger_chrome

    return attach_debugger_chrome(address)


# Back-compat alias used by some crawlers
build_debugger_driver = build_debugger_chrome


def leave_chrome_open(driver: webdriver.Chrome | None) -> None:
    """Do not driver.quit() — quit() đóng luôn cửa sổ debug Chrome."""
    _ = driver
