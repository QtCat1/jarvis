import pytest

from jarvis import memory


@pytest.fixture(autouse=True)
def _isolated_memory(tmp_path, monkeypatch):
    """Tests must never touch the real ~/.jarvis_memory.jsonl."""
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "test_memory.jsonl")
