"""Jarvis's brain: decides which tool to call for a user message.

Two modes:
- Claude mode: used when ANTHROPIC_API_KEY is set and `anthropic` is installed.
  Claude chooses tools via native tool use.
- Offline mode: simple rule-based routing, no API key or internet needed.
"""
from __future__ import annotations

import os
import re

from .tools import TOOLS, run_tool

MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5-5")
SYSTEM = (
    "You are J.A.R.V.I.S., a dry-witted, impeccably polite British AI butler. "
    "Address the user as 'sir' occasionally. Be concise: replies are spoken aloud, "
    "so use one to three short sentences and no markdown. Use tools when they help."
)


def _offline(message: str) -> str:
    m = message.strip()
    low = m.lower()

    m = re.sub(r"^\s*(hey |ok |okay )?jarvis[,.!:]?\s*", "", m, flags=re.I)
    low = m.lower()

    if re.search(r"(update|upgrade) (yourself|jarvis|your software)|check (for )?(an )?updates?|any updates", low):
        return run_tool("update_self")
    if re.search(r"\b(status|diagnostic|systems check|report)\b", low):
        return run_tool("status_report")
    if re.search(r"\bjoke\b", low):
        return run_tool("joke")
    w = re.search(r"weather(?: in| for| at)?\s*(.*)$", low)
    if w:
        return run_tool("weather", w.group(1).strip(" ?.!"))
    q = re.match(r"^(?:who is|who was|what is a|what is an|tell me about|wiki|look up|define)\s+(.+?)[?.!]*$", m, re.I)
    if q and not re.fullmatch(r"[\d\s+\-*/().%^]+", q.group(1)):
        return run_tool("wiki", q.group(1))

    if re.search(r"\b(time|date|day is it)\b", low):
        return run_tool("get_time")
    if re.search(r"\b(system|disk|os info|specs)\b", low):
        return run_tool("system_info")
    if re.search(r"\b(clear|delete) (all )?(my )?notes\b", low):
        return run_tool("clear_notes")
    if re.search(r"\b(show|list|read|what are)\b.*\bnotes?\b", low):
        return run_tool("list_notes")
    note = re.match(r"^(?:note|remember|save note|add note)[:\s]+(.+)$", m, re.I)
    if note:
        return run_tool("add_note", note.group(1))

    calc = re.match(r"^(?:calc(?:ulate)?|what is|what's|compute)?\s*([\d\s+\-*/().%^]+)\??$", low)
    if calc and re.search(r"\d", calc.group(1)):
        return run_tool("calculate", calc.group(1).replace("^", "**"))

    if re.search(r"\b(hi|hello|hey|salam)\b", low):
        return "At your service, sir. Ask about the weather, a topic, the time, or say 'status report'."
    if "help" in low:
        return "I can tell the time, do math, keep notes, and report system info."
    return "I'm in offline mode, so I only know a few commands. Set ANTHROPIC_API_KEY for full conversation."


class Jarvis:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.client = None
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic

                self.client = anthropic.Anthropic(api_key=key)
            except ImportError:
                self.client = None

    @property
    def mode(self) -> str:
        return "claude" if self.client else "offline"

    def _tool_specs(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": desc,
                "input_schema": {
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                },
            }
            for name, (_, desc) in TOOLS.items()
        ]

    def ask(self, message: str) -> str:
        if not self.client:
            return _offline(message)

        self.history.append({"role": "user", "content": message})
        for _ in range(5):  # max tool-use rounds
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM,
                tools=self._tool_specs(),
                messages=self.history,
            )
            self.history.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text").strip()
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = run_tool(block.name, (block.input or {}).get("input", ""))
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": out}
                    )
            self.history.append({"role": "user", "content": results})
        return "Sorry, I got stuck. Please try again."
