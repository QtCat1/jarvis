"""Optional voice I/O. Everything degrades gracefully if libraries are missing.

Speech in:  pip install SpeechRecognition pyaudio
Speech out: pip install pyttsx3
"""
from __future__ import annotations


class Voice:
    def __init__(self) -> None:
        self.recognizer = None
        self.mic_ok = False
        self.engine = None

        try:
            import speech_recognition as sr

            self.sr = sr
            self.recognizer = sr.Recognizer()
            sr.Microphone()  # raises if no mic / pyaudio
            self.mic_ok = True
        except Exception:
            self.mic_ok = False

        try:
            import pyttsx3

            self.engine = pyttsx3.init()
        except Exception:
            self.engine = None

    @property
    def can_listen(self) -> bool:
        return self.mic_ok

    @property
    def can_speak(self) -> bool:
        return self.engine is not None

    def listen(self) -> str | None:
        """Record one phrase and return text, or None if nothing understood."""
        if not self.mic_ok:
            return None
        with self.sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(source, timeout=6, phrase_time_limit=12)
                return self.recognizer.recognize_google(audio)
            except Exception:
                return None

    def speak(self, text: str) -> None:
        if self.engine:
            self.engine.say(text)
            self.engine.runAndWait()

    def status(self) -> str:
        return f"mic={'on' if self.can_listen else 'off'}, speaker={'on' if self.can_speak else 'off'}"
