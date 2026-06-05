# Ginie

**GitHub:** https://github.com/rfi-irfos/ginie

An offline AI assistant that lives on a USB stick and fits on your keychain.

Plug into any Linux machine. No internet. No account. No cloud. Just Ginie.

Airplane mode? Hotel with no wifi? Dead zone in the mountains? Power outage?
Ginie does not care. She runs entirely from the stick, brings her own AI model,
and is ready to chat, search your files, and help you think — anywhere.

```
plug in usb  ->  bash START_ASSISTANT.sh  ->  working AI agent
```

---

## Run from your machine (no USB needed)

If you just want to build and run Ginie directly on your Linux machine:

```bash
# 1. install system deps (Ubuntu/Debian)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
pip install pillow

# 2. clone
git clone https://github.com/rfi-irfos/ginie ~/ginie
cd ~/ginie

# 3. generate sprites
python3 gen_sprites.py

# 4. wire the genie command (one time)
mkdir -p ~/.local/bin
echo '#!/usr/bin/env bash' > ~/.local/bin/ginie
echo 'exec python3 '"$HOME"'/ginie/Ginie.py "$@"' >> ~/.local/bin/ginie
chmod +x ~/.local/bin/ginie

# make sure ~/.local/bin is in PATH (add to ~/.bashrc if missing)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 5. launch
ginie
```

After step 4, open any new terminal and just type `ginie`.

> Ollama + model weights are optional for the desktop pet — the sprite, animations,
> and right-click menu all work without them. Chat will show "offline" until Ollama
> is running (see USB setup below).

## What it is

- Desktop pet that lives on your screen — floats, walks, poofs, zooms in and out in 3D
- Materialises from a tiny speck on launch, then drifts around your desktop
- Right-click for actions: chat, teleport, walk, float, sleep, quit
- Fully streaming chat with markdown rendering (needs Ollama + model)
- Voice input (German by default, configurable)
- USB mode: brings its own Ollama binary and LLM weights — nothing installed on the host

## USB quick start

Plug in the USB stick, open a terminal there, and run:

```bash
bash START_ASSISTANT.sh
```

That is it. Ginie appears on your desktop.

## One-time USB host setup (optional)

Run this once on a machine you use regularly to get the `ginie` command from USB:

```bash
bash setup_autostart.sh
```

After that, any terminal on that machine: type `ginie`, hit enter.

## Requirements on the host machine

The only things that must already be installed:

- Python 3.8+
- `python3-gi` and `python3-gi-cairo` (GTK3 bindings — pre-installed on Ubuntu/Debian)
- `pip install pillow` (image handling)

For voice input (optional):
- `pip install vosk`
- `sudo apt install alsa-utils` (for `arecord`)

Everything else — the AI model, the Ollama runtime, the sprite frames — lives on the stick.

## What is on the stick

```
Ginie.py                    main application (desktop pet + chat)
START_ASSISTANT.sh          launch script, path-agnostic from any mount point
setup_autostart.sh          one-time setup to get the `ginie` terminal command
gen_sprites.py              regenerate sprite frames if needed

usb_assistant/
  assistent.py              legacy browser-based interface (fallback / alternative)
  frames/                   sprite animation frames (float, walk, poof, ghost)
  models/
    vosk-model-small-de-0.15/   offline speech recognition model

ollama_portable/
  ollama                    portable Ollama binary (copy to /tmp on launch, FAT32-safe)
  models/                   LLM weights — qwen3:0.6b by default
  start_ollama.sh           manual start script for debugging
```

The model weights and Ollama binary are NOT in this git repo (too large).
See setup instructions below for how to populate them onto a fresh stick.

## Populating a fresh USB stick

```bash
# 1. clone this repo onto the stick
git clone https://github.com/rfi-irfos/ginie /media/yourname/GINIE

# 2. download the Ollama binary
curl -L https://ollama.com/download/ollama-linux-amd64 \
     -o /media/yourname/GINIE/ollama_portable/ollama
chmod +x /media/yourname/GINIE/ollama_portable/ollama

# 3. pull the model onto the stick
OLLAMA_MODELS=/media/yourname/GINIE/ollama_portable/models \
  /media/yourname/GINIE/ollama_portable/ollama pull qwen3:0.6b

# 4. done — eject and carry
```

Total size on stick: roughly 1.2 GB (fits on any 2 GB+ USB drive).

## How it works

1. `START_ASSISTANT.sh` finds its own location regardless of mount point.
2. Ginie copies the portable Ollama binary to `/tmp` (FAT32 has no execute bit).
3. Ollama starts on port 11435 (separate from any system Ollama on 11434).
4. The model prewarmed into the KV cache — first response is fast.
5. The GTK3 pet window appears. Everything from here runs offline.

## Changing the model

Edit the `MODEL` line near the top of `Ginie.py`:

```python
MODEL = "qwen3:0.6b"   # change to any model you have pulled onto the stick
```

Smaller models (0.6b) respond in ~1 second on most hardware.
Larger models (3b, 7b) need a bigger stick and more patience.

## Troubleshooting

| Problem | Fix |
|---|---|
| Blank screen / no sprite | `python3 gen_sprites.py` to regenerate frames |
| "vosk not found" | `pip install vosk` |
| No mic input | `arecord -l` to check capture devices |
| Ollama not responding | `bash ollama_portable/start_ollama.sh` to see errors |
| ETXTBSY error on binary | Previous Ginie still running — `pkill -f ginie_ollama_bin` |
| Model not found (404) | System Ollama grabbed port 11435 — `pkill ollama`, relaunch |

## The idea

Most AI tools require a subscription, an internet connection, and a company
that can read your conversations. Ginie requires a USB port.

Carry her on your keychain. Use her on a plane, in a server room with no wifi,
on a borrowed laptop in a foreign country, on a machine that has never seen
the internet. The model runs locally, the data stays on your stick, and when
you pull it out nothing is left behind on the host.

---

Built by Zabih and Simeon at RFI-IRFOS.
