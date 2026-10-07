"""Runs ONE skill in its own isolated Python process. Never imported by Jarvis itself.

Usage (done by jarvis/skills.py):  python -I skill_runner.py check|run <skill.py> [argument]
Prints a single line starting with JARVIS_RESULT: followed by JSON.
"""
import importlib.util
import json
import sys
import urllib.error
import urllib.request

PREFIX = "JARVIS_RESULT:"
sys.dont_write_bytecode = True  # no __pycache__ clutter next to the skill


def _blocked(*args, **kwargs):
    raise urllib.error.URLError("blocked: skills may only use http and https")


# A skill may fetch web pages, but never local files (file://) or ftp.
urllib.request.FileHandler.file_open = _blocked
urllib.request.FTPHandler.ftp_open = _blocked


def _emit(obj):
    print(PREFIX + json.dumps(obj))


def main():
    mode, path = sys.argv[1], sys.argv[2]
    try:
        spec = importlib.util.spec_from_file_location("jarvis_skill", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "run", None)):
            _emit({"ok": False, "error": "the skill has no run() function"})
            return
        if mode == "check":
            _emit({"ok": True})
            return
        arg = sys.argv[3] if len(sys.argv) > 3 else ""
        _emit({"ok": True, "result": str(mod.run(arg))[:1500]})
    except Exception as e:  # report, never crash noisily
        _emit({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})


if __name__ == "__main__":
    main()
