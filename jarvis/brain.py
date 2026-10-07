"""Jarvis's brain: decides which tool to call for a user message.

Modes:
- Claude or Grok: used when a key is saved (python -m jarvis --setup) or set in the environment.
  The AI chooses tools itself. Say "use grok" / "use claude" to switch, or "ask grok ..." once.
- Offline: simple rule-based routing, no key or internet needed.

Skill commands (learn / approve / reject ...) are handled first, before any AI sees the message,
so installing new abilities can only ever happen because the user said so.
"""
from __future__ import annotations

import json
import os
import re

from . import keys, llm, memory, skills
from .tools import TOOLS, run_tool

MODEL = llm.CLAUDE_MODEL
SYSTEM = (
    "You are J.A.R.V.I.S., a dry-witted, impeccably polite British AI butler. "
    "Address the user as 'sir' occasionally. Be concise: replies are spoken aloud, "
    "so use one to three short sentences and no markdown. Use tools when they help. "
    "You can grow new abilities: if the user wants one you lack, tell them to say "
    "'learn how to' followed by the topic. Installed skills appear as tools. "
    "Never claim to have installed or changed anything yourself; only the user's approval does that."
)

_PROVIDER_RE = re.compile(r"^(?:please\s+)?(?:use|switch to|change to|go to)\s+(grok|claude)(?:\s+(?:now|instead|brain))?[.!]*$", re.I)
_ASK_RE = re.compile(r"^(?:ask|tell|check with)\s+(grok|claude)[,:]?\s+(.+)$", re.I)
_PRE_RE = re.compile(r"^\s*(?:hey |ok |okay )?jarvis[,.!:]?\s*", re.I)


_FORGET_RE = re.compile(r"\b(forget|clear|erase|delete|wipe)\b.*\b(memory|memories|conversations?|chat history|everything)\b", re.I)
_RECALL_RE = re.compile(
    r"what (did|have) (we|i)\b|do you remember|remind me what|\brecall\b|our (last |previous )?(chat|conversation)s?\b|conversation history",
    re.I,
)


def _offline(message: str) -> str:
    m = message.strip()
    low = m.lower()

    m = re.sub(r"^\s*(hey |ok |okay )?jarvis[,.!:]?\s*", "", m, flags=re.I)
    low = m.lower()

    if re.search(r"(update|upgrade) (yourself|jarvis|your software)|check (for )?(an )?updates?|any updates", low):
        return run_tool("update_self")
    if _FORGET_RE.search(low):
        return run_tool("clear_memory")
    if _RECALL_RE.search(low):
        return run_tool("recall", m)
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

    hit = skills.match_trigger(m)
    if hit:
        return run_tool(hit[0], hit[1])

    if re.search(r"\b(hi|hello|hey|salam)\b", low):
        return "At your service, sir. Ask about the weather, a topic, the time, or say 'status report'."
    if "help" in low:
        return "I can tell the time, do math, keep notes, and report system info."
    return "I'm in offline mode, so I only know a few commands. Run setup-keys.bat to add a Claude or Grok key for full conversation."


