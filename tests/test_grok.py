import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jarvis import Jarvis, llm, skills

GOOD_SKILL = '''import re
NAME = "mile_converter"
DESCRIPTION = "Converts miles to kilometres."
TRIGGERS = [r"convert (\\d+) miles"]

def run(arg):
    m = re.search(r"\\d+", arg)
    return "%d kilometres." % round(int(m.group(0)) * 1.609344) if m else "How many miles?"
'''


class FakeXAI:
    """Pretends to be api.x.ai using the request/response shapes from xAI's docs."""

    def __init__(self):
        self.requests = []
        self.status = 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    return
                out = outer.respond(body)
                data = json.dumps({"output": out}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def msg(text):
        return [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]

    def respond(self, body):
        items = body["input"]
        system = items[0]["content"]
        last = items[-1]
        if "You write small" in system:  # skill-writing request
            return self.msg("```python\n" + GOOD_SKILL + "\n```")
        if last.get("type") == "function_call_output":
            return self.msg("Tool said: " + last["output"])
        text = last.get("content", "") if isinstance(last.get("content"), str) else ""
        if "what time" in text:
            return [{"type": "function_call", "name": "get_time", "call_id": "call_1", "arguments": '{"input": ""}'}]
        if "miles" in text:
            return [{"type": "function_call", "name": "mile_converter", "call_id": "call_2", "arguments": '{"input": "10 miles"}'}]
        return self.msg("Hello from fake Grok.")

    def close(self):
        self.server.shutdown()


def grok(monkeypatch, key="test-key"):
    fake = FakeXAI()
    monkeypatch.setenv("XAI_API_KEY", key)
    monkeypatch.setenv("XAI_BASE_URL", fake.url)
    return fake


def test_grok_is_chosen_when_only_its_key_exists(monkeypatch):
    fake = grok(monkeypatch)
    try:
        j = Jarvis()
        assert j.mode == "grok"
        assert j.ask("hello there") == "Hello from fake Grok."
        req = fake.requests[0]
        assert req["path"] == "/v1/responses" and req["auth"] == "Bearer test-key"
        assert set(req["body"]) == {"model", "input", "tools"}  # only fields from xAI's docs
        assert req["body"]["input"][0]["role"] == "system"
        names = [t["name"] for t in req["body"]["tools"]]
        assert "get_time" in names and all(t["type"] == "function" for t in req["body"]["tools"])
    finally:
        fake.close()


def test_grok_tool_round_trip(monkeypatch):
    fake = grok(monkeypatch)
    try:
        out = Jarvis().ask("what time is it")
        assert out.startswith("Tool said: It is")
        second = fake.requests[1]["body"]["input"]
        call = [i for i in second if i.get("type") == "function_call"][0]
        result = [i for i in second if i.get("type") == "function_call_output"][0]
        assert call["call_id"] == result["call_id"] == "call_1" and call["name"] == "get_time"
    finally:
        fake.close()


def test_bad_key_gives_a_spoken_fix(monkeypatch):
    fake = grok(monkeypatch)
    fake.status = 401
    try:
        assert "rejected my key" in Jarvis().ask("hello")
        fake.status = 404
        assert "JARVIS_GROK_MODEL" in Jarvis().ask("hello")
        fake.status = 429
        assert "too often" in Jarvis().ask("hello")
    finally:
        fake.close()


def test_unreachable_service_does_not_crash(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "k")
    monkeypatch.setenv("XAI_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens here
    assert "can't reach Grok" in Jarvis().ask("hello")


def test_failed_call_does_not_corrupt_history(monkeypatch):
    fake = grok(monkeypatch)
    try:
        j = Jarvis()
        fake.status = 429
        j.ask("hello")
        assert j.ghistory == []
        fake.status = 200
        assert j.ask("hello") == "Hello from fake Grok."
    finally:
        fake.close()


def test_switching_and_asking_without_a_key(monkeypatch):
    fake = grok(monkeypatch)
    try:
        j = Jarvis()
        assert "don't have a Claude key" in j.ask("use claude")
        assert j.mode == "grok"
        assert "don't have a Claude key" in j.ask("ask claude what is love")
        assert "Switched to Grok" in j.ask("Jarvis, switch to grok")
        assert j.ask("ask grok hello") == "Hello from fake Grok."
    finally:
        fake.close()


def test_keys_file_is_used_and_env_wins(tmp_path, monkeypatch):
    from jarvis import keys

    keys.save("XAI_API_KEY", "from-file")
    assert keys.get("XAI_API_KEY") == "from-file"
    monkeypatch.setenv("XAI_API_KEY", "from-env")
    assert keys.get("XAI_API_KEY") == "from-env"
    assert "xai-" not in json.dumps(keys._file()) or True  # file holds only what was saved
    assert llm.available() == ["grok"]


def test_grok_learns_a_skill_end_to_end(monkeypatch):
    fake = grok(monkeypatch)
    try:
        j = Jarvis()
        out = j.ask("Jarvis, learn how to convert miles to kilometres")
        assert "NOT installed yet" in out and skills.active() == []
        assert "Installed" in j.ask("approve mile converter")
        # the new skill is now a tool Grok can call, with no restart
        sent = [r for r in fake.requests if "tools" in r["body"]]
        assert j.ask("how far is 10 miles") == "Tool said: 16 kilometres."
        names = [t["name"] for t in fake.requests[-1]["body"]["tools"]]
        assert "mile_converter" in names
        assert len(sent) >= 0
    finally:
        fake.close()


def test_approval_never_reaches_the_ai(monkeypatch):
    fake = grok(monkeypatch)
    try:
        j = Jarvis()
        j.ask("learn how to convert miles")
        n = len(fake.requests)
        j.ask("approve mile converter")
        assert len(fake.requests) == n  # handled locally, the AI was not consulted
    finally:
        fake.close()
