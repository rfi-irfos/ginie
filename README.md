# USB Assistant — Ginie

A portable desktop pet + local AI assistant that runs fully offline from this USB stick.
No installation needed on the host machine (beyond Python dependencies).

## Quick start

Double-click or run from a terminal:

```bash
bash START_ASSISTANT.sh
```

Ginie appears as a walking character on your desktop. Right-click her to open the chat or trigger voice input.

## Requirements (must be installed on the host)

- Python 3.8+
- `pip install pillow vosk requests`
- `arecord` (ALSA utils, for voice — `sudo apt install alsa-utils`)

## What's on this stick

```
START_ASSISTANT.sh        launch script (path-agnostic, works from any mount point)
usb_assistant/
  assistent.py            main application
  frames/                 sprite animation frames
  models/
    vosk-model-small-de-0.15/   offline speech recognition model (German)
ollama_portable/
  ollama                  portable Ollama binary
  models/                 LLM weights (qwen2.5-coder:1.5b)
```

## How it works

1. On launch, Ginie checks if Ollama is already running on port 11434.
2. If not, it starts the portable Ollama binary from this stick, pointing it at the local `models/` folder.
3. Voice wake word: say "Hey Ginie" — the listener runs in the background using the bundled Vosk model.
4. File search scans the entire USB volume (not just the assistant folder).

## Troubleshooting

| Problem | Fix |
|---|---|
| "vosk not found" | `pip install vosk` |
| No mic input | Check `arecord -l` and ensure a capture device is visible |
| Ollama not responding | Run `bash ollama_portable/start_ollama.sh` manually to see errors |
| Blank sprite | Frames missing — `usb_assistant/frames/` must contain `frame_*.png` files |
