"""Tools Jarvis can use. Each tool is a plain function returning a string."""
from __future__ import annotations

import ast
import json
import operator
import platform
import shutil
from datetime import datetime
from pathlib import Path

NOTES_FILE = Path.home() / ".jarvis_notes.json"

# ---------- safe calculator ----------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    """Evaluate a math expression like '2 * (3 + 4) ** 2'."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception:
        return "Error: I can only do basic arithmetic (+ - * / ** % //)."


def get_time(_: str = "") -> str:
    now = datetime.now()
    return now.strftime("It is %A, %d %B %Y, %I:%M %p.")


def system_info(_: str = "") -> str:
    total, used, free = shutil.disk_usage("/")
    gb = 1024 ** 3
    return (
        f"OS: {platform.system()} {platform.release()} | "
        f"Python {platform.python_version()} | "
        f"Disk: {used // gb} GB used of {total // gb} GB ({free // gb} GB free)"
    )


# ---------- notes ----------
def _load_notes() -> list[str]:
    try:
        return json.loads(NOTES_FILE.read_text())
    except Exception:
        return []


def add_note(text: str) -> str:
    text = text.strip()
    if not text:
        return "Nothing to save."
    notes = _load_notes()
    notes.append(text)
    NOTES_FILE.write_text(json.dumps(notes, indent=2))
    return f"Saved note #{len(notes)}."


def list_notes(_: str = "") -> str:
    notes = _load_notes()
    if not notes:
        return "You have no notes."
    return "\n".join(f"{i}. {n}" for i, n in enumerate(notes, 1))


def clear_notes(_: str = "") -> str:
    NOTES_FILE.write_text("[]")
    return "All notes cleared."


# ---------- online tools (fail gracefully when offline) ----------
def _get_json(url: str, timeout: int = 8):
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "JarvisAssistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def weather(city: str = "") -> str:
    """Current weather for a city via Open-Meteo (no API key)."""
    import urllib.parse

    city = city.strip() or "Karachi"
    try:
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?count=1&name="
            + urllib.parse.quote(city)
        )
        if not geo.get("results"):
            return f"I couldn't find a place called {city}."
        g = geo["results"][0]
        w = _get_json(
            "https://api.open-meteo.com/v1/forecast?current=temperature_2m,"
            f"wind_speed_10m,relative_humidity_2m&latitude={g['latitude']}&longitude={g['longitude']}"
        )["current"]
        return (
            f"{g['name']}, {g.get('country', '')}: {w['temperature_2m']}°C, "
            f"humidity {w['relative_humidity_2m']}%, wind {w['wind_speed_10m']} km/h."
        )
    except Exception:
        return "I can't reach the weather service right now."


def wiki(topic: str) -> str:
    """Short Wikipedia summary of a topic."""
    import urllib.parse

    topic = topic.strip()
    if not topic:
        return "What should I look up?"
    try:
        d = _get_json(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(topic.replace(" ", "_"))
        )
        text = d.get("extract") or "I found no summary for that."
        return text if len(text) < 500 else text[:497].rsplit(" ", 1)[0] + "..."
    except Exception:
        return f"I couldn't find anything on {topic}, or I'm offline."


_JOKES = [
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, sees two tables and asks: may I join you?",
    "I'd tell you a recursion joke, but first I'd have to tell you a recursion joke.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
]


def joke(_: str = "") -> str:
    import random

    return random.choice(_JOKES)


def status_report(_: str = "") -> str:
    """Movie-style systems check."""
    return (
        "All systems nominal, sir. Arc reactor at 100 percent. "
        + get_time()
        + " "
        + system_info()
    )


TOOLS = {
    "weather": (weather, "Current weather. Input: city name."),
    "wiki": (wiki, "Wikipedia summary. Input: topic."),
    "joke": (joke, "Tell a joke. No input."),
    "status_report": (status_report, "Full systems status report. No input."),
    "calculate": (calculate, "Evaluate arithmetic. Input: expression string."),
    "get_time": (get_time, "Get current date and time. No input."),
    "system_info": (system_info, "Get OS, Python and disk info. No input."),
    "add_note": (add_note, "Save a note. Input: note text."),
    "list_notes": (list_notes, "List saved notes. No input."),
    "clear_notes": (clear_notes, "Delete all notes. No input."),
}


def run_tool(name: str, arg: str = "") -> str:
    if name not in TOOLS:
        return f"Unknown tool: {name}"
    return TOOLS[name][0](arg)
