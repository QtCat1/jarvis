# Jarvis

A small, extensible AI assistant for the command line. It runs **offline** with simple
commands, or becomes a full conversational assistant with **Claude** tool use when you
set an API key.

## Run

```bash
pip install -r requirements.txt
python -m jarvis                      # offline mode
ANTHROPIC_API_KEY=sk-... python -m jarvis   # Claude mode
```

## Movie mode: the HUD

```bash
python -m jarvis --hud
```

Open http://127.0.0.1:8765 in Chrome or Edge. You get an animated arc reactor that reacts
to what Jarvis is doing, a "Jarvis" wake word (press **Wake word**, then say "Jarvis, what's
the weather in London"), a mic button for free conversation, and spoken replies in a British
voice. Click once on the page so the browser allows audio.

It runs only on your own machine (localhost). Tools: weather, Wikipedia, jokes, status
report, timers, calculator, notes. With `ANTHROPIC_API_KEY` set, Claude handles open-ended
conversation and picks the tools itself.

## On your phone

```bash
python -m jarvis --hud --lan
```

The window prints a line like `http://192.168.1.20:8765/?pin=123456`. Open that exact link in
your phone's browser (phone on the same Wi-Fi). The PIN keeps others on your network out.
If Windows asks about the firewall, allow **Private networks**.

Voice note: phone browsers only allow the microphone on secure (https) pages, so on this link
Jarvis speaks to you and you talk using your keyboard's mic key or type. To add it to the home
screen, use the browser menu, then Add to Home screen.

## Updating

**Automatic:** Jarvis checks GitHub every time it starts (at most once an hour) and every few
hours while the HUD is open. When there's a new version it installs it and restarts itself,
only when you haven't spoken to it for two minutes. You can also say "update yourself".
Turn this off by creating an empty file called `.jarvis_no_autoupdate` in the Jarvis folder.

**Manual:**

Double-click **update.bat** (or run `python -m jarvis --update`). Jarvis downloads the newest
files from https://github.com/QtCat1/jarvis, keeps a backup of anything it replaces in
`_backup_before_update`, and never touches your notes.

- **Public repo:** works with no setup.
- **Private repo:** Jarvis needs a GitHub token. On GitHub open Settings, Developer settings,
  Personal access tokens, Fine-grained tokens, create one that can *read* this repository
  (Contents: Read-only), then save it as a one-line text file named `.jarvis_token` in the
  Jarvis folder (or set `JARVIS_GITHUB_TOKEN`).

## Memory (one week)

Jarvis remembers your conversations for 7 days and then forgets them automatically. They are
saved only on your computer, in `.jarvis_memory.jsonl` in your home folder, so updates never
touch them. API keys and GitHub tokens are blanked out before saving.

- Offline: ask "what did we talk about yesterday", "what did we say about the router", or
  "what did we talk about today".
- With `ANTHROPIC_API_KEY`: Claude is given the past week as background, so it can use it
  naturally in conversation.
- Say "forget everything" to erase it all, or delete the file.

## Shortcuts

- `start-jarvis.bat` opens the HUD, `start-jarvis-phone.bat` opens it for your phone.

## Voice mode (terminal)

```bash
pip install SpeechRecognition pyaudio pyttsx3
python -m jarvis --voice
```

Jarvis listens through your microphone and speaks replies. If the audio libraries or a
microphone are missing, it falls back to typing, so it never crashes.

Try: `what time is it`, `2*(3+4)**2`, `note: buy milk`, `show notes`, `system info`.

## Add your own tool

Write a function in `jarvis/tools.py` and register it in `TOOLS`:

```python
def coin_flip(_: str = "") -> str:
    import random
    return random.choice(["Heads", "Tails"])

TOOLS["coin_flip"] = (coin_flip, "Flip a coin. No input.")
```

In Claude mode it is picked up automatically.

## Test

```bash
pytest
```

## Layout

- `jarvis/tools.py` – tools (calculator, time, notes, system info)
- `jarvis/brain.py` – routing: Claude tool use or offline rules
- `jarvis/cli.py` – terminal interface

Set `JARVIS_MODEL` to change the Claude model.
