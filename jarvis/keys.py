"""API keys for Claude and Grok, kept on this computer only.

Looked up in this order: environment variable, then ~/.jarvis_keys.json (outside the Jarvis
folder, so GitHub updates never touch it and it can never be uploaded by accident).
Set them with:  python -m jarvis --setup
"""
from __future__ import annotations

import json
import os
from pathlib import Path

KEYS_FILE = Path.home() / ".jarvis_keys.json"
NAMES = ("ANTHROPIC_API_KEY", "XAI_API_KEY")


def _file() -> dict:
    try:
        d = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(name: str) -> str:
    return (os.environ.get(name) or _file().get(name) or "").strip()


def save(name: str, value: str) -> None:
    if name not in NAMES:
        raise ValueError("unknown key name")
    d = _file()
    d[name] = value.strip()
    KEYS_FILE.write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(KEYS_FILE, 0o600)  # owner-only where the OS supports it
    except OSError:
        pass


def setup() -> int:
    """`python -m jarvis --setup`: paste keys once; nothing is echoed to the screen."""
    import getpass

    print("Jarvis key setup. Keys are saved only on this computer, in:\n  " + str(KEYS_FILE))
    print("When you paste, nothing will appear on screen. That is normal. Press Enter after.\n")
    for name, label in (("XAI_API_KEY", "Grok (xAI) key"), ("ANTHROPIC_API_KEY", "Claude (Anthropic) key")):
        have = "already saved, Enter keeps it" if get(name) else "Enter to skip"
        try:
            v = getpass.getpass(f"Paste your {label} ({have}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if v:
            save(name, v)
            print(f"  saved {label}.")
    print("\nDone. Start Jarvis normally. Say 'use grok' or 'use claude' to switch brains.")
    return 0