class Jarvis:
    def __init__(self) -> None:
        self.history: list = []   # Claude conversation
        self.ghistory: list = []  # Grok conversation
        self._client = None
        have = llm.available()
        if "claude" in have:
            try:
                import anthropic  # noqa: F401
            except ImportError:
                have.remove("claude")  # key saved but library missing: don't pretend
        self.providers = have
        pref = os.environ.get("JARVIS_PROVIDER", "").strip().lower()
        self.provider = pref if pref in have else (have[0] if have else "")
        skills.register()

    @property
    def mode(self) -> str:
        return self.provider or "offline"

    # ---- helpers
    def _complete(self, system: str, prompt: str) -> str:
        return llm.complete(self.provider, system, prompt)

    def _tool_specs(self) -> list:
        return [
            {
                "name": name,
                "description": desc,
                "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
            }
            for name, (_, desc) in TOOLS.items()
        ]

    def _grok_tools(self) -> list:
        return [
            {
                "type": "function",
                "name": name,
                "description": desc,
                "parameters": {"type": "object", "properties": {"input": {"type": "string"}}},
            }
            for name, (_, desc) in TOOLS.items()
        ]

    def _system(self) -> str:
        try:
            past = memory.context_block()
        except Exception:
            past = ""
        if not past:
            return SYSTEM
        return (
            SYSTEM
            + "\n\nYour memory of this user's conversations over the past week (oldest first). "
            "Use it naturally when relevant; don't recite it unprompted:\n" + past
        )

    # ---- public
    def ask(self, message: str) -> str:
        reply = self._route(message)
        if not (_FORGET_RE.search(message) or _RECALL_RE.search(message) or reply.startswith("[code]")):
            try:
                memory.add("user", message)
                memory.add("jarvis", reply)
            except Exception:
                pass  # memory must never break a conversation
        return reply

    def _route(self, message: str) -> str:
        m = _PRE_RE.sub("", message.strip())

        # 1) skill commands: learn / approve / reject / show / list / remove (never reaches an AI)
        try:
            r = skills.handle_command(message, self._complete if self.provider else None, self.provider)
        except Exception as e:
            r = f"I hit a problem with that skill command ({type(e).__name__}), sir."
        if r is not None:
            return r

        # 2) choose the brain
        sw = _PROVIDER_RE.match(m)
        if sw:
            want = sw.group(1).lower()
            if want in self.providers:
                self.provider = want
                return f"Switched to {want.capitalize()}, sir."
            return f"I don't have a {want.capitalize()} key yet. Run setup-keys.bat to add one."
        one = _ASK_RE.match(m)
        if one:
            want = one.group(1).lower()
            if want not in self.providers:
                return f"I don't have a {want.capitalize()} key yet. Run setup-keys.bat to add one."
            return self._answer(one.group(2), want)

        return self._answer(message, self.provider)

    # ---- the AI brains
    def _answer(self, message: str, provider: str = "") -> str:
        try:
            if provider == "claude":
                return self._answer_claude(message)
            if provider == "grok":
                return self._answer_grok(message)
        except llm.LLMError as e:
            return str(e)
        except Exception as e:  # network trouble etc.: say so instead of crashing the page
            return f"I couldn't reach {provider.capitalize()} just now ({type(e).__name__}), sir."
        return _offline(message)

    def _answer_claude(self, message: str) -> str:
        if self._client is None:
            self._client = llm._claude_client()
        n0 = len(self.history)
        self.history.append({"role": "user", "content": message})
        try:
            for _ in range(5):  # max tool-use rounds
                resp = self._client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=self._system(),
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
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                self.history.append({"role": "user", "content": results})
        except Exception:
            del self.history[n0:]  # keep the conversation valid after a failed call
            raise
        return "Sorry, I got stuck. Please try again."

    def _answer_grok(self, message: str) -> str:
        n0 = len(self.ghistory)
        self.ghistory.append({"role": "user", "content": message})
        try:
            for _ in range(5):
                data = llm.grok_call(self._system(), self.ghistory, self._grok_tools())
                calls = [o for o in data.get("output", []) or [] if o.get("type") == "function_call"]
                if not calls:
                    text = llm.grok_text(data)
                    self.ghistory.append({"role": "assistant", "content": text})
                    return text or "I have nothing to add, sir."
                for c in calls:
                    self.ghistory.append({
                        "type": "function_call", "call_id": c.get("call_id", ""),
                        "name": c.get("name", ""), "arguments": c.get("arguments") or "{}",
                    })
                for c in calls:
                    try:
                        args = json.loads(c.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    arg = args.get("input", "") if isinstance(args, dict) else ""
                    out = run_tool(c.get("name", ""), str(arg))
                    self.ghistory.append({"type": "function_call_output", "call_id": c.get("call_id", ""), "output": out})
        except Exception:
            del self.ghistory[n0:]
            raise
        return "Sorry, I got stuck. Please try again."
