"""Skills: new abilities Jarvis writes for itself, safely.

"Learn how to check bitcoin prices" -> an AI (Claude or Grok) writes a small Python file, Jarvis
checks it, tells you what it does, and installs it only after you say "approve". It works at
once, with no restart, and is kept in ~/.jarvis_skills (outside the Jarvis folder) so GitHub
updates never erase it.

Safety layers, honestly described:
 1. Nothing is installed without your spoken or typed approval (approval is handled here,
    before any AI sees your message, and is never something the AI can trigger itself).
 2. A static check rejects files that import anything outside a short safe list, touch files,
    run programs, or use eval/exec/dunder tricks. This stops mistakes and casual misuse; it is
    NOT a sandbox against a determined attacker, so approval is the real gate.
 3. Each skill runs in a separate Python process with no API keys in its environment, a time
    limit, and no access to local files through URLs.
 4. A skill that fails to load is skipped and Jarvis keeps working.
Jarvis's own core files (updater, server, supervisor) are not editable by skills.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKILLS_DIR = Path.home() / ".jarvis_skills"
PENDING_MAX_AGE = 24 * 3600
RUN_TIMEOUT = 25
RUNNER = Path(__file__).with_name("skill_runner.py")
PREFIX = "JARVIS_RESULT:"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
ALLOWED_MODULES = {
    "json", "re", "math", "cmath", "datetime", "time", "calendar", "statistics", "random",
    "collections", "itertools", "functools", "decimal", "fractions", "string", "textwrap",
    "html", "csv", "base64", "hashlib", "typing", "difflib", "heapq", "bisect", "operator",
    "enum", "dataclasses", "urllib",
}
ALLOWED_URLLIB = {"request", "parse", "error"}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "globals", "locals", "vars", "getattr",
    "setattr", "delattr", "breakpoint", "exit", "quit", "memoryview",
}
# Attribute names that would reach the operating system through an allowed module
# (for example urllib.request.os). Any attribute starting with an underscore is blocked too.
FORBIDDEN_ATTRS = {
    "os", "sys", "io", "tempfile", "shutil", "subprocess", "posixpath", "ntpath", "importlib",
    "builtins", "modules", "environ", "system", "popen", "startfile", "contextlib", "warnings",
}
_NESTED_QUANT = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")  # e.g. (a+)+ can freeze a regex engine
MAX_CODE = 12000

CODEGEN_SYSTEM = """You write small "skills" for a voice assistant named Jarvis.
Reply with ONE Python 3 file inside a single ```python code block and nothing else.

The file must contain exactly these top-level pieces:
  NAME = "snake_case_name"        # 3-30 chars: lowercase letters, digits, underscores
  DESCRIPTION = "One sentence: what it does and when to use it."
  TRIGGERS = [r"regex"]           # optional, 0-5 regexes matching what the user might say; use ONE capture group for the useful part (a ticker, a city, a topic)
  def run(arg: str) -> str:       # arg is the captured text or the user's request; return one or two short plain sentences that sound natural when spoken (no markdown, no emoji)

Rules:
- Python 3.8 compatible, standard library only. The only imports allowed: %s.
- No file access, no running programs, no eval/exec/compile/open/getattr/globals, and no names that start with a double underscore.
- Network only through urllib.request, always with timeout=10, to public HTTPS APIs that need no key and no login. Never ask for, read or store passwords or keys.
- Never place trades, orders, payments or messages for anyone. Researching, explaining, calculating and simulating are fine. For anything about investing, money or health, end the answer with a short note that it is not professional advice.
- run() must never raise: catch errors and return a short explanation.
- Keep it under 150 lines.""" % ", ".join(sorted(ALLOWED_MODULES))


# ------------------------------------------------------------------ paths

def _pending_dir() -> Path:
    return SKILLS_DIR / "_pending"


def _removed_dir() -> Path:
    return SKILLS_DIR / "_removed"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ------------------------------------------------------------------ checking code

def _meta(tree: ast.AST) -> dict:
    """Read NAME / DESCRIPTION / TRIGGERS without running the code."""
    out = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            if key in ("NAME", "DESCRIPTION", "TRIGGERS"):
                try:
                    out[key] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
    return out


def imports_used(code: str) -> list:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    return sorted(mods)


def validate(code: str) -> list:
    """Return a list of problems; empty means the file passed the static check."""
    errors = []
    if len(code) > MAX_CODE:
        return ["the file is too long"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error on line {e.lineno}"]

    meta = _meta(tree)
    name = meta.get("NAME")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append("NAME must be a snake_case string of 3-30 characters")
    desc = meta.get("DESCRIPTION")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 200:
        errors.append("DESCRIPTION must be one short sentence")
    trig = meta.get("TRIGGERS", [])
    if not isinstance(trig, list) or len(trig) > 5 or not all(isinstance(t, str) and len(t) <= 100 for t in trig):
        errors.append("TRIGGERS must be a list of up to 5 short regex strings")
    else:
        for t in trig:
            try:
                re.compile(t)
            except re.error:
                errors.append("a TRIGGERS pattern is not a valid regex")
                break
            if _NESTED_QUANT.search(t):
                errors.append("a TRIGGERS pattern is too complicated")
                break

    has_run = any(
        isinstance(n, ast.FunctionDef) and n.name == "run" and len(n.args.args) >= 1 for n in tree.body
    )
    if not has_run:
        errors.append("there must be a top-level function run(arg)")

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                root, _, sub = a.name.partition(".")
                if root not in ALLOWED_MODULES or (root == "urllib" and sub.split(".")[0] not in ALLOWED_URLLIB):
                    errors.append(f"import of '{a.name}' is not allowed")
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            root = mod.split(".")[0]
            if n.level or root not in ALLOWED_MODULES:
                errors.append(f"import from '{mod or '.'}' is not allowed")
            elif root == "urllib":
                parts = mod.split(".")
                if len(parts) > 1 and parts[1] not in ALLOWED_URLLIB:
                    errors.append(f"import from '{mod}' is not allowed")
                if len(parts) == 1 and any(a.name not in ALLOWED_URLLIB for a in n.names):
                    errors.append("only urllib.request, urllib.parse and urllib.error are allowed")
        elif isinstance(n, ast.Name):
            if n.id in FORBIDDEN_NAMES or (n.id.startswith("__") and n.id != "__name__"):
                errors.append(f"use of '{n.id}' is not allowed")
        elif isinstance(n, ast.Attribute):
            if (n.attr.startswith("_") and n.attr != "__name__") or n.attr in FORBIDDEN_ATTRS:
                errors.append(f"use of '.{n.attr}' is not allowed")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            # blocks "{0.__class__}".format(x)-style tricks; the usual main guard is fine
            if "__" in n.value and n.value not in ("__main__", "__name__"):
                errors.append("text containing a double underscore is not allowed")
    # keep the list short and free of duplicates
    seen, uniq = set(), []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq[:6]


# ------------------------------------------------------------------ running skills

def _safe_env() -> dict:
    """Minimal environment for a skill process: no API keys, nothing personal."""
    keep = (
        "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "LANG",
        # network settings only, so skills still work behind a proxy
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    )
    return {k: v for k, v in os.environ.items() if k in keep}


def _run_runner(mode: str, path: Path, arg: str = "", timeout: int = 0) -> dict:
    timeout = timeout or RUN_TIMEOUT
    cmd = [sys.executable, "-I", str(RUNNER), mode, str(path)]
    if mode == "run":
        cmd.append(arg[:500])
    try:
        p = subprocess.run(
            cmd, env=_safe_env(), cwd=str(SKILLS_DIR if SKILLS_DIR.exists() else Path.home()),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "it took too long"}
    except OSError as e:
        return {"ok": False, "error": f"couldn't start it ({e})"}
    for line in reversed(p.stdout.decode("utf-8", "replace").splitlines()):
        if line.startswith(PREFIX):
            try:
                return json.loads(line[len(PREFIX):])
            except ValueError:
                break
    return {"ok": False, "error": "it crashed"}


def run_skill(name: str, arg: str = "") -> str:
    path = SKILLS_DIR / f"{name}.py"
    if not path.exists():
        return f"I don't have a skill called {name}."
    res = _run_runner("run", path, arg)
    if res.get("ok"):
        return (res.get("result") or "That skill gave no answer.").strip()
    return f"The {name.replace('_', ' ')} skill failed: {res.get('error', 'unknown error')}."


# ------------------------------------------------------------------ registry

_registered = set()


def active() -> list:
    """Installed skills: [{name, description, triggers, path}]. Reads metadata without running code."""
    out = []
    if not SKILLS_DIR.exists():
        return out
    for p in sorted(SKILLS_DIR.glob("*.py")):
        try:
            code = p.read_text(encoding="utf-8")
            if validate(code):
                continue  # edited by hand into something unsafe/broken: ignore it
            m = _meta(ast.parse(code))
            if m.get("NAME") != p.stem:
                continue
            out.append({"name": p.stem, "description": m["DESCRIPTION"], "triggers": m.get("TRIGGERS", []), "path": p})
        except (OSError, SyntaxError):
            continue
    return out


def register(tools: dict = None) -> int:
    """Make installed skills available as tools. Safe to call again after any change."""
    if tools is None:
        from .tools import TOOLS as tools
    for n in list(_registered):
        tools.pop(n, None)
    _registered.clear()
    count = 0
    for s in active():
        if s["name"] in tools:
            continue  # never shadow a built-in tool
        tools[s["name"]] = ((lambda arg="", _n=s["name"]: run_skill(_n, arg)), s["description"])
        _registered.add(s["name"])
        count += 1
    return count


def match_trigger(message: str):
    """For offline mode: does this message match an installed skill's TRIGGERS? -> (name, arg) or None."""
    message = message[:300]
    for s in active():
        for t in s["triggers"]:
            try:
                m = re.search(t, message, re.I)
            except re.error:
                continue
            if m:
                arg = m.group(1) if m.lastindex else message
                return s["name"], (arg or message).strip()
    return None


# ------------------------------------------------------------------ pending proposals

def pending() -> dict:
    """{name: {path, request, created}} for proposals waiting for approval. Old ones are discarded."""
    d = _pending_dir()
    out = {}
    if not d.exists():
        return out
    now = time.time()
    for p in d.glob("*.py"):
        try:
            if now - p.stat().st_mtime > PENDING_MAX_AGE:
                p.unlink()
                continue
            meta = {}
            mj = p.with_suffix(".json")
            if mj.exists():
                meta = json.loads(mj.read_text(encoding="utf-8"))
            out[p.stem] = {"path": p, "request": meta.get("request", ""), "created": p.stat().st_mtime}
        except (OSError, ValueError):
            continue
    return out


def _extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", text, re.S | re.I)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n" if "def run" in text else ""


def create(request: str, complete, provider: str = "") -> str:
    """Ask an AI to write a skill, check it, and stage it for approval."""
    if complete is None:
        return "I need a Claude or Grok key to write new skills, sir. Run setup-keys.bat to add one."
    request = " ".join(request.split())[:500]
    prompt = f"Request from the user: {request}\n\nWrite the skill."
    code, errors = "", []
    for attempt in range(2):
        try:
            reply = complete(CODEGEN_SYSTEM, prompt)
        except Exception as e:  # LLMError or anything unexpected
            return f"I couldn't get the AI to write it: {e}"
        code = _extract_code(reply)
        errors = validate(code) if code else ["no code came back"]
        if not errors:
            break
        prompt = (
            f"Request from the user: {request}\n\nYour previous skill was rejected:\n- "
            + "\n- ".join(errors)
            + f"\n\nPrevious code:\n```python\n{code}\n```\nReply with the full corrected file in one ```python block."
        )
    if errors:
        return "I tried twice but couldn't write a safe version. The problem was: " + "; ".join(errors[:3]) + "."

    meta = _meta(ast.parse(code))
    name = meta["NAME"]
    if name in _builtin_names():
        name = f"{name}_skill"
        code = re.sub(r"^NAME\s*=.*$", f'NAME = "{name}"', code, count=1, flags=re.M)
        if validate(code):
            return "That name clashed with a built-in tool and I couldn't fix it. Please try again."
    _pending_dir().mkdir(parents=True, exist_ok=True)
    p = _pending_dir() / f"{name}.py"
    p.write_text(code, encoding="utf-8")
    p.with_suffix(".json").write_text(
        json.dumps({"request": request, "provider": provider, "created": time.time()}), encoding="utf-8"
    )
    res = _run_runner("check", p, timeout=15)
    if not res.get("ok"):
        p.unlink()
        p.with_suffix(".json").unlink()
        return f"I wrote a skill but it wouldn't even load ({res.get('error')}), so I threw it away. Please try again."

    mods = ", ".join(imports_used(code)) or "nothing extra"
    lines = len(code.splitlines())
    return (
        f"I've written a new skill called {name.replace('_', ' ')}: {meta['DESCRIPTION']} "
        f"It has {lines} lines, uses {mods}, and cannot read your files or run programs. "
        f"It is NOT installed yet. Say 'approve {name.replace('_', ' ')}' to install it, "
        f"'show the code' to read it, or 'reject {name.replace('_', ' ')}'."
    )


