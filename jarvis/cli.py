"""Command-line interface: `python -m jarvis [--hud] [--lan] [--voice] [--update] [--setup]`

Running Jarvis starts a small supervisor that (1) checks GitHub for a newer version,
(2) starts the real Jarvis, and (3) restarts it automatically after an update.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .brain import Jarvis


def _supervise(argv: list) -> int:
    from .update import PROJECT_ROOT, RESTART_CODE, auto_check

    auto_check(log=print)  # quiet unless there's an update or a problem worth mentioning
    env = dict(os.environ, JARVIS_CHILD="1")
    while True:
        try:
            code = subprocess.call(
                [sys.executable, "-m", "jarvis"] + argv, env=env, cwd=str(PROJECT_ROOT)
            )
        except KeyboardInterrupt:
            return 0
        if code != RESTART_CODE:
            return code
        print("\nRestarting Jarvis with the new version...\n")


def _run(argv: list) -> None:
    if "--hud" in argv:
        from .server import serve

        serve(lan="--lan" in argv)
        return
    use_voice = "--voice" in argv
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


def main() -> None:
    argv = sys.argv[1:]
    if "--setup" in argv:
        from .keys import setup

        sys.exit(setup())
    if "--update" in argv:
        from .update import update

        sys.exit(update())
    if os.environ.get("JARVIS_CHILD") != "1":
        sys.exit(_supervise(argv))
    _run(argv)


if __name__ == "__main__":
    main()
