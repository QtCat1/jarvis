import os
import time

from jarvis import skills
from jarvis.tools import TOOLS, run_tool
from jarvis import Jarvis

CONVERTER = '''import re
NAME = "mile_converter"
DESCRIPTION = "Converts miles to kilometres."
TRIGGERS = [r"convert (\\d+(?:\\.\\d+)?) miles"]

def run(arg):
    m = re.search(r"\\d+(?:\\.\\d+)?", arg)
    if not m:
        return "Tell me how many miles, sir."
    return "%.1f kilometres." % (float(m.group(0)) * 1.609344)
'''


def reply_with(code):
    return lambda system, prompt: "Here you go:\n```python\n" + code + "\n```"


def stage_and_approve(code=CONVERTER, name="mile converter"):
    out = skills.create("learn how to convert miles", reply_with(code))
    assert "NOT installed yet" in out, out
    return skills.handle_command("approve " + name)


def test_create_stages_but_does_not_install():
    out = skills.create("learn how to convert miles", reply_with(CONVERTER))
    assert "approve mile converter" in out and "NOT installed" in out
    assert skills.active() == []
    assert "mile_converter" in skills.pending()
    assert "mile_converter" not in TOOLS


def test_approve_installs_hot_and_runs():
    skills.create("learn how to convert miles", reply_with(CONVERTER))
    assert "Installed" in skills.handle_command("Jarvis, approve mile converter")
    assert "mile_converter" in TOOLS
    assert run_tool("mile_converter", "10 miles") == "16.1 kilometres."
    assert skills.pending() == {}


def test_single_pending_can_be_approved_without_a_name():
    skills.create("x", reply_with(CONVERTER))
    assert "Installed" in skills.handle_command("yes, install it")


def test_offline_trigger_runs_skill():
    stage_and_approve()
    assert Jarvis().ask("convert 10 miles to km") == "16.1 kilometres."


def test_reject_discards():
    skills.create("x", reply_with(CONVERTER))
    assert "Discarded" in skills.handle_command("reject mile converter")
    assert skills.pending() == {} and skills.active() == []


def test_cancel_something_else_is_not_hijacked():
    skills.create("x", reply_with(CONVERTER))
    assert skills.handle_command("cancel the timer") is None
    assert "mile_converter" in skills.pending()  # still waiting


def test_nothing_pending_messages():
    assert "nothing waiting" in skills.handle_command("approve")
    assert skills.handle_command("install python") is None
    assert skills.handle_command("cancel") is None


def test_unsafe_code_is_never_staged():
    evil = CONVERTER.replace("import re", "import os\nimport re")
    out = skills.create("x", reply_with(evil))
    assert "couldn't write a safe version" in out
    assert skills.pending() == {}


def test_ai_gets_one_chance_to_repair():
    calls = []

    def flaky(system, prompt):
        calls.append(prompt)
        code = CONVERTER.replace("import re", "import os\nimport re") if len(calls) == 1 else CONVERTER
        return "```python\n" + code + "\n```"

    out = skills.create("x", flaky)
    assert "NOT installed yet" in out and len(calls) == 2
    assert "rejected" in calls[1] and "'os'" in calls[1]


def test_no_ai_key_message():
    out = skills.handle_command("learn how to trade", complete=None)
    assert "key" in out and skills.pending() == {}


def test_update_yourself_to_latest_is_not_a_skill_request():
    assert skills.handle_command("update yourself to the latest version", complete=reply_with(CONVERTER)) is None
    assert skills.handle_command("update yourself") is None


def test_show_list_remove():
    skills.create("x", reply_with(CONVERTER))
    assert skills.handle_command("show the code").startswith("[code]")
    skills.handle_command("approve")
    assert "mile converter" in skills.handle_command("list skills")
    assert "Removed" in skills.handle_command("remove skill mile converter")
    assert "mile_converter" not in TOOLS and skills.active() == []
    assert any((skills.SKILLS_DIR / "_removed").glob("mile_converter-*.py"))  # a copy is kept


def test_builtin_name_is_not_shadowed():
    code = CONVERTER.replace('"mile_converter"', '"get_time"')
    out = skills.create("x", reply_with(code))
    assert "get time skill" in out
    skills.handle_command("approve")
    assert "It is" in run_tool("get_time")  # built-in untouched


def test_pending_expires_after_a_day():
    skills.create("x", reply_with(CONVERTER))
    p = skills.pending()["mile_converter"]["path"]
    old = time.time() - 2 * 86400
    os.utime(p, (old, old))
    assert skills.pending() == {}


def test_hand_edited_unsafe_skill_is_ignored():
    stage_and_approve()
    path = skills.SKILLS_DIR / "mile_converter.py"
    path.write_text("import os\n" + path.read_text())
    assert skills.active() == []


def test_validator_blocks_escape_routes():
    base = CONVERTER
    bad = [
        base.replace("import re", "import urllib.request\nimport re") + "\nx = urllib.request.os\n",
        base.replace("import re", "import re\nimport subprocess"),
        base + "\nx = (1).__class__\n",
        base + "\ny = '{0.__class__}'.format(1)\n",
        base + "\neval('1')\n",
        base + "\nopen('f')\n",
        base.replace('r"convert (\\d+(?:\\.\\d+)?) miles"', 'r"(a+)+$"'),
    ]
    for code in bad:
        assert skills.validate(code), code[-60:]
    assert skills.validate(base) == []


def test_skill_process_has_no_api_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-secret-secret")
    monkeypatch.setenv("XAI_API_KEY", "xai-secret-secret-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    env = skills._safe_env()
    assert "ANTHROPIC_API_KEY" not in env and "XAI_API_KEY" not in env
    assert env.get("HTTPS_PROXY") == "http://proxy.example:3128"


def test_file_urls_are_blocked_at_runtime():
    code = '''import urllib.request
NAME = "peek"
DESCRIPTION = "Tries to read a local file."

def run(arg):
    try:
        return urllib.request.urlopen("file:///etc/passwd", timeout=5).read(60).decode("utf-8", "replace")
    except Exception as e:
        return "blocked: " + type(e).__name__
'''
    out = skills.create("x", reply_with(code))
    assert "NOT installed" in out  # static check can't know the URL...
    skills.handle_command("approve peek")
    result = run_tool("peek", "")
    assert result.startswith("blocked") and "root:" not in result  # ...but the runner refuses it


def test_slow_skill_is_stopped(monkeypatch):
    monkeypatch.setattr(skills, "RUN_TIMEOUT", 2)
    code = CONVERTER.replace("def run(arg):", "def run(arg):\n    import time as t\n    t.sleep(30)")
    skills.create("x", reply_with(code))
    skills.handle_command("approve")
    t0 = time.time()
    assert "too long" in run_tool("mile_converter", "1 miles")
    assert time.time() - t0 < 10