def _builtin_names() -> set:
    from .tools import TOOLS

    return {n for n in TOOLS if n not in _registered}


def _resolve(spoken: str, items: dict):
    """Pick a proposal/skill by (spoken) name; the only one if no name was given."""
    if spoken:
        key = _norm(spoken)
        if key in items:
            return key, None
        hits = [n for n in items if key and (key in n or n in key)]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"I can't find one called {spoken.strip()}."
        return None, "Which one, sir? " + ", ".join(h.replace("_", " ") for h in hits) + "."
    if len(items) == 1:
        return next(iter(items)), None
    if not items:
        return None, ""
    return None, "Which one, sir? " + ", ".join(n.replace("_", " ") for n in items) + "."


def approve(spoken: str = "") -> str:
    items = pending()
    if not items:
        return "There's nothing waiting for approval, sir."
    name, err = _resolve(spoken, items)
    if not name:
        return err
    src = items[name]["path"]
    code = src.read_text(encoding="utf-8")
    problems = validate(code)
    if problems:
        return "I re-checked it and it no longer passes: " + "; ".join(problems[:2]) + ". I won't install it."
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    dst = SKILLS_DIR / f"{name}.py"
    if dst.exists():  # replacing an older version of the same skill: keep the old one
        _removed_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, _removed_dir() / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.py")
    shutil.move(str(src), str(dst))
    mj = src.with_suffix(".json")
    if mj.exists():
        shutil.move(str(mj), str(SKILLS_DIR / f"{name}.json"))
    register()
    return f"Installed, sir. The {name.replace('_', ' ')} skill is ready now. No restart was needed."


