"""Self-update: Jarvis pulls the latest version of itself from GitHub.

- Automatic: checked when Jarvis starts (at most once an hour) and every few hours while the
  HUD server runs. After an update Jarvis restarts itself.
- Manual: say "update yourself", or run `python -m jarvis --update`, or double-click update.bat.

Public repo  -> works with no setup.
Private repo -> needs a GitHub token, from the JARVIS_GITHUB_TOKEN environment variable
                or a one-line file called `.jarvis_token` next to this project.
Your notes live outside this folder (~/.jarvis_notes.json), so updating never touches them.

Turn automatic updates off: create an empty file named `.jarvis_no_autoupdate` in the
Jarvis folder, or set JARVIS_AUTOUPDATE=0.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = os.environ.get("JARVIS_REPO", "QtCat1/jarvis")
BRANCH = os.environ.get("JARVIS_BRANCH", "main")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", "__pycache__", "_backup_before_update", ".github"}
RESTART_CODE = 3  # a child Jarvis exits with this to ask its supervisor for a restart
CHECK_INTERVAL = 3600  # seconds between automatic checks at startup
STAMP = Path.home() / ".jarvis_update_stamp"

LAST_ERROR = ""  # short, human-readable reason for the most recent failure


def _token() -> str:
    t = os.environ.get("JARVIS_GITHUB_TOKEN", "").strip()
    if not t:
        f = PROJECT_ROOT / ".jarvis_token"
        if f.exists():
            t = f.read_text().strip()
    return t


def _download(timeout: int) -> bytes:
    override = os.environ.get("JARVIS_UPDATE_URL")  # used for testing
    token = _token()
    headers = {"User-Agent": "JarvisUpdater/1.0"}
    if override:
        url = override
    elif token:
        url = f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}"
        headers["Authorization"] = f"token {token}"
        headers["Accept"] = "application/vnd.github+json"
    else:
        url = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def auto_enabled() -> bool:
    if os.environ.get("JARVIS_AUTOUPDATE", "1") == "0":
        return False
    return not (PROJECT_ROOT / ".jarvis_no_autoupdate").exists()


def apply_update(log=print, timeout: int = 60) -> str:
    """Download the latest version and copy it over this folder.

    Returns "updated", "current" or "error" (reason in LAST_ERROR).
    """
    global LAST_ERROR
    LAST_ERROR = ""
    try:
        data = _download(timeout)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            LAST_ERROR = (
                f"GitHub refused access ({e.code}). The repository is probably private and needs "
                "a token, or it is empty, or the branch isn't called "
                f"'{BRANCH}'. See 'Updating' in README.md."
            )
        else:
            LAST_ERROR = f"download failed (HTTP {e.code})"
        return "error"
    except Exception as e:  # no internet, TLS problems, etc.
        LAST_ERROR = f"couldn't reach GitHub ({e})"
        return "error"

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        LAST_ERROR = "what came back wasn't a valid zip file"
        return "error"

    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        LAST_ERROR = "the repository looks empty"
        return "error"
    top = names[0].split("/")[0] + "/"
    if not all(n.startswith(top) for n in names) or not any(
        n[len(top):] == "jarvis/__init__.py" for n in names
    ):
        LAST_ERROR = "the repository doesn't look like Jarvis, so I changed nothing"
        return "error"

    backup = PROJECT_ROOT / "_backup_before_update" / time.strftime("%Y%m%d-%H%M%S")
    changed = added = 0
    tmp = Path(tempfile.mkdtemp())
    try:
        zf.extractall(tmp)
        src_root = tmp / top.rstrip("/")
        for src in src_root.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(src_root)
            if SKIP_PARTS & set(rel.parts):
                continue
            dst = PROJECT_ROOT / rel
            new_bytes = src.read_bytes()
            if dst.exists():
                if dst.read_bytes() == new_bytes:
                    continue
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup / rel)
                changed += 1
            else:
                added += 1
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(new_bytes)
    except Exception as e:
        LAST_ERROR = f"couldn't write the new files ({e})"
        return "error"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not (changed or added):
        return "current"
    log(f"Updated: {changed} file(s) changed, {added} new. Old versions kept in {backup}")
    return "updated"


def auto_check(log=print) -> str:
    """Startup check. Quiet when there's nothing to say; never raises."""
    if not auto_enabled():
        return "disabled"
    try:
        if STAMP.exists() and time.time() - STAMP.stat().st_mtime < CHECK_INTERVAL:
            return "skipped"
        status = apply_update(log=log, timeout=15)
        STAMP.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        if status == "error":
            log(f"(Couldn't check for Jarvis updates: {LAST_ERROR})")
        return status
    except Exception:
        return "error"


def schedule_restart(delay: float = 1.5) -> bool:
    """Ask the supervisor to restart us. Only possible when running under it."""
    if os.environ.get("JARVIS_CHILD") != "1":
        return False
    threading.Timer(delay, os._exit, [RESTART_CODE]).start()
    return True


def update() -> int:
    """`python -m jarvis --update`"""
    print(f"Checking {REPO} ({BRANCH}) for a newer Jarvis...")
    status = apply_update(log=print)
    if status == "error":
        print(f"\nCouldn't update: {LAST_ERROR}")
        return 1
    if status == "current":
        print("You already have the latest version.")
    else:
        print("If something looks broken afterwards, also run:  py -m pip install -r requirements.txt")
        print("Start Jarvis again to use the new version.")
    return 0


if __name__ == "__main__":
    sys.exit(update())
