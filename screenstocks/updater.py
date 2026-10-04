"""Update check against the latest GitHub release, plus installer download."""

import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__, config

log = logging.getLogger(__name__)

API_URL = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
INSTALLER_PATTERN = re.compile(r"^ScreenStocksTradingBot-Setup-.*\.exe$", re.I)


@dataclass
class Release:
    version: str
    page_url: str
    installer_name: Optional[str]
    installer_url: Optional[str]
    installer_size: int


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _request(url: str, timeout: float) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": f"ScreenStocksTradingBot/{__version__}",
                                                "Accept": "application/vnd.github+json"})


def fetch_latest(timeout: float = 10.0) -> Release:
    with urllib.request.urlopen(_request(API_URL, timeout), timeout=timeout) as resp:
        data = json.load(resp)
    asset = next((a for a in data.get("assets", []) if INSTALLER_PATTERN.match(a.get("name", ""))), None)
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        page_url=data.get("html_url", f"https://github.com/{config.GITHUB_REPO}/releases"),
        installer_name=asset["name"] if asset else None,
        installer_url=asset["browser_download_url"] if asset else None,
        installer_size=int(asset.get("size", 0)) if asset else 0,
    )


def download_installer(release: Release, progress: Callable[[int, int], None]) -> Path:
    """Download the installer to the temp folder; progress(done_bytes, total_bytes)."""
    if not release.installer_url:
        raise RuntimeError("release has no installer")
    target = Path(tempfile.gettempdir()) / release.installer_name
    partial = target.with_suffix(".part")
    with urllib.request.urlopen(_request(release.installer_url, 30), timeout=30) as resp, \
            open(partial, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or release.installer_size or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            fh.write(chunk)
            done += len(chunk)
            progress(done, total)
    if total and done != total:
        raise RuntimeError(f"download incomplete ({done} of {total} bytes)")
    os.replace(partial, target)
    return target


def launch_installer(path: Path) -> None:
    # Detached, so it keeps running after the app has closed itself.
    subprocess.Popen([str(path)], close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
