from jarvis.voice import Voice


def test_voice_degrades_without_hardware():
    v = Voice()  # no mic/speaker in CI: must not raise
    assert isinstance(v.can_listen, bool)
    assert isinstance(v.can_speak, bool)
    assert v.listen() is None or isinstance(v.listen(), str)
    v.speak("test")  # must be a safe no-op when no engine
    assert "mic=" in v.status()
