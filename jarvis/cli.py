"""Command-line interface: `python -m jarvis [--voice]`"""
from __future__ import annotations

import sys

from .brain import Jarvis


def main() -> None:
    if "--update" in sys.argv:
        from .update import update

        sys.exit(update())
    if "--hud" in sys.argv:
        from .server import serve

        serve(lan="--lan" in sys.argv)
        return
    use_voice = "--voice" in sys.argv
    jarvis = Jarvis()
    voice = None
    if use_voice:
        from .voice import Voice

        voice = Voice()
        print(f"Voice mode: {voice.status()}")
        if not voice.can_listen:
            print("No microphone available, so you can type instead.")

    print(f"Jarvis online ({jarvis.mode} mode). Type 'exit' to quit.")
    interactive = sys.stdin.isatty()

    while True:
        try:
            if voice and voice.can_listen:
                print("listening...")
                line = voice.listen()
                if line is None:
                    continue
                print(f"you> {line}")
            else:
                line = input("you> ") if interactive else sys.stdin.readline()
                if not line:
                    break
                if not interactive:
                    print(f"you> {line.strip()}")
        except (EOFError, KeyboardInterrupt):
            break

        line = line.strip()
        if not line:
            continue
        if line.lower() in {"exit", "quit", "bye", "goodbye"}:
            print("jarvis> Goodbye!")
            if voice:
                voice.speak("Goodbye!")
            break

        reply = jarvis.ask(line)
        print(f"jarvis> {reply}")
        if voice:
            voice.speak(reply)


if __name__ == "__main__":
    main()
