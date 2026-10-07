"""Talking to the AI services: Claude (Anthropic) and Grok (xAI).

Grok uses xAI's Responses API (POST {base}/responses), called with the standard library only,
so nothing extra has to be installed. Defaults can be changed with environment variables:
  JARVIS_GROK_MODEL  (default grok-4.7)      XAI_BASE_URL (default https://api.x.ai/v1)
  JARVIS_MODEL       (Claude model)          JARVIS_PROVIDER (claude or grok)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import keys

CLAUDE_MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5-5")
GROK_MODEL = os.environ.get("JARVIS_GROK_MODEL", "grok-4.7")


class LLMError(Exception):
    """A problem talking to an AI service, with a message that is safe to say out loud."""


def base_url() -> str:
    return os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")


def available() -> list:
    """Providers we have a key for, in default order."""
    out = []
    if keys.get("ANTHROPIC_API_KEY"):
        out.append("claude")
    if keys.get("XAI_API_KEY"):
        out.append("grok")
    return out


def default_provider() -> str:
    have = available()
    pref = os.environ.get("JARVIS_PROVIDER", "").strip().lower()
    if pref in have:
        return pref
    return have[0] if have else ""


# ---------------------------------------------------------------- Grok

def grok_call(system: str, items: list, tools: list = None, max_tokens: int = 2000, timeout: int = 90) -> dict:
    key = keys.get("XAI_API_KEY")
    if not key:
        raise LLMError("I don't have a Grok key yet. Run setup-keys.bat to add one.")
    # Only fields shown in xAI's own docs (model, input, tools); extra options are not guessed.
    body = {
        "model": GROK_MODEL,
        "input": [{"role": "system", "content": system}] + items,
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        base_url() + "/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "User-Agent": "JarvisAssistant/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LLMError("Grok rejected my key. Run setup-keys.bat and paste it again.")
        if e.code == 404:
            raise LLMError(f"Grok doesn't know the model '{GROK_MODEL}'. Set JARVIS_GROK_MODEL to a current model name.")
        if e.code == 429:
            raise LLMError("Grok says I'm asking too often, or the account is out of credit.")
        raise LLMError(f"Grok returned an error ({e.code}).")
    except (urllib.error.URLError, OSError, ValueError):
        raise LLMError("I can't reach Grok right now. Check the internet connection.")


def grok_text(data: dict) -> str:
    """Pull the assistant's words out of a Responses API reply."""
    parts = []
    for item in data.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
    return "".join(parts).strip()


# ---------------------------------------------------------------- Claude

def _claude_client():
    key = keys.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("I don't have a Claude key yet. Run setup-keys.bat to add one.")
    try:
        import anthropic
    except ImportError:
        raise LLMError("The Claude library isn't installed. Run: py -m pip install anthropic")
    return anthropic.Anthropic(api_key=key)


def complete(provider: str, system: str, prompt: str, max_tokens: int = 4000) -> str:
    """One question, one answer, no tools. Used for writing code."""
    if provider == "grok":
        return grok_text(grok_call(system, [{"role": "user", "content": prompt}], max_tokens=max_tokens, timeout=180))
    if provider == "claude":
        client = _claude_client()
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:  # network, auth, quota...
            raise LLMError(f"Claude didn't answer ({type(e).__name__}).")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    raise LLMError("I need a Claude or Grok key to do that. Run setup-keys.bat.")
