import pytest

from jarvis import keys, memory, skills


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Tests must never touch the real memory, keys or skills in the home folder."""
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "test_memory.jsonl")
    monkeypatch.setattr(keys, "KEYS_FILE", tmp_path / "test_keys.json")
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "test_skills")
    for k in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "JARVIS_PROVIDER", "XAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    skills.register()  # drop skills left registered by an earlier test
    yield
    skills.register()