def reject(spoken: str = "") -> str:
    items = pending()
    name, err = _resolve(spoken, items)
    if not name:
        return err or "There's nothing waiting for approval, sir."
    items[name]["path"].unlink()
    mj = items[name]["path"].with_suffix(".json")
    if mj.exists():
        mj.unlink()
    return f"Discarded the {name.replace('_', ' ')} skill. Nothing was installed."


def remove(spoken: str) -> str:
    items = {s["name"]: s for s in active()}
    name, err = _resolve(spoken, items)
    if not name:
        return err or "You have no installed skills, sir."
    _removed_dir().mkdir(parents=True, exist_ok=True)
    shutil.move(str(items[name]["path"]), str(_removed_dir() / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.py"))
    register()
    return f"Removed the {name.replace('_', ' ')} skill. A copy is kept in the removed folder."


def show(spoken: str = "") -> str:
    pend = pending()
    items = {n: {"path": v["path"], "src": "waiting for approval"} for n, v in pend.items()}
    if not items or spoken:
        for sk in active():
            items.setdefault(sk["name"], {"path": sk["path"], "src": "installed"})
    name, err = _resolve(spoken, items)
    if not name:
        return err or "I have no skills to show, sir."
    src = items[name]["src"]
    code = items[name]["path"].read_text(encoding="utf-8")
    if len(code) > 2500:
        code = code[:2500] + "\n# ... (shortened)"
    return f"[code] {name} ({src}):\n{code}"


def listing() -> str:
    a, p = active(), pending()
    parts = []
    if a:
        parts.append(f"I have {len(a)} skill{'s' if len(a) != 1 else ''}: " + ", ".join(s["name"].replace("_", " ") for s in a) + ".")
    else:
        parts.append("I haven't learned any extra skills yet, sir. Try 'learn how to' and a topic.")
    if p:
        parts.append("Waiting for your approval: " + ", ".join(n.replace("_", " ") for n in p) + ".")
    return " ".join(parts)


# ------------------------------------------------------------------ spoken / typed commands

_PRE = re.compile(r"^\s*(?:hey |ok |okay )?jarvis[,.!:]?\s*", re.I)
_LEARN = re.compile(
    r"^(?:please\s+)?(?:learn(?: how)? to|learn about|teach yourself(?: to| how to| about)?|"
    r"(?:create|make|add|write) (?:a |yourself a )?(?:new )?skill(?: (?:to|that|for|which|so you can))?|"
    r"upgrade yourself(?: to| so you can)?|update yourself to|change your (?:own )?code to)\s+(?P<req>.+)$",
    re.I,
)
_APPROVE = re.compile(
    r"^(?:yes[, ]+)?(?:go ahead and |please )?(?:approve|install)(?: the| that| this)?(?: skill| it)?"
    r"(?:\s+(?P<n>[a-z0-9_ ]+?))?[.!]*$",
    re.I,
)
_REJECT = re.compile(r"^(?:reject|discard|decline|cancel)(?: the| that| this)?(?: skill)?(?:\s+(?P<n>[a-z0-9_ ]+?))?[.!]*$", re.I)
_SHOW = re.compile(r"^(?:show|read|display)(?: me)?(?: the)?(?: new)? (?:code|skill)(?: (?:for|of))?(?: (?P<n>[a-z0-9_ ]+?))?[.!?]*$", re.I)
_LIST = re.compile(r"^(?:list|show)(?: me)?(?: all| my| your)? skills[.!?]*$|^what skills do you have[.!?]*$", re.I)
_REMOVE = re.compile(r"^(?:remove|delete|uninstall|disable)(?: the)? skill (?P<n>[a-z0-9_ ]+?)[.!]*$", re.I)


def handle_command(message: str, complete=None, provider: str = ""):
    """Handle skill commands. Returns the reply, or None if the message isn't about skills.

    Runs BEFORE any AI sees the message, so approving can only ever come from the user.
    """
    m = _PRE.sub("", message.strip())
    if _LIST.match(m):
        return listing()
    r = _REMOVE.match(m)
    if r:
        return remove(r.group("n"))
    r = _SHOW.match(m)
    if r:
        return show(r.group("n") or "")
    r = _LEARN.match(m)
    if r and not re.match(r"(?i)(?:the |a )?(?:latest|newest|newer|new)\b|version\b", r.group("req")):
        return create(m, complete, provider)
    r = _APPROVE.match(m)
    if r:
        spoken = (r.group("n") or "").strip()
        if _norm(spoken) in ("it", "skill", "the_skill"):
            spoken = ""
        # "install python" etc. only counts when it names something we actually have waiting
        if not pending():
            return "There's nothing waiting for approval, sir." if re.match(r"(?i)^(?:yes[, ]+)?(?:go ahead and |please )?approve", m) else None
        return approve(spoken)
    r = _REJECT.match(m)
    if r and pending():  # "cancel" means something else when nothing is waiting
        spoken = (r.group("n") or "").strip()
        if spoken:
            name, _ = _resolve(spoken, pending())
            if not name:
                return None  # e.g. "cancel the timer" is not about skills
        return reject(spoken)
    return None
