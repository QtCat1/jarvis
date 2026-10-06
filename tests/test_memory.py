import time

from jarvis import Jarvis, memory
import jarvis.tools as tools

DAY = 86400


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "mem.jsonl")
    monkeypatch.setattr(tools, "NOTES_FILE", tmp_path / "notes.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_old_entries_are_dropped_after_a_week(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = time.time()
    memory.add("user", "eight days ago", now=now - 8 * DAY)
    memory.add("user", "two days ago", now=now - 2 * DAY)
    memory.add("user", "just now", now=now)
    texts = [e["text"] for e in memory.recent(now=now)]
    assert texts == ["two days ago", "just now"]
    assert "eight days ago" not in (tmp_path / "mem.jsonl").read_text()


def test_secrets_are_hidden(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    memory.add("user", "my key is sk-ant-abcdefghijklmnop1234 ok")
    memory.add("user", "token ghp_abcdefghijklmnopqrstuvwx")
    saved = (tmp_path / "mem.jsonl").read_text()
    assert "sk-ant" not in saved and "ghp_" not in saved and "[hidden]" in saved


def test_recall_yesterday_today_and_topic(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = time.time()
    memory.add("user", "buy a new router", now=now - 1 * DAY - 60)
    memory.add("user", "what is the weather in Lahore", now=now - 3600 * 0.1)
    assert "router" in memory.recall("what did we talk about yesterday", now=now)
    assert "Lahore" in memory.recall("what did we talk about today", now=now)
    assert "router" in memory.recall("what did we say about the router", now=now)
    assert "nothing saved" in memory.recall("what did we say about quantum", now=now).replace("anything", "nothing")


def test_conversation_flow_and_forget(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    j = Jarvis()
    j.ask("tell me a joke")
    j.ask("2+2")
    answer = j.ask("what did we talk about today")
    assert "joke" in answer and "2+2" in answer
    # memory questions are not saved as memories
    assert not any("what did we" in e["text"] for e in memory.recent())
    assert "forgotten" in j.ask("forget everything")
    assert memory.recent() == []
    assert "any conversations" in j.ask("what did we talk about")


def test_claude_context_block(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    memory.add("user", "I like green tea")
    memory.add("jarvis", "Noted, sir.")
    block = memory.context_block()
    assert "User: I like green tea" in block and "Jarvis: Noted, sir." in block


def test_damaged_line_does_not_lose_memory(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    memory.add("user", "keep me")
    with open(tmp_path / "mem.jsonl", "a") as f:
        f.write("{not json\n")
    assert [e["text"] for e in memory.recent()] == ["keep me"]
