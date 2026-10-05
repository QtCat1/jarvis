import jarvis.tools as tools
from jarvis import Jarvis


def test_calculate():
    assert tools.calculate("2*(3+4)**2") == "98"
    assert tools.calculate("10/4") == "2.5"
    assert tools.calculate("1/0").startswith("Error")
    assert tools.calculate("__import__('os')").startswith("Error")


def test_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "NOTES_FILE", tmp_path / "notes.json")
    assert tools.list_notes() == "You have no notes."
    tools.add_note("buy milk")
    assert "buy milk" in tools.list_notes()
    tools.clear_notes()
    assert tools.list_notes() == "You have no notes."


def test_offline_routing(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tools, "NOTES_FILE", tmp_path / "notes.json")
    j = Jarvis()
    assert j.mode == "offline"
    assert j.ask("what time is it").startswith("It is")
    assert j.ask("2+2") == "4"
    assert "Saved" in j.ask("note: call mom")
    assert "call mom" in j.ask("show my notes")


def test_new_offline_routes(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tools, "NOTES_FILE", tmp_path / "notes.json")
    j = Jarvis()
    assert "nominal" in j.ask("Jarvis, status report")
    assert j.ask("tell me a joke") in tools._JOKES
    assert "At your service" in j.ask("hello")
