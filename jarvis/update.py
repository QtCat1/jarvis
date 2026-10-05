"""Self-update: `python -m jarvis --update` pulls the latest Jarvis from GitHub.

Public repo  -> works with no setup.
Private repo -> needs a GitHub token, from the JARVIS_GITHUB_TOKEN environment variable
                or a one-line file called `.jarvis_token` next to this project.
Your notes live outside this folder (~/.jarvis_notes.json), so updating never touches them.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = os.environ.get("JARVIS_REPO", "QtCat1/jarvis")
BRANCH = os.environ.get("JARVIS_BRANCH", "main")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", "__pycache__", "_backup_before_update", ".github"}


def _token() -> str:
    t = os.environ.get("JARVIS_GITHUB_TOKEN", "").strip()
    if not t:
        f = PROJECT_ROOT / ".jarvis_token"
        if f.exists():
            t = f.read_text().strip()
    return t


def _download() -> bytes:
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
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def update() -> int:
    print(f"Checking {REPO} ({BRANCH}) for a newer Jarvis...")
    try:
        data = _download()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            print(
                f"\nGitHub answered {e.code}. Most likely causes:\n"
                "  - The repository is private and no token was provided, or\n"
                "  - The files haven't been uploaded to the repository yet, or\n"
                f"  - The branch is not called '{BRANCH}'.\n"
                "See the 'Updating' section of README.md."
            )
        else:
            print(f"Download failed (HTTP {e.code}).")
        return 1
    except Exception as e:  # no internet, TLS problems, etc.
        print(f"Couldn't reach GitHub: {e}")
        return 1

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        print("What came back wasn't a valid zip file, so I didn't change anything.")
        return 1

    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        print("The repository looks empty, so nothing was updated.")
        return 1
    top = names[0].split("/")[0] + "/"
    if not all(n.startswith(top) for n in names):
        print("Unexpected zip layout, so I didn't change anything.")
        return 1
    if not any(n[len(top):] == "jarvis/__init__.py" for n in names):
        print("That repository doesn't contain jarvis/__init__.py, so I didn't change anything.")
        return 1

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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not (changed or added):
        print("You already have the latest version.")
    else:
        print(f"Updated: {changed} file(s) changed, {added} new.")
        if changed:
            print(f"Your old versions were saved in: {backup}")
        print("If requirements changed, also run:  py -m pip install -r requirements.txt")
        print("Restart Jarvis to use the new version.")
    return 0


if __name__ == "__main__":
    sys.exit(update())
