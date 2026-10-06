"""One week of conversation memory, stored only on this computer.

File: ~/.jarvis_memory.jsonl (outside the Jarvis folder, so updates never touch it).
Entries older than RETENTION_DAYS are deleted automatically. API keys and GitHub tokens
are blanked out before anything is saved.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path.home() / ".jarvis_memory.jsonl"
RETENTION_DAYS = 7
MAX_TEXT = 600          # characters kept per message
MAX_CONTEXT_CHARS = 6000  # how much history is shown to Claude

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
_DAY = 86400


def _clean(text: str) -> str:
    return _SECRET.sub("[hidden]", " ".join(str(text).split()))[:MAX_TEXT]


def _read() -> list[dict]:
    try:
        lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
            if isinstance(e, dict) and "t" in e and "text" in e:
                out.append(e)
        except ValueError:
            continue  # skip a damaged line instead of losing everything
    return out


def _write(entries: list[dict]) -> None:
    MEMORY_FILE.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )


def recent(days: float = RETENTION_DAYS, now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [e for e in _read() if now - e["t"] <= days * _DAY]


def add(role: str, text: str, now: float | None = None) -> None:
    """Save one message (role is 'user' or 'jarvis') and drop anything past a week."""
    text = _clean(text)
    if not text:
        return
    now = now or time.time()
    entries = [e for e in _read() if now - e["t"] <= RETENTION_DAYS * _DAY]
    entries.append({"t": now, "role": role, "text": text})
    _write(entries)


def clear() -> int:
    n = len(_read())
    try:
        MEMORY_FILE.unlink()
    except OSError:
        pass
    return n


def context_block(now: float | None = None) -> str:
    """The past week as plain text for Claude's system prompt, newest kept if too long."""
    lines = []
    for e in recent(now=now):
        when = datetime.fromtimestamp(e["t"]).strftime("%a %d %b %H:%M")
        who = "User" if e["role"] == "user" else "Jarvis"
        lines.append(f"[{when}] {who}: {e['text']}")
    text = "\n".join(lines)
    return text[-MAX_CONTEXT_CHARS:].split("\n", 1)[-1] if len(text) > MAX_CONTEXT_CHARS else text


def _short(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


_GENERIC = {
    "we", "it", "that", "this", "me", "us", "you", "i", "something", "anything", "everything", "stuff",
    "yesterday", "today", "earlier", "this week", "last week", "the past week", "past week",
    "this morning", "last night", "the week", "the last week",
}
_STOP = {
    "the", "and", "for", "with", "our", "was", "are", "that", "this", "have", "has", "been", "did",
    "what", "when", "how", "about", "any", "all", "you", "your", "his", "her", "its", "from", "there",
}


def recall(query: str = "", now: float | None = None) -> str:
    """Answer 'what did we talk about yesterday / today / this week / about X'."""
    now = now or time.time()
    low = query.lower()
    entries = [e for e in recent(now=now) if e["role"] == "user"]
    if not entries:
        return "I don't have any conversations saved yet, sir."

    today0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if "yesterday" in low:
        label, head, lo, hi = "yesterday", "Yesterday", today0 - _DAY, today0
    elif re.search(r"\btoday\b|\bearlier\b|\bthis morning\b", low):
        label, head, lo, hi = "today", "Today", today0, now + 1
    else:
        label, head, lo, hi = "the past week", "Over the past week", now - RETENTION_DAYS * _DAY, now + 1
    picked = [e for e in entries if lo <= e["t"] < hi]

    about = ""
    topic = re.search(r"\babout\s+(.+?)(?:\s+(?:yesterday|today|earlier|this week|last week))?[?.!]*$", low)
    if topic and topic.group(1).strip() not in _GENERIC:
        words = [w for w in re.findall(r"[a-z0-9']+", topic.group(1)) if len(w) > 2 and w not in _GENERIC and w not in _STOP]
        if words:
            picked = [e for e in picked if any(w in e["text"].lower() for w in words)]
            about = f" about {topic.group(1).strip()}"

    if not picked:
        return f"I don't have anything saved from {label}{about}, sir."
    items = "; ".join(f"“{_short(e['text'])}”" for e in picked[-5:])
    return f"{head}{about}, you said: {items}."
