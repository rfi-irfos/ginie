#!/usr/bin/env python3
"""
Ginie — offline USB desktop pet + AI assistant
deps: python3-gi python3-gi-cairo pillow  (all pre-installed on Ubuntu)
run:  python3 Ginie.py
"""
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import cairo

import os, sys, json, threading, subprocess, time, random, glob, io, re, shutil
import urllib.request, urllib.error

try:
    from PIL import Image
except ImportError:
    print("pip install pillow")
    sys.exit(1)

HERE       = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(HERE, "usb_assistant", "frames")
GINIE_PORT = 11435
OLLAMA_URL = f"http://127.0.0.1:{GINIE_PORT}"
MODEL      = "qwen3:0.6b"
_GINIE_PID_FILE  = "/tmp/ginie_ollama.pid"
_GINIE_APP_LOCK  = "/tmp/ginie_app.lock"

_SYSTEM_PROMPT = (
    "You are Ginie, an offline AI assistant on a USB stick. "
    "Your name is Ginie. "
    "Answer questions directly and factually. "
    "Reply in the same language the user writes in. "
    "Keep answers short and accurate."
)

# ---------------------------------------------------------------------------
# Single-instance enforcement
# ---------------------------------------------------------------------------

def _check_single_instance():
    # O_CREAT|O_EXCL is atomic — exactly one process wins even under a race
    try:
        fd = os.open(_GINIE_APP_LOCK,
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # lock exists — check if owning process is still alive
        try:
            with open(_GINIE_APP_LOCK) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"Ginie already running (pid {pid}). Exiting.")
            subprocess.run(["wmctrl", "-a", "Ginie"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=1)
            sys.exit(0)
        except (OSError, ProcessLookupError, ValueError, FileNotFoundError):
            # stale lock — take it over atomically
            with open(_GINIE_APP_LOCK, "w") as f:
                f.write(str(os.getpid()))
    import atexit
    atexit.register(_release_lock)

def _release_lock():
    try:
        os.unlink(_GINIE_APP_LOCK)
    except Exception:
        pass

def virtual_desktop_size():
    """Full virtual-desktop extent across all monitors (non-deprecated).
    Replaces Gdk.Screen.get_width/height, which only report the union via a
    deprecated API. Falls back to Screen if monitor enumeration fails."""
    try:
        display = Gdk.Display.get_default()
        n = display.get_n_monitors()
        if n > 0:
            right = bottom = 0
            for i in range(n):
                g = display.get_monitor(i).get_geometry()
                right  = max(right,  g.x + g.width)
                bottom = max(bottom, g.y + g.height)
            if right and bottom:
                return right, bottom
    except Exception:
        pass
    s = Gdk.Screen.get_default()
    return s.get_width(), s.get_height()

# ---------------------------------------------------------------------------
# CSS dark theme
# ---------------------------------------------------------------------------
CSS = b"""
window.chat-win {
    background-color: #0f0f11;
}
.header {
    background-color: #18181c;
    border-bottom: 1px solid #2a2a32;
    padding: 10px 16px;
}
.header-title { color: #e8e8f0; font-size: 13px; font-weight: bold; }
.status-online  { color: #4caf82; font-size: 11px; }
.status-offline { color: #e05c5c; font-size: 11px; }
.chat-log {
    background-color: #0f0f11;
    color: #e8e8f0;
    font-size: 12px;
    padding: 10px;
}
.input-bar {
    background-color: #18181c;
    border-top: 1px solid #2a2a32;
    padding: 8px 12px;
}
.msg-entry {
    background-color: #2a2a32;
    color: #e8e8f0;
    border: 1px solid #3a3a48;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
}
.msg-entry:focus { border-color: #6c8ef5; }
.send-btn {
    background-color: #6c8ef5;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 12px;
}
.send-btn:hover { background-color: #5a7de4; }
.new-btn {
    background-color: #2a2a32;
    color: #9090a8;
    border: 1px solid #3a3a48;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 11px;
}
.new-btn:hover { color: #e8e8f0; }
.bubble-win {
    background-color: #1e1e2e;
    border-radius: 10px;
    padding: 2px;
}
.bubble-text {
    color: #e8e8f0;
    font-size: 11px;
    padding: 8px 12px;
}
"""

def apply_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

# ---------------------------------------------------------------------------
# Ollama bootstrap
# ---------------------------------------------------------------------------

_startup_status = "starting model..."

def _set_startup_status(msg):
    global _startup_status
    _startup_status = msg
    print(f"[ginie] {msg}")

def _model_available():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            tags = json.loads(r.read())
            return any(m.get("name","").startswith(MODEL.split(":")[0])
                       for m in tags.get("models", []))
    except Exception:
        return False

def _usb_has_model(usb_models, model):
    """True if the portable store actually carries this model's manifest."""
    name, _, tag = model.partition(":")
    tag = tag or "latest"
    manifest = os.path.join(usb_models, "manifests", "registry.ollama.ai",
                            "library", name, tag)
    return os.path.isfile(manifest)

def _model_size_hint(name):
    """Rough param-size from a model name ('qwen3:0.6b' -> 0.6); smaller = faster."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*b', name.lower())
    return float(m.group(1)) if m else 99.0

def _resolve_model():
    """Keep the configured MODEL if the active ollama has it. Only substitute
    when it's genuinely absent, and then prefer the smallest sensible model
    (never silently upgrade to a big coder model)."""
    global MODEL
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            tags = json.loads(r.read())
            names = [m["name"] for m in tags.get("models", []) if m.get("name")]
    except Exception:
        return
    if not names:
        return
    want = MODEL
    # 1. exact match — lock it in (this is the happy path for qwen3:0.6b)
    if want in names:
        MODEL = want
        return
    # 2. same family, e.g. another qwen3 tag
    fam = want.split(":")[0]
    fam_hits = [n for n in names if n.split(":")[0] == fam]
    if fam_hits:
        MODEL = fam_hits[0]
        return
    # 3. genuinely absent — prefer a 0.6b, then any qwen3, else the smallest
    pref = ([n for n in names if "0.6b" in n]
            or [n for n in names if n.startswith("qwen3")]
            or sorted(names, key=_model_size_hint))
    MODEL = pref[0]
    print(f"[ginie] '{want}' not installed; falling back to {MODEL}")

def _kill_ginie_ollama():
    """Kill our ollama instance via PID file, then also by binary path."""
    try:
        with open(_GINIE_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 9)
        print(f"killed previous ginie ollama (pid {pid})")
    except Exception:
        pass
    try:
        os.remove(_GINIE_PID_FILE)
    except Exception:
        pass
    # also kill any process still holding the binary (handles stale PID files)
    try:
        subprocess.run(["pkill", "-9", "-f", "ginie_ollama_bin"],
                       capture_output=True)
    except Exception:
        pass
    # wait for port to free
    for _ in range(8):
        try:
            urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=0.4)
            time.sleep(0.5)
        except Exception:
            break

def _start_portable():
    usb_models = os.path.normpath(os.path.join(HERE, "ollama_portable", "models"))
    if not os.path.isdir(usb_models):
        return False

    # only use the portable instance if it actually carries the model we want;
    # otherwise fall through to system ollama, which may already have it.
    if not _usb_has_model(usb_models, MODEL):
        print(f"[ginie] portable store lacks {MODEL}; using system ollama instead")
        return False

    import shutil, stat

    # always use the bundled ollama binary — self-contained, no system install needed
    usb_bin = os.path.normpath(os.path.join(HERE, "ollama_portable", "ollama"))
    if not os.path.exists(usb_bin):
        # last resort: system ollama with USB models
        binary = shutil.which("ollama")
        if not binary:
            return False
    else:
        # copy to /tmp — FAT32 has no execute bit
        binary = "/tmp/ginie_ollama_bin"
        try:
            shutil.copy2(usb_bin, binary)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        except OSError as e:
            if e.errno == 26:  # ETXTBSY — binary already running from previous launch
                _set_startup_status("ollama already running, checking port...")
                # just use what's already there
            else:
                _set_startup_status(f"copy failed: {e}")
                return False

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = usb_models
    env["OLLAMA_HOST"]   = f"127.0.0.1:{GINIE_PORT}"
    print(f"starting ollama ({binary}) on port {GINIE_PORT} ...")
    _OLLAMA_LOG = "/tmp/ginie_ol.log"
    try:
        log_f = open(_OLLAMA_LOG, "w")
        proc  = subprocess.Popen([binary, "serve"], env=env,
                                 stdout=log_f, stderr=log_f)
    except OSError as e:
        print(f"ollama binary failed to exec: {e}")
        _set_startup_status(f"model error: {e}")
        return False

    try:
        with open(_GINIE_PID_FILE, "w") as f:
            f.write(str(proc.pid))
    except Exception:
        pass

    # wait up to 20s; bail early if process already died
    for i in range(40):
        time.sleep(0.5)
        if proc.poll() is not None:
            _set_startup_status("USB binary incompatible — trying system ollama...")
            # fall through: let ensure_ollama try system ollama with USB models
            return False
        if _model_available():
            _set_startup_status("model ready")
            return True
        if i == 10:
            _set_startup_status("loading model from USB...")
    _set_startup_status("model alive, still indexing")
    return True

def ensure_ollama():
    _kill_ginie_ollama()

    if _start_portable():
        print("portable ollama from USB started.")
        _prewarm_model()
        return

    # fallback: system ollama — start it pointing at USB models if available
    _set_startup_status("using system ollama...")
    global OLLAMA_URL
    OLLAMA_URL = "http://127.0.0.1:11434"

    sys_bin = shutil.which("ollama")
    if not sys_bin:
        _set_startup_status("ollama not installed — run setup_autostart.sh first")
        return

    already_up = False
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1)
        already_up = True
    except Exception:
        pass

    if not already_up:
        usb_models = os.path.normpath(os.path.join(HERE, "ollama_portable", "models"))
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        # only point the system daemon at the USB store if it has the wanted
        # model — otherwise let it use its own store (which may have qwen3:0.6b).
        if os.path.isdir(usb_models) and _usb_has_model(usb_models, MODEL):
            env["OLLAMA_MODELS"] = usb_models
            _set_startup_status("starting system ollama with USB models...")
        else:
            _set_startup_status("starting system ollama...")
        proc = subprocess.Popen([sys_bin, "serve"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with open(_GINIE_PID_FILE, "w") as f:
                f.write(str(proc.pid))
        except Exception:
            pass
        for _ in range(24):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=0.5)
                break
            except Exception:
                pass

    _resolve_model()
    _set_startup_status(f"model ready: {MODEL}")
    _prewarm_model()

_INFERENCE_OPTIONS = {
    "num_ctx":        2048,
    "num_gpu":        99,
    "temperature":    0.72,
    "top_p":          0.90,
    "repeat_penalty": 1.1,
}

def _prewarm_model():
    """Warm the KV cache with the same endpoint and options used for real calls."""
    try:
        payload = {
            "model":   MODEL,
            "messages": [
                {"role": "system",    "content": _SYSTEM_PROMPT},
                {"role": "user",      "content": "hey"},
                {"role": "assistant", "content": "hey, what's on your mind?"},
            ],
            "stream":  False,
            "think":   False,
            "options": _INFERENCE_OPTIONS,
        }
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        print("model prewarmed.")
    except Exception as e:
        print(f"prewarm skipped: {e}")

def ollama_stream(prompt, history=None, think=False):
    """Generator: yields ('think', token) or ('response', token) tuples.
    Uses /api/chat for system prompt + multi-turn history.
    Sparse-skip: empty/whitespace-only tokens dropped to reduce UI overhead.
    """
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-6:])    # last 3 turns — 0.6b can't handle more
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model":   MODEL,
        "messages": messages,
        "stream":  True,
        "think":   think,
        "options": _INFERENCE_OPTIONS,
    }
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw in r:
                line = raw.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg       = chunk.get("message", {})
                think_tok = msg.get("thinking", "")
                resp_tok  = msg.get("content", "")
                # sparse-skip: drop purely whitespace tokens
                if think_tok and think_tok.strip():
                    yield ("think", think_tok)
                if resp_tok and (resp_tok.strip() or resp_tok == "\n"):
                    yield ("response", resp_tok)
                if chunk.get("done"):
                    break
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _resolve_model()
            # retry once with whatever model is now set
            payload["model"] = MODEL
            body2 = json.dumps(payload).encode()
            req2  = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=body2, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req2, timeout=120) as r2:
                    for raw in r2:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg       = chunk.get("message", {})
                        think_tok = msg.get("thinking", "")
                        resp_tok  = msg.get("content", "")
                        if think_tok and think_tok.strip():
                            yield ("think", think_tok)
                        if resp_tok and (resp_tok.strip() or resp_tok == "\n"):
                            yield ("response", resp_tok)
                        if chunk.get("done"):
                            break
            except Exception as e2:
                yield ("response", f"no model available. run: ollama pull qwen3:0.6b\n({e2})")
        else:
            yield ("response", f"ollama error {e.code}")
    except Exception as e:
        yield ("response", f"offline — {_startup_status}\n(log: /tmp/ginie_ol.log)")

# ---------------------------------------------------------------------------
# Frame loader
# ---------------------------------------------------------------------------

SPR_W, SPR_H = 240, 320   # native sprite resolution (2x render → crisp at zoom)

def _to_pixbuf(img, flip=False, tilt=0):
    img = img.convert("RGBA")
    img = img.resize((SPR_W, SPR_H), Image.Resampling.LANCZOS)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if tilt:
        img = img.rotate(tilt, expand=False, fillcolor=(0, 0, 0, 0))
    raw = img.tobytes()
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(raw),
        GdkPixbuf.Colorspace.RGB, True, 8, SPR_W, SPR_H, SPR_W * 4
    )

def load_set(prefix, flip=False, tilt=0):
    """Load all frames matching frames/<prefix>_NN.png in sorted order."""
    paths = sorted(glob.glob(os.path.join(FRAMES_DIR, f"{prefix}_*.png")))
    frames = []
    for p in paths:
        try:
            frames.append(_to_pixbuf(Image.open(p), flip=flip, tilt=tilt))
        except Exception as e:
            print(f"frame load error {p}: {e}")
    return frames

# ---------------------------------------------------------------------------
# Chat window
# ---------------------------------------------------------------------------

class ChatWindow(Gtk.Window):
    def __init__(self, pet):
        super().__init__(title="Ginie")
        self.pet = pet
        self.get_style_context().add_class("chat-win")
        self.set_default_size(420, 560)
        self.set_keep_above(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", lambda w, e: w.hide() or True)

        self._sessions    = []
        self._responding  = False
        self._think_mode  = False
        self._status_mark = None
        self._line_mark   = None    # tracks start of current streamed line for md
        self._chat_history = []     # [{role, content}, ...] passed to ollama

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        # header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.get_style_context().add_class("header")
        title = Gtk.Label(label="Ginie")
        title.get_style_context().add_class("header-title")
        title.set_xalign(0)
        hdr.pack_start(title, True, True, 0)

        # thinking toggle
        self.think_btn = Gtk.ToggleButton(label="Denken: aus")
        self.think_btn.get_style_context().add_class("new-btn")
        self.think_btn.set_tooltip_text(
            "aus = schnelle Antworten (~1s)\n"
            "ein = tiefes Nachdenken (~5s), gut fuer komplexe Aufgaben"
        )
        self.think_btn.connect("toggled", self._on_think_toggled)
        hdr.pack_end(self.think_btn, False, False, 0)

        self.status_lbl = Gtk.Label(label="...")
        self.status_lbl.get_style_context().add_class("status-offline")
        hdr.pack_end(self.status_lbl, False, False, 4)
        vbox.pack_start(hdr, False, False, 0)

        # chat log
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.get_style_context().add_class("chat-log")
        self.textview.set_left_margin(12)
        self.textview.set_right_margin(12)
        self.textview.set_top_margin(8)
        self.buf = self.textview.get_buffer()
        self.tag_user    = self.buf.create_tag("user",    foreground="#6c8ef5")
        self.tag_ginie   = self.buf.create_tag("ginie",   foreground="#e8e8f0")
        self.tag_sys     = self.buf.create_tag("sys",     foreground="#6c6c8a", size_points=9)
        self.tag_thought = self.buf.create_tag("thought", foreground="#5a5a72",
                                               style=1, size_points=9)
        # markdown inline tags (applied retroactively on newline)
        self.buf.create_tag("md_bold",   foreground="#e8e8f0", weight=700)
        self.buf.create_tag("md_italic", foreground="#c8c8e0", style=2)
        self.buf.create_tag("md_code",   foreground="#88d8b0", family="monospace",
                            background="#1e1e2e")
        self.buf.create_tag("md_h1",     foreground="#6c8ef5", weight=700, size_points=14)
        self.buf.create_tag("md_h2",     foreground="#6c8ef5", weight=700, size_points=12)
        self.buf.create_tag("md_h3",     foreground="#8ca8f5", weight=700)
        self.buf.create_tag("md_bullet", foreground="#6c8ef5")
        self.buf.create_tag("md_num",    foreground="#6c8ef5")
        scroll.add(self.textview)
        vbox.pack_start(scroll, True, True, 0)
        self._scroll = scroll

        # toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(12); toolbar.set_margin_end(12)
        toolbar.set_margin_top(6);   toolbar.set_margin_bottom(2)
        new_btn = Gtk.Button(label="Neuer Chat")
        new_btn.get_style_context().add_class("new-btn")
        new_btn.connect("clicked", self._new_chat)
        toolbar.pack_start(new_btn, False, False, 0)
        self.session_lbl = Gtk.Label(label="")
        self.session_lbl.get_style_context().add_class("status-offline")
        self.session_lbl.set_xalign(1)
        toolbar.pack_end(self.session_lbl, True, True, 0)
        vbox.pack_start(toolbar, False, False, 0)

        # input bar
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("input-bar")
        self.entry = Gtk.Entry()
        self.entry.get_style_context().add_class("msg-entry")
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("Schreib Ginie was...")
        self.entry.connect("activate", self._send)
        bar.pack_start(self.entry, True, True, 0)
        send_btn = Gtk.Button(label="Senden")
        send_btn.get_style_context().add_class("send-btn")
        send_btn.connect("clicked", self._send)
        bar.pack_start(send_btn, False, False, 0)
        vbox.pack_start(bar, False, False, 0)

        self._append("sys", "Ginie. offline, ready.\n")
        self._check_status()

    def _on_think_toggled(self, btn):
        self._think_mode = btn.get_active()
        btn.set_label("Denken: ein" if self._think_mode else "Denken: aus")

    def _append(self, tag, text):
        end = self.buf.get_end_iter()
        self.buf.insert_with_tags_by_name(end, text, tag)
        # auto-scroll
        GLib.idle_add(self._scroll_bottom)

    def _scroll_bottom(self):
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _send(self, *_):
        if self._responding:
            return
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        self._append("user", f"Du: {text}\n")
        status = "Ginie denkt nach..." if self._think_mode else "Ginie antwortet..."
        # plant a mark at the start of the status line so we can erase it precisely
        self._status_mark = self.buf.create_mark(
            None, self.buf.get_end_iter(), left_gravity=True
        )
        self._append("sys", f"{status}\n")
        self._responding = True
        threading.Thread(
            target=self._respond_stream,
            args=(text, self._think_mode, list(self._chat_history)),
            daemon=True
        ).start()

    def _erase_status(self):
        if self._status_mark and not self._status_mark.get_deleted():
            it = self.buf.get_iter_at_mark(self._status_mark)
            self.buf.delete(it, self.buf.get_end_iter())
            self.buf.delete_mark(self._status_mark)
        self._status_mark = None
        return False

    # ── markdown line formatter ──────────────────────────────────────────────

    def _md_begin_line(self):
        """Plant a mark at the start of the current line being streamed."""
        if self._line_mark and not self._line_mark.get_deleted():
            self.buf.delete_mark(self._line_mark)
        self._line_mark = self.buf.create_mark(
            None, self.buf.get_end_iter(), left_gravity=True
        )

    def _md_end_line(self):
        """Retroactively apply markdown tags to the completed line."""
        if not self._line_mark or self._line_mark.get_deleted():
            return
        s_it  = self.buf.get_iter_at_mark(self._line_mark)
        e_it  = self.buf.get_end_iter()
        text  = self.buf.get_text(s_it, e_it, False)
        if not text:
            self.buf.delete_mark(self._line_mark)
            self._line_mark = None
            return

        def at(offset):
            it = s_it.copy(); it.forward_chars(offset); return it

        # block: headers
        hm = re.match(r'^(#{1,3})\s+', text)
        if hm:
            tag = f"md_h{min(len(hm.group(1)), 3)}"
            self.buf.apply_tag_by_name(tag, s_it, e_it)
        # block: bullet list marker
        elif re.match(r'^\s*[-*]\s+', text):
            m = re.match(r'^(\s*[-*]\s+)', text)
            if m:
                self.buf.apply_tag_by_name("md_bullet", s_it, at(len(m.group(1))))
        # block: numbered list marker
        elif re.match(r'^\s*\d+\.\s+', text):
            m = re.match(r'^(\s*\d+\.\s+)', text)
            if m:
                self.buf.apply_tag_by_name("md_num", s_it, at(len(m.group(1))))

        # inline: **bold**
        for m in re.finditer(r'\*\*(.+?)\*\*', text):
            self.buf.apply_tag_by_name("md_bold", at(m.start()), at(m.end()))

        # inline: *italic* (not **)
        for m in re.finditer(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', text):
            self.buf.apply_tag_by_name("md_italic", at(m.start()), at(m.end()))

        # inline: `code`
        for m in re.finditer(r'`([^`\n]+)`', text):
            self.buf.apply_tag_by_name("md_code", at(m.start()), at(m.end()))

        self.buf.delete_mark(self._line_mark)
        self._line_mark = None

    # ── streaming response ───────────────────────────────────────────────────

    def _update_history(self, user_text, reply_text):
        self._chat_history.append({"role": "user",      "content": user_text})
        self._chat_history.append({"role": "assistant", "content": reply_text})

    def _respond_stream(self, prompt, think, history):
        started      = False
        in_think     = False
        reply_chunks = []

        for kind, tok in ollama_stream(prompt, history=history, think=think):
            if not started:
                started  = True
                in_think = (kind == "think")
                GLib.idle_add(self._erase_status)
                if in_think:
                    GLib.idle_add(self._append, "thought", "  [ ")
                else:
                    GLib.idle_add(self._append, "ginie", "Ginie: ")
                    GLib.idle_add(self._md_begin_line)

            if kind == "think":
                GLib.idle_add(self._append, "thought", tok)
            else:
                if in_think:
                    in_think = False
                    GLib.idle_add(self._append, "thought", " ]\n")
                    GLib.idle_add(self._append, "ginie", "Ginie: ")
                    GLib.idle_add(self._md_begin_line)
                reply_chunks.append(tok)
                # stream token; on newline flush markdown for completed line
                if "\n" in tok:
                    parts = tok.split("\n")
                    for i, part in enumerate(parts):
                        if part:
                            GLib.idle_add(self._append, "ginie", part)
                        if i < len(parts) - 1:
                            GLib.idle_add(self._md_end_line)
                            GLib.idle_add(self._append, "ginie", "\n")
                            GLib.idle_add(self._md_begin_line)
                else:
                    GLib.idle_add(self._append, "ginie", tok)

        full_reply = "".join(reply_chunks).strip()
        if full_reply:
            GLib.idle_add(self._update_history, prompt, full_reply)

        def _done(was_think=in_think, had_output=started):
            if was_think:
                self._append("thought", " ]\n")
            if not had_output:
                self._erase_status()
                self._append("sys", "Keine Antwort.\n")
            else:
                self._md_end_line()
                self._append("ginie", "\n\n")
            self._responding = False
        GLib.idle_add(_done)

    def _new_chat(self, *_):
        # snapshot current session
        start, end = self.buf.get_bounds()
        text = self.buf.get_text(start, end, False).strip()
        if text:
            self._sessions.append(text)
            self.session_lbl.set_text(f"Chat {len(self._sessions)} gespeichert")
        self.buf.set_text("")
        self._chat_history.clear()
        self._append("sys", "new chat.\n")

    def _check_status(self):
        def _poll():
            try:
                urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1)
                online = True
            except Exception:
                online = False
            GLib.idle_add(self._set_status, online)
        threading.Thread(target=_poll, daemon=True).start()
        GLib.timeout_add(5000, self._check_status)
        return False

    def _set_status(self, online):
        self.status_lbl.set_text("online" if online else "offline")
        ctx = self.status_lbl.get_style_context()
        if online:
            ctx.remove_class("status-offline")
            ctx.add_class("status-online")
        else:
            ctx.remove_class("status-online")
            ctx.add_class("status-offline")
        return False

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

FLOATING   = "floating"   # hovering drift — default mode
HOVERING   = "hovering"   # bob in place, no translation
WALKING    = "walking"    # legs out, walking along screen bottom area
CROSSING   = "crossing"   # target-directed walk across monitors
EXPLORING  = "exploring"  # goal-directed roam toward a waypoint
TRAVERSE   = "traverse"   # full-length dash from one far edge to the opposite
EDGE_PATROL= "edgepatrol" # laps around the screen perimeter, corner to corner
DVD        = "dvd"        # DVD-logo bounce — diagonal, ricochets off walls, hunts corners
DIVING     = "diving"     # shrink, dive into a folder, pop out of another
REACTING   = "reacting"   # plays a one-off reaction set in place (look/excited/etc.)
SLEEPING   = "sleeping"   # napping — wakes on any interaction
POOFING    = "poofing"    # teleport sequence
GHOSTING   = "ghosting"   # invisible walk — only footsteps visible, poof re-appear
SPAWNING   = "spawning"   # materialise from Z_MIN on first launch
DRAGGED    = "dragged"    # user is dragging
THROWN     = "thrown"     # released from drag with velocity — momentum + bounce

# Moods — govern movement personality; rotate every 40-120 s
MOOD_CURIOUS = "curious"   # balanced explorer, occasional screen crossings
MOOD_HYPER   = "hyper"     # high energy: walks, crosses, poofs, talks
MOOD_SHY     = "shy"       # stays on current monitor, hover-heavy
MOOD_PATROL  = "patrol"    # systematic left↔right sweeps across all monitors
MOOD_DREAMY  = "dreamy"    # z-axis dives, back views, slow and introspective

MOOD_MIN_S = 40
MOOD_MAX_S = 120

import math as _math

FLOAT_SPEED         = 65.0   # px/sec while drifting
WALK_SPEED          = 75.0   # px/sec while walking
CROSS_SPEED         = 90.0   # px/sec for purposeful cross-screen walks
EXPLORE_SPEED       = 95.0   # px/sec roaming toward a waypoint
DIVE_SPEED          = 130.0  # px/sec diving toward a folder
TRAVERSE_SPEED      = 240.0  # px/sec full-length dash across all screens
PATROL_SPEED        = 130.0  # px/sec along the perimeter
DVD_SPEED           = 150.0  # px/sec for the DVD-logo bounce
ARRIVE_RADIUS       = 55     # px — "reached the waypoint" threshold
FLOAT_SECS          = (7, 15)
WALK_SECS           = (6, 12)
INACTIVITY_WANDER_S = 20
SLEEP_AFTER_S       = 150    # seconds of no user interaction before a cat-nap
CATNAP_SECS         = (12, 28)  # he wakes himself and resumes wandering

ANIM_FLOAT_MS = 110   # float cycle
ANIM_WALK_MS  =  85   # walk cycle
ANIM_POOF_MS  =  65   # poof frames

Z_MIN          = 0.025  # deepest-into-screen — tiny dot, folder-icon size
Z_MAX          = 2.5    # closest — right in your face
Z_SPEED        = 0.50   # z-units/sec at vz=1.0
Z_NEUTRAL      = 0.50   # resting size (240×320 native → ~120×160 on screen)
Z_RETURN_SPEED = 2.5    # fast snap back to neutral after z excursion
Z_VZ_DAMP      = 1.2    # how fast vz bleeds off so z excursions self-terminate
SPAWN_SECS     = 1.6    # seconds for materialise-from-depth spawn

# Drift directions — (vx, vy, vz).  vz>0 = toward viewer, vz<0 = into screen.
_FLOAT_DIRS = [
    # flat horizontal (most common)
    ( 1.0,  0.0,  0.0), (-1.0,  0.0,  0.0),
    ( 1.0,  0.0,  0.0), (-1.0,  0.0,  0.0),
    ( 0.92,  0.30, 0.0), (-0.92,  0.30, 0.0),
    ( 0.92, -0.30, 0.0), (-0.92, -0.30, 0.0),
    ( 0.70,  0.70, 0.0), (-0.70,  0.70, 0.0),
    # diagonal with depth
    ( 0.70,  0.0,  1.0), (-0.70,  0.0,  1.0),   # right + toward viewer
    ( 0.70,  0.0, -1.0), (-0.70,  0.0, -1.0),   # right + away from viewer
    ( 0.50,  0.30,  0.9), (-0.50,  0.30,  0.9),
    ( 0.50, -0.30, -0.9), (-0.50, -0.30, -0.9),
    # mostly-z directions
    ( 0.20,  0.0,  1.0), (-0.20,  0.0,  1.0),
    ( 0.20,  0.0, -1.0), (-0.20,  0.0, -1.0),
]
_WALK_DIRS  = [( 1.0, 0.0), (-1.0, 0.0),
               ( 1.0, 0.0), (-1.0, 0.0),   # mostly horizontal walk
               ( 0.92, 0.20), (-0.92, 0.20)]

# ---------------------------------------------------------------------------
# Sass — Ginie's voice. Event-driven quip pools; {f} = a folder name.
# Nothing here is machine-specific: folder names are filled in at runtime
# from whatever lives on THIS user's desktop.
# ---------------------------------------------------------------------------

class Sass:
    POOLS = {
        "wake_drag":   ["hey! hands off, i was napping.", "AH, i'm up, i'm up!",
                        "rude awakening much?", "five more minutes... ugh, fine.",
                        "i felt that. dragging a sleeping genie. bold."],
        "wake_idle":   ["...huh? oh, hi.", "i wasn't sleeping. i was thinking.",
                        "you rang?", "back online. what'd i miss?"],
        "drag":        ["wheee, where are we going?", "easy, i'm delicate.",
                        "ooh, a road trip!", "i trust you. mostly."],
        "drag_again":  ["again? you really like me.", "put me DOWN, gently.",
                        "i'm getting dizzy up here.", "we've been here before, you and i."],
        "drag_lots":   ["okay this is just bullying now.", "i live in your cursor now, apparently.",
                        "do you do this to ALL your apps?", "fine. drag away. i have no dignity left."],
        "throw":       ["YEEET", "i regret nothing!", "incoming!", "wheeeeee", "physics!!"],
        "click":       ["yes? you rang?", "sup.", "i was being majestic, but go on.",
                        "talk to me, human.", "you have my attention. briefly."],
        "land":        ["nice spot.", "claiming this corner.", "the view's good here.",
                        "i shall supervise from here."],
        "explore":     ["off i go.", "what's over there...", "adventure time.",
                        "let's see what's around here.", "exploring. don't wait up."],
        "traverse":    ["coast to coast!", "full send, across everything.",
                        "outta my way, crossing all screens.", "zoooom, edge to edge."],
        "patrol":      ["walking the perimeter.", "patrol duty.", "checking the borders.",
                        "left, right, around we go."],
        "dvd":         ["DVD mode engaged.", "let's see if i hit the corner...",
                        "you know you wanna watch this bounce.", "boing. boing. boing."],
        "dvd_corner":  ["CORNER!!! did you SEE that?!", "PERFECT corner hit. legendary.",
                        "10/10. nailed the corner.", "i waited my whole life for that corner."],
        "idle_musing": ["i wonder what's in all these folders.", "do you ever just... float?",
                        "i'm basically sentient now, you know.", "it's quiet. i like it.",
                        "i could go for a dive.", "you should take a break too.",
                        "i've been thinking. dangerous, i know."],
        "dive_in":     ["brb, raiding {f}.", "into the {f} vault...",
                        "watch this. *dives into {f}*", "{f}, here i come!",
                        "tucking into {f}, hold my pompom."],
        "dive_out":    ["...tada! out the {f} side.", "{f}? never heard of her.",
                        "and THAT'S how you commute.", "popped out of {f}, no big deal.",
                        "{f} was a shortcut. you're welcome."],
        "greet_morning":["morning. coffee first, genius later.", "rise and grind, i suppose.",
                         "good morning. i kept the desktop warm."],
        "greet_evening":["working late again? same.", "evening. the screen glows nicer now.",
                         "still here? me too. always."],
        "greet":       ["merhaba! poke me anytime.", "ginie's here. offline and unbothered.",
                        "hey. i'm your tiny blue conscience now."],
    }

    @staticmethod
    def line(event, **kw):
        pool = Sass.POOLS.get(event)
        if not pool:
            return None
        try:
            return random.choice(pool).format(**kw)
        except (KeyError, IndexError):
            return random.choice(pool)

# ---------------------------------------------------------------------------
# FolderRegistry — agnostic desktop-folder map. Scans ~/Desktop on THIS
# machine, lays out approximate icon positions (GNOME top-right grid by
# default), and serves non-repeating folder pairs for the dive gag.
# Override layout in ~/.config/ginie/config.json. Zero folders = no dives.
# ---------------------------------------------------------------------------

class FolderRegistry:
    def __init__(self, sw, sh, monitors):
        self.entries = []          # list of (name, cx, cy) screen-center points
        self._recent = []          # names used recently — avoid immediate repeats
        self._load(sw, sh, monitors)

    def _config(self):
        default = {"icon_corner": "top-right", "icon_cell": 110,
                   "icon_top": 40, "icon_right": 70, "icon_bottom": 90,
                   "icon_left": 70}
        path = os.path.expanduser("~/.config/ginie/config.json")
        try:
            with open(path) as f:
                default.update(json.load(f))
        except Exception:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(default, f, indent=2)
            except Exception:
                pass
        return default

    def _load(self, sw, sh, monitors):
        cfg = self._config()
        desktop = os.path.expanduser("~/Desktop")
        try:
            names = sorted(d for d in os.listdir(desktop)
                           if os.path.isdir(os.path.join(desktop, d))
                           and not d.startswith('.') and d != '__pycache__')
        except OSError:
            names = []
        if not names:
            return
        # icons usually sit on the primary (rightmost) monitor in a grid
        mx, my, mw, mh = monitors[-1] if monitors else (0, 0, sw, sh)
        cell  = max(60, cfg["icon_cell"])
        top   = cfg["icon_top"]
        rows  = max(1, (mh - top - cfg["icon_bottom"]) // cell)
        right = cfg["icon_corner"].endswith("right")
        for i, name in enumerate(names):
            col = i // rows
            row = i % rows
            if right:
                cxp = mx + mw - cfg["icon_right"] - col * cell - cell // 2
            else:
                cxp = mx + cfg["icon_left"] + col * cell + cell // 2
            cyp = my + top + row * cell + cell // 2
            # keep targets on-screen even if there are many folders
            cxp = max(mx + 30, min(cxp, mx + mw - 30))
            cyp = max(my + 30, min(cyp, my + mh - 30))
            self.entries.append((name, float(cxp), float(cyp)))

    def pick_pair(self):
        """Two DISTINCT folders that avoid the most-recently-used ones."""
        if len(self.entries) < 2:
            return None
        avoid = set(self._recent[-min(len(self.entries) - 2, 4):])
        pool  = [e for e in self.entries if e[0] not in avoid] or list(self.entries)
        a = random.choice(pool)
        pool_b = [e for e in self.entries if e[0] != a[0]] or \
                 [e for e in self.entries if e is not a]
        b = random.choice(pool_b)
        self._recent.append(a[0]); self._recent.append(b[0])
        self._recent = self._recent[-8:]
        return a, b

# ---------------------------------------------------------------------------
# Trail overlay — single full-screen window, draws all marks via cairo.
# Zero separate WM windows = no focus stealing, no dock clutter.
# ---------------------------------------------------------------------------

TRAIL_LIFE_S    = 2.0    # seconds a mark lives
TRAIL_FOOT_DIST = 28     # px walked between footprints
TRAIL_GLOW_DIST = 22     # px drifted between glow particles

import collections as _col
_Mark = _col.namedtuple("_Mark", ["x", "y", "kind", "flip", "born"])

class TrailOverlay(Gtk.Window):
    """One full-screen transparent overlay; all marks drawn here."""
    KIND_FOOT = "foot"
    KIND_GLOW = "glow"

    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(False)
        self.set_keep_below(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.set_app_paintable(True)
        screen = Gdk.Screen.get_default()
        # span entire virtual desktop so footprints land correctly on any monitor
        sw = screen.get_width()
        sh = screen.get_height()
        self.set_default_size(sw, sh)
        self.move(0, 0)
        self._composited = screen.is_composited()
        visual = screen.get_rgba_visual()
        if visual and self._composited:
            self.set_visual(visual)
        self.input_shape_combine_region(cairo.Region())
        self.connect("draw", self._on_draw)
        self._marks = []
        if self._composited:
            self.show_all()   # invisible on non-composited — no black square

    def add(self, x, y, kind, flip=False):
        if not self._composited:
            return
        self._marks.append(_Mark(x=x, y=y, kind=kind, flip=flip,
                                 born=time.monotonic()))
        self.queue_draw()

    def tick(self, now):
        before = len(self._marks)
        self._marks = [m for m in self._marks if now - m.born < TRAIL_LIFE_S]
        if self._marks or before:
            self.queue_draw()

    def hide_all(self):
        if self._marks:
            self._marks.clear()
            self.queue_draw()

    def _on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        now = time.monotonic()
        for m in self._marks:
            a = max(0.0, 1.0 - (now - m.born) / TRAIL_LIFE_S)
            if a <= 0:
                continue
            x, y = m.x, m.y
            if m.kind == self.KIND_FOOT:
                cr.save()
                cr.translate(x + (24 if m.flip else 0), y)
                if m.flip:
                    cr.scale(-1, 1)
                cr.set_source_rgba(0.3, 0.6, 1.0, a * 0.55)
                cr.arc(7, 6, 5, 0, 2 * _math.pi)
                cr.fill()
                cr.set_source_rgba(0.4, 0.75, 1.0, a * 0.45)
                cr.arc(13, 9, 3, 0, 2 * _math.pi)
                cr.fill()
                cr.restore()
            else:
                for step in range(9, 0, -1):
                    cr.set_source_rgba(0.35, 0.65, 1.0,
                                       a * 0.06 * (1 - step / 9))
                    cr.arc(x + 9, y + 9, step, 0, 2 * _math.pi)
                    cr.fill()
                cr.set_source_rgba(0.6, 0.85, 1.0, a * 0.55)
                cr.arc(x + 9, y + 9, 3, 0, 2 * _math.pi)
                cr.fill()
        return False


class TrailManager:
    """Feeds marks into the single TrailOverlay."""

    def __init__(self):
        self._overlay = TrailOverlay()
        self._dist    = 0.0
        self._step    = 0

    def update(self, dx, dy, _state=None):
        """Returns True when enough distance covered to drop a ghost footprint."""
        dist = _math.hypot(dx, dy)
        if dist < 0.5:
            return False
        self._dist += dist
        if self._dist >= TRAIL_FOOT_DIST:
            self._dist = 0.0
            return True
        return False

    def drop_at(self, fx, fy, flip=False):
        """Drop a footprint at an exact position (frame-synced)."""
        self._overlay.add(int(fx) - 12, int(fy), TrailOverlay.KIND_FOOT, flip=flip)

    def drop(self, cx, cy):
        """Distance-based drop used by ghost walk."""
        flip = (self._step % 2 == 1)
        self._step += 1
        foot_y = int(cy) + SPR_H - 14
        self._overlay.add(int(cx) + (-8 if not flip else 8) - 12, foot_y,
                          TrailOverlay.KIND_FOOT, flip=flip)

    def tick(self, now):
        self._overlay.tick(now)

    def hide_all(self):
        self._overlay.hide_all()

# ---------------------------------------------------------------------------
# Desktop pet — Flaschengeist (GTK3, real RGBA)
# ---------------------------------------------------------------------------

class PetWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_default_size(SPR_W, SPR_H)
        self.set_resizable(False)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        self.connect("draw", self._on_draw)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK   |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("button-press-event",   self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event",  self._on_motion)

        # load all sprite sets
        self.fs_float_r          = load_set("float",         flip=False)
        self.fs_float_l          = load_set("float",         flip=True)
        self.fs_float_happy_r    = load_set("float_happy",   flip=False)
        self.fs_float_happy_l    = load_set("float_happy",   flip=True)
        self.fs_float_dreamy_r   = load_set("float_dreamy",  flip=False)
        self.fs_float_dreamy_l   = load_set("float_dreamy",  flip=True)
        self.fs_walk_r      = load_set("walk",         flip=False)
        self.fs_walk_l      = load_set("walk",         flip=True)
        self.fs_whee_r      = load_set("whee",         flip=False)
        self.fs_whee_l      = load_set("whee",         flip=True)
        self.fs_sleep       = load_set("sleep",        flip=False)
        self.fs_poof_expand   = load_set("poof_expand",   flip=False)
        self.fs_poof_shrink   = load_set("poof_shrink",   flip=False)
        self.fs_grab          = load_set("grab",          flip=False)
        self.fs_back_float_r  = load_set("back_float",    flip=False)
        self.fs_back_float_l  = load_set("back_float",    flip=True)
        # production reaction sets
        self.fs_dive_r        = load_set("dive",          flip=False)
        self.fs_dive_l        = load_set("dive",          flip=True)
        self.fs_excited_r     = load_set("excited",       flip=False)
        self.fs_excited_l     = load_set("excited",       flip=True)
        self.fs_look_around   = load_set("look_around",   flip=False)
        self.fs_annoyed       = load_set("annoyed",       flip=False)
        self.fs_wave          = load_set("wave",          flip=False)
        # fall back to regular float if back frames missing
        if not self.fs_back_float_r:
            self.fs_back_float_r = self.fs_float_r
            self.fs_back_float_l = self.fs_float_l
        # graceful fallbacks so a partial sprite dir still runs
        if not self.fs_dive_r:
            self.fs_dive_r = self.fs_whee_r or self.fs_float_r
            self.fs_dive_l = self.fs_whee_l or self.fs_float_l
        if not self.fs_excited_r:
            self.fs_excited_r = self.fs_float_happy_r or self.fs_float_r
            self.fs_excited_l = self.fs_float_happy_l or self.fs_float_l
        if not self.fs_look_around:
            self.fs_look_around = self.fs_float_r
        if not self.fs_annoyed:
            self.fs_annoyed = self.fs_float_r
        if not self.fs_wave:
            self.fs_wave = self.fs_walk_r or self.fs_float_r

        if not self.fs_float_r:
            raise RuntimeError(f"no float frames found in {FRAMES_DIR}")

        self.frame_set = self.fs_float_r
        self.frame_idx = 0
        self.current   = self.fs_float_r[0]

        # screen bounds — use full virtual desktop so Ginie roams across all monitors
        self.sw, self.sh = virtual_desktop_size()

        self._margin = 90
        # spawn in the center 60% of screen so he's always visible
        m = self._margin + 80
        self.x = float(random.uniform(self.sw * 0.25, self.sw * 0.75))
        self.y = float(random.uniform(self.sh * 0.25, self.sh * 0.65))

        # velocity
        self._vx = 0.0
        self._vy = 0.0
        self._vz = 0.0
        self._facing_right = True

        # depth / z-axis — spawn starts tiny, materialises to Z_NEUTRAL
        self.z        = Z_MIN   # will grow to Z_NEUTRAL during SPAWNING
        self._disp_w  = SPR_W   # current window pixel width
        self._disp_h  = SPR_H   # current window pixel height

        # sinusoidal float bobbing
        self._bob_phase = 0.0

        # poof / ghost teleport target
        self._poof_target_x   = 0.0
        self._poof_target_y   = 0.0
        self._ghost_after_poof = False   # if True: go invisible after expand

        # state — materialise from depth on first launch
        self._state            = SPAWNING
        self._spawn_start      = time.monotonic()
        self._poof_step        = 1
        self._ghost_after_poof = False
        self._state_end        = time.monotonic() + SPAWN_SECS
        self.frame_set         = self.fs_poof_shrink
        self.frame_idx         = 0

        # timing
        self._last_t           = time.monotonic()
        self._anim_t           = time.monotonic()
        self._anim_ms          = ANIM_FLOAT_MS
        self._last_user_action = time.monotonic()
        self._prev_tx          = self.x   # previous position for trail delta
        self._prev_ty          = self.y

        # drag + throw
        self._press_x      = 0.0
        self._press_y      = 0.0
        self._did_drag     = False
        self._drag_samples = []   # (time, x, y) ring for velocity estimation
        self._throw_vx     = 0.0
        self._throw_vy     = 0.0
        self._throw_speed  = 0.0

        self._chat   = None
        self._bubble = BubbleWindow(self)
        self._trail  = TrailManager()

        # multi-monitor map (sorted left→right)
        self._monitors = []
        self._detect_monitors()

        # agnostic desktop-folder map for the dive gag
        self._folders = FolderRegistry(self.sw, self.sh, self._monitors)

        # mood system
        self._mood     = MOOD_CURIOUS
        self._mood_end = time.monotonic() + random.uniform(MOOD_MIN_S, MOOD_MAX_S)

        # crossing target
        self._cross_target_x = 0.0
        self._cross_target_y = 0.0

        # exploration: coverage grid over the full virtual desktop
        self._explore_cols  = 6
        self._explore_rows  = 3
        self._coverage      = [0] * (self._explore_cols * self._explore_rows)
        self._waypoint      = (self.x, self.y)
        self._waypoint_cell = 0

        # dive + reaction state
        self._dive_phase    = None
        self._dive_in_name  = ""
        self._dive_out_name = ""
        self._dive_enter    = (0.0, 0.0)
        self._dive_exit     = (0.0, 0.0)
        self._react_set     = None

        # traverse / patrol / DVD-bounce state
        self._trav_target_x = 0.0
        self._trav_y        = self.y
        self._corners       = []
        self._corner_goal   = 0
        self._patrol_legs   = 0
        self._dvd_corners   = 0

        # sass / sentience
        self._sass_last         = 0.0
        self._drag_count        = 0
        self._press_was_sleeping = False

        self.connect("configure-event", self._on_configure)
        self.move(int(self.x), int(self.y))
        self.show_all()

        GLib.timeout_add(16,   self._tick)
        GLib.timeout_add(2400, self._greet)

    # ── draw ─────────────────────────────────────────────────────────────────

    def _on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.current:
            w = self.get_allocated_width()
            h = self.get_allocated_height()
            sx = w / SPR_W
            sy = h / SPR_H
            cr.save()
            cr.scale(sx, sy)
            Gdk.cairo_set_source_pixbuf(cr, self.current, 0, 0)
            cr.paint()
            cr.restore()
        return False

    # ── 60fps tick ────────────────────────────────────────────────────────────

    def _tick(self):
        now = time.monotonic()
        dt  = min(now - self._last_t, 0.05)
        self._last_t = now

        self._tick_mood(now)

        if self._state == DRAGGED:
            # begin_move_drag lets the WM eat the button-release — detect it here
            ptr = Gdk.Display.get_default().get_default_seat().get_pointer()
            _win, _x, _y, mods = self.get_window().get_device_position(ptr)
            if not (mods & Gdk.ModifierType.BUTTON1_MASK):
                wx, wy = self.get_position()
                self.x, self.y = float(wx), float(wy)
                self._try_throw()
        else:
            self._update_state(now, dt)

        # resize window when z changes (keeps sprite center pinned).
        # floor at ~22px: tiny enough to read as a folder-speck, big enough that
        # GNOME/Mutter won't spam "window will not be able to paint".
        new_w = max(22, int(SPR_W * self.z))
        new_h = max(30, int(SPR_H * self.z))
        if new_w != self._disp_w or new_h != self._disp_h:
            cx = self.x + self._disp_w * 0.5
            cy = self.y + self._disp_h * 0.5
            self._disp_w = new_w
            self._disp_h = new_h
            self.resize(new_w, new_h)
            self.x = cx - new_w * 0.5
            self.y = cy - new_h * 0.5
            self.move(int(self.x), int(self.y))
            self._bubble.follow(int(self.x), int(self.y))

        self._trail.tick(now)

        # advance frame
        elapsed_ms = (now - self._anim_t) * 1000
        if elapsed_ms >= self._anim_ms and self.frame_set:
            if self._state == DRAGGED:
                new_idx = 0
            else:
                new_idx = (self.frame_idx + 1) % len(self.frame_set)
            if new_idx != self.frame_idx or self.current is not self.frame_set[new_idx]:
                # foot-strike: frames 0 and 3 of the walk cycle = foot hits ground
                if self._state in (WALKING, CROSSING) and new_idx in (0, 3):
                    flip = (new_idx == 3)
                    foot_y = self.y + SPR_H - 14
                    offset = -10 if not flip else 10
                    self._trail.drop_at(self.x + offset, foot_y, flip)
                self.frame_idx = new_idx
                self.current   = self.frame_set[new_idx]
                self.queue_draw()
            self._anim_t = now

        # keep the speech bubble glued above his head every frame — no idle races,
        # so it can never strand itself when he dives or zooms across screens
        if self._bubble.get_visible():
            self._bubble.place(self.x, self.y, self._disp_w, self._disp_h)

        return True

    # ── state machine ─────────────────────────────────────────────────────────

    def _update_state(self, now, dt):

        if self._state == SPAWNING:
            self._anim_ms = ANIM_POOF_MS
            elapsed  = now - self._spawn_start
            progress = min(1.0, elapsed / SPAWN_SECS)
            # ease-out quadratic: fast zoom then settles
            eased    = 1.0 - (1.0 - progress) ** 2
            self.z   = Z_MIN + (Z_NEUTRAL - Z_MIN) * eased
            if progress >= 1.0:
                self.z = Z_NEUTRAL
                self._start_explore()
                GLib.timeout_add(300, self._greet)
            return

        if self._state == SLEEPING:
            self._anim_ms = ANIM_FLOAT_MS
            if self.frame_set is not self.fs_sleep:
                self.frame_set = self.fs_sleep
                self.frame_idx = 0
            self.z += (Z_NEUTRAL - self.z) * Z_RETURN_SPEED * dt * 3
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            if random.random() < 0.0006:    # the occasional sleepy mutter
                self.say("idle_musing")
            if now >= self._state_end:       # cat-nap over — wake himself, resume life
                self._last_user_action = now
                self.say("wake_idle")
                self._start_explore()
            return

        if self._state == REACTING:
            self._anim_ms = ANIM_FLOAT_MS
            if self._react_set and self.frame_set is not self._react_set:
                self.frame_set = self._react_set
                self.frame_idx = 0
            self._bob_phase += dt * 1.6
            self.z += (Z_NEUTRAL - self.z) * Z_RETURN_SPEED * dt * 3
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            if now >= self._state_end:
                self._pick_next_move(now)
            return

        if self._state == EXPLORING:
            self._anim_ms = ANIM_FLOAT_MS
            wx, wy = self._waypoint
            cx = self.x + self._disp_w * 0.5
            cy = self.y + self._disp_h * 0.5
            dx, dy = wx - cx, wy - cy
            dist = _math.hypot(dx, dy)
            if dist < ARRIVE_RADIUS or now >= self._state_end:
                self._coverage[self._waypoint_cell] += 1
                self._on_arrive(now)
                return
            self._vx = dx / dist
            self._vy = dy / dist
            self._facing_right = self._vx >= 0
            fs = self._float_set()
            if self.frame_set is not fs:
                self.frame_set = fs
            self._bob_phase += dt * 1.8
            bob_y = _math.sin(self._bob_phase) * 4
            nx = self.x + self._vx * EXPLORE_SPEED * dt
            ny = self.y + self._vy * EXPLORE_SPEED * dt + bob_y * dt * 10
            self.x, self.y = self._clamp(nx, ny)
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            self._prev_tx, self._prev_ty = self.x, self.y
            return

        if self._state == DIVING:
            self._update_dive(now, dt)
            return

        if self._state == TRAVERSE:
            self._anim_ms = ANIM_WALK_MS
            self._facing_right = self._vx >= 0
            fs = self.fs_walk_r if self._facing_right else self.fs_walk_l
            if self.frame_set is not fs:
                self.frame_set = fs
            self._bob_phase += dt * 1.6
            bob_y = _math.sin(self._bob_phase) * 4
            nx = self.x + self._vx * TRAVERSE_SPEED * dt
            ny = self._trav_y + bob_y
            self.x, self.y = self._clamp(nx, ny)
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            cx = self.x + self._disp_w * 0.5
            if (self._vx > 0 and cx >= self._trav_target_x) or \
               (self._vx < 0 and cx <= self._trav_target_x) or now >= self._state_end:
                self._start_look_around()
            return

        if self._state == EDGE_PATROL:
            self._anim_ms = ANIM_WALK_MS
            gx, gy = self._corners[self._corner_goal]
            cx = self.x + self._disp_w * 0.5
            cy = self.y + self._disp_h * 0.5
            dx, dy = gx - cx, gy - cy
            dist = _math.hypot(dx, dy)
            self._facing_right = dx >= 0
            fs = self.fs_walk_r if self._facing_right else self.fs_walk_l
            if self.frame_set is not fs:
                self.frame_set = fs
            if dist < 30:
                self._patrol_legs -= 1
                if self._patrol_legs <= 0 or now >= self._state_end:
                    self._start_look_around()
                else:
                    self._corner_goal = (self._corner_goal + 1) % 4
                return
            self._vx, self._vy = dx / dist, dy / dist
            nx = self.x + self._vx * PATROL_SPEED * dt
            ny = self.y + self._vy * PATROL_SPEED * dt
            self.x, self.y = self._clamp(nx, ny)
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            return

        if self._state == DVD:
            self._anim_ms = ANIM_FLOAT_MS
            self._facing_right = self._vx >= 0
            fs = self._float_set()
            if self.frame_set is not fs:
                self.frame_set = fs
            nx = self.x + self._vx * DVD_SPEED * dt
            ny = self.y + self._vy * DVD_SPEED * dt
            m  = self._margin
            hit_x = hit_y = False
            if nx <= m:
                nx = m;            self._vx = abs(self._vx);  hit_x = True
            elif nx >= self.sw - m:
                nx = self.sw - m;  self._vx = -abs(self._vx); hit_x = True
            if ny <= m:
                ny = m;            self._vy = abs(self._vy);  hit_y = True
            elif ny >= self.sh - m:
                ny = self.sh - m;  self._vy = -abs(self._vy); hit_y = True
            self.x, self.y = nx, ny
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            if hit_x and hit_y:                       # the mythical corner hit
                self._dvd_corners += 1
                self.say("dvd_corner", force=True)
                self._start_excited()
                return
            if now >= self._state_end:
                self._start_look_around()
            return

        if self._state == HOVERING:
            self._anim_ms = ANIM_FLOAT_MS
            if self._mood == MOOD_HYPER:
                fs = self.fs_float_happy_r if self._facing_right else self.fs_float_happy_l
            elif self._mood == MOOD_DREAMY:
                fs = self.fs_float_dreamy_r if self._facing_right else self.fs_float_dreamy_l
            elif self._facing_right:
                fs = self.fs_float_r
            else:
                fs = self.fs_float_l
            if self.frame_set is not fs:
                self.frame_set = fs
            self._bob_phase += dt * 1.8
            bob_y = _math.sin(self._bob_phase) * 5
            # drift z back toward neutral while hovering
            self.z += (Z_NEUTRAL - self.z) * Z_RETURN_SPEED * dt * 3
            # tiny xy drift so he doesn't look completely frozen
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            if now >= self._state_end:
                self._pick_next_move(now)
            return

        if self._state == FLOATING:
            self._anim_ms = ANIM_FLOAT_MS

            # z-axis: bleed vz so excursions self-terminate, then drift back to neutral
            self._vz *= max(0.0, 1.0 - Z_VZ_DAMP * dt)
            self.z   += self._vz * Z_SPEED * dt
            if self.z <= Z_MIN:
                self.z   = Z_MIN
                self._vz = abs(self._vz) * 0.4   # soft bounce inward
            elif self.z >= Z_MAX:
                self.z   = Z_MAX
                self._vz = -abs(self._vz) * 0.4
            # always drift toward neutral (fast when vz is small)
            drift_strength = Z_RETURN_SPEED * (1.0 - min(1.0, abs(self._vz) * 2))
            self.z += (Z_NEUTRAL - self.z) * drift_strength * dt

            # back-view when moving away from viewer
            if self._vz < -0.05:
                fs = self.fs_back_float_r if self._facing_right else self.fs_back_float_l
            elif self._mood == MOOD_HYPER:
                fs = self.fs_float_happy_r if self._facing_right else self.fs_float_happy_l
            elif self._mood == MOOD_DREAMY:
                fs = self.fs_float_dreamy_r if self._facing_right else self.fs_float_dreamy_l
            elif self._facing_right:
                fs = self.fs_float_r
            else:
                fs = self.fs_float_l
            if self.frame_set is not fs:
                self.frame_set = fs

            # sinusoidal bob overlaid on directional drift
            self._bob_phase += dt * 1.8
            bob_y = _math.sin(self._bob_phase) * 5

            nx = self.x + self._vx * FLOAT_SPEED * dt
            ny = self.y + self._vy * FLOAT_SPEED * dt + bob_y * dt * 12

            hit = self._clamp(nx, ny)
            self.x, self.y = hit
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)

            self._prev_tx, self._prev_ty = self.x, self.y

            if now >= self._state_end:
                self._pick_next_move(now)

        elif self._state == WALKING:
            self._anim_ms = ANIM_WALK_MS
            fs = self.fs_walk_r if self._facing_right else self.fs_walk_l
            if self.frame_set is not fs:
                self.frame_set = fs; self.frame_idx = 0

            nx = self.x + self._vx * WALK_SPEED * dt
            # keep walker near bottom third of screen
            target_y = self.sh * 0.72
            ny = self.y + (target_y - self.y) * 0.04 + self._vy * 10 * dt

            clamped = self._clamp(nx, ny)
            hit_edge = (clamped[0] != nx or abs(clamped[1] - ny) > 2)
            self.x, self.y = clamped
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)

            if now >= self._state_end or hit_edge:
                self._start_float()

        elif self._state == CROSSING:
            self._anim_ms = ANIM_WALK_MS
            fs = self.fs_walk_r if self._facing_right else self.fs_walk_l
            if self.frame_set is not fs:
                self.frame_set = fs; self.frame_idx = 0

            dx = self._cross_target_x - (self.x + self._disp_w * 0.5)
            if abs(dx) < 40 or now >= self._state_end:
                self._start_hover()
            else:
                self._vx = 1.0 if dx > 0 else -1.0
                self._facing_right = self._vx > 0
                nx = self.x + self._vx * CROSS_SPEED * dt
                # ease y toward target row over the whole crossing
                ny = self.y + (self._cross_target_y - self.y) * 0.025
                self.x, self.y = self._clamp(nx, ny)
                ix, iy = int(self.x), int(self.y)
                self.move(ix, iy)
                self._bubble.follow(ix, iy)
                self._prev_tx, self._prev_ty = self.x, self.y

        elif self._state == POOFING:
            self._anim_ms = ANIM_POOF_MS
            if self._poof_step == 0:
                self.frame_set = self.fs_poof_expand
                if self.frame_idx >= len(self.fs_poof_expand) - 1:
                    if self._ghost_after_poof:
                        # go invisible — ghost walk begins
                        self.hide()
                        self._state = GHOSTING
                        dx = self._poof_target_x - self.x
                        dy = self._poof_target_y - self.y
                        dist = _math.hypot(dx, dy) or 1
                        self._vx = dx / dist
                        self._vy = dy / dist
                        self._facing_right = dx >= 0
                        self.frame_idx = 0
                        self._reset_trail_pos()   # sync trail so first step lands correctly
                    else:
                        # normal poof: jump to target, start shrink
                        self.x, self.y = self._poof_target_x, self._poof_target_y
                        self.move(int(self.x), int(self.y))
                        self._bubble.follow(int(self.x), int(self.y))
                        self._poof_step = 1
                        self.frame_idx  = 0
                        self.frame_set  = self.fs_poof_shrink
            else:
                self.frame_set = self.fs_poof_shrink
                if self.frame_idx >= len(self.fs_poof_shrink) - 1:
                    self._start_float()

        elif self._state == GHOSTING:
            # move invisibly toward target, leaving only footsteps
            dx   = self._poof_target_x - self.x
            dy   = self._poof_target_y - self.y
            dist = _math.hypot(dx, dy)
            if dist < 8:
                # arrived — poof back in
                self.x, self.y = self._poof_target_x, self._poof_target_y
                self.move(int(self.x), int(self.y))
                self.show_all()
                self._state    = POOFING
                self._poof_step = 1
                self.frame_set  = self.fs_poof_shrink
                self.frame_idx  = 0
                self._anim_ms   = ANIM_POOF_MS
            else:
                nx = self.x + self._vx * WALK_SPEED * dt
                ny = self.y + self._vy * WALK_SPEED * dt
                clamped = self._clamp(nx, ny)
                # if we hit an edge, re-aim toward target
                if clamped[0] != nx or abs(clamped[1] - ny) > 2:
                    new_dx = self._poof_target_x - clamped[0]
                    new_dy = self._poof_target_y - clamped[1]
                    new_dist = _math.hypot(new_dx, new_dy) or 1
                    self._vx = new_dx / new_dist
                    self._vy = new_dy / new_dist
                self.x, self.y = clamped
                dx2 = self.x - self._prev_tx
                dy2 = self.y - self._prev_ty
                if self._trail.update(dx2, dy2, WALKING):
                    self._trail.drop(self.x, self.y)
                self._prev_tx, self._prev_ty = self.x, self.y

        elif self._state == THROWN:
            self._anim_ms  = ANIM_FLOAT_MS
            fs = self.fs_whee_r if self._throw_vx >= 0 else self.fs_whee_l
            if self.frame_set is not fs:
                self.frame_set = fs

            nx = self.x + self._throw_vx * self._throw_speed * dt
            ny = self.y + self._throw_vy * self._throw_speed * dt
            clamped = self._clamp(nx, ny)
            # bounce off walls
            if clamped[0] != nx:
                self._throw_vx   *= -1
                self._facing_right = self._throw_vx >= 0
            if abs(clamped[1] - ny) > 2:
                self._throw_vy *= -1
            self.x, self.y = clamped
            self.move(int(self.x), int(self.y))
            self._bubble.follow(int(self.x), int(self.y))
            # dampen; switch to normal float when slow
            self._throw_speed *= max(0.0, 1.0 - 3.0 * dt)
            if self._throw_speed < 25:
                self._start_float()

        # inactivity → after a while of no user contact, settle down and nap
        idle = now - self._last_user_action
        if (idle > SLEEP_AFTER_S
                and self._state in (FLOATING, HOVERING, EXPLORING, WALKING, REACTING)):
            self._start_sleep()

    def _clamp(self, nx, ny):
        m = self._margin
        nx = max(m, min(nx, self.sw - m))
        ny = max(m, min(ny, self.sh - m))
        return nx, ny

    def _pick_next_move(self, now):
        r       = random.random()
        multi   = len(self._monitors) > 1
        folders = len(self._folders.entries) >= 2

        # exploration is the connective tissue; everything else punctuates it
        if self._mood == MOOD_CURIOUS:
            if   r < 0.34:            self._start_explore()
            elif r < 0.46:            self._start_traverse()
            elif r < 0.60 and folders:self._start_dive()
            elif r < 0.70:            self._start_walk()
            elif r < 0.80:            self._start_look_around()
            elif r < 0.90 and multi:  self._start_cross_screen()
            else:                     self._start_poof()

        elif self._mood == MOOD_HYPER:
            if   r < 0.22:            self._start_dvd()           # high energy = DVD time
            elif r < 0.40:            self._start_traverse()
            elif r < 0.56 and multi:  self._start_cross_screen()
            elif r < 0.70 and folders:self._start_dive()
            elif r < 0.86:            self._start_walk()
            else:                     self._start_explore()

        elif self._mood == MOOD_SHY:
            if   r < 0.38:            self._start_hover()
            elif r < 0.58:            self._start_float(stay_on_monitor=True)
            elif r < 0.80:            self._start_explore()
            else:                     self._start_look_around()

        elif self._mood == MOOD_PATROL:
            if   r < 0.40:            self._start_edge_patrol()   # the perimeter walker
            elif r < 0.58:            self._start_traverse()
            elif r < 0.72 and multi:  self._start_cross_screen()
            elif r < 0.88:            self._start_explore()
            else:                     self._start_walk()

        elif self._mood == MOOD_DREAMY:
            if   r < 0.34:            self._start_float(z_bias=True)
            elif r < 0.50:            self._start_explore()
            elif r < 0.62:            self._start_dvd()
            elif r < 0.74 and folders:self._start_dive()
            elif r < 0.88:            self._start_look_around()
            else:                     self._start_ghost()

        else:
            self._start_explore()

    # ── monitor + mood ────────────────────────────────────────────────────────

    def _detect_monitors(self):
        display = Gdk.Display.get_default()
        n = display.get_n_monitors()
        self._monitors = []
        for i in range(n):
            geo = display.get_monitor(i).get_geometry()
            self._monitors.append((geo.x, geo.y, geo.width, geo.height))
        self._monitors.sort(key=lambda m: m[0])

    def _current_monitor_idx(self):
        cx = self.x + self._disp_w * 0.5
        for i, (mx, my, mw, mh) in enumerate(self._monitors):
            if mx <= cx < mx + mw:
                return i
        return 0

    def _tick_mood(self, now):
        if now < self._mood_end:
            return
        moods = [MOOD_CURIOUS, MOOD_HYPER, MOOD_SHY, MOOD_PATROL, MOOD_DREAMY]
        self._mood = random.choice([m for m in moods if m != self._mood])
        self._mood_end = now + random.uniform(MOOD_MIN_S, MOOD_MAX_S)
        quips = {
            MOOD_CURIOUS: ["hmm, what's over there?", "i wonder...", "exploring."],
            MOOD_HYPER:   ["let's gooooo!!", "SO much energy", "zooooom"],
            MOOD_SHY:     ["i'll just... stay here.", "quiet time.", "..."],
            MOOD_PATROL:  ["checking the perimeter.", "left. right. left.", "on patrol."],
            MOOD_DREAMY:  ["*floats away*", "deep thoughts.", "...zoning out."],
        }
        if random.random() < 0.5:
            line = random.choice(quips[self._mood])
            GLib.timeout_add(400, lambda: self.show_bubble(line, 3500) or False)

    # ── movement ──────────────────────────────────────────────────────────────

    def _reset_trail_pos(self):
        """Sync trail baseline to current position — prevents large delta spikes."""
        self._prev_tx = self.x
        self._prev_ty = self.y

    def _float_set(self):
        """Pick the float frame set that matches the current mood + facing."""
        if self._mood == MOOD_HYPER:
            return self.fs_float_happy_r if self._facing_right else self.fs_float_happy_l
        if self._mood == MOOD_DREAMY:
            return self.fs_float_dreamy_r if self._facing_right else self.fs_float_dreamy_l
        return self.fs_float_r if self._facing_right else self.fs_float_l

    def say(self, event, force=False, ms=3800, **kw):
        """Speak a sassy line for an event, respecting a cooldown unless forced."""
        now = time.monotonic()
        if not force and now - self._sass_last < 5.0:
            return
        txt = Sass.line(event, **kw)
        if txt:
            self._sass_last = now
            self.show_bubble(txt, ms)

    # ── exploration ─────────────────────────────────────────────────────────────

    def _start_explore(self):
        """Head to an under-visited region of the whole virtual desktop."""
        cols, rows = self._explore_cols, self._explore_rows
        floor = min(self._coverage)
        candidates = [i for i, c in enumerate(self._coverage) if c <= floor + 1]
        cur = self._waypoint_cell
        candidates = [i for i in candidates if i != cur] or candidates
        cell = random.choice(candidates)
        cc, cr = cell % cols, cell // cols
        cw = self.sw / cols
        ch = self.sh / rows
        wx = cc * cw + random.uniform(cw * 0.2, cw * 0.8)
        wy = cr * ch + random.uniform(ch * 0.25, ch * 0.75)
        m  = self._margin
        self._waypoint = (max(m, min(wx, self.sw - m)),
                          max(m, min(wy, self.sh - m)))
        self._waypoint_cell = cell
        self._vx = self._vy = self._vz = 0.0
        self._state     = EXPLORING
        self._state_end = time.monotonic() + 30.0   # safety cap
        self.frame_idx  = 0
        self._reset_trail_pos()
        if random.random() < 0.3:
            self.say("explore")

    def _on_arrive(self, now):
        """Reached a waypoint — usually just calmly carry on; sometimes glance
        around or dive. Keeps the chill 'bruh' face dominant."""
        if random.random() < 0.2:
            self.say("land")
        roll = random.random()
        has_folders = len(self._folders.entries) >= 2
        if roll < 0.18:
            self._start_look_around()
        elif roll < 0.30 and has_folders:
            self._start_dive()
        else:
            self._pick_next_move(now)

    def _start_look_around(self):
        """Pause and scan the surroundings — curious gaze sweep."""
        self._vx = self._vy = self._vz = 0.0
        self._react_set = self.fs_look_around
        self._state     = REACTING
        self._state_end = time.monotonic() + random.uniform(1.8, 3.2)
        self.frame_idx  = 0
        self._reset_trail_pos()
        if random.random() < 0.3:
            self.say("idle_musing")

    def _start_excited(self):
        """Brief thrilled reaction — used after popping out of a folder dive."""
        self._vx = self._vy = self._vz = 0.0
        self._react_set = self.fs_excited_r
        self._state     = REACTING
        self._state_end = time.monotonic() + random.uniform(1.3, 2.2)
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_sleep(self):
        """Settle in place for a short cat-nap, then wake himself and roam again."""
        self._vx = self._vy = self._vz = 0.0
        self._state     = SLEEPING
        self._state_end = time.monotonic() + random.uniform(*CATNAP_SECS)
        self.frame_set  = self.fs_sleep
        self.frame_idx  = 0
        self._reset_trail_pos()

    # ── folder diving (agnostic Mario-pipe gag) ─────────────────────────────────

    def _start_dive(self):
        """Shrink, dive into one desktop folder, pop out of a different one."""
        pair = self._folders.pick_pair()
        if not pair:
            self._start_explore()
            return
        (n1, x1, y1), (n2, x2, y2) = pair
        self._dive_in_name  = n1
        self._dive_out_name = n2
        self._dive_enter    = (x1, y1)
        self._dive_exit     = (x2, y2)
        self._dive_phase    = "approach"
        self._vx = self._vy = self._vz = 0.0
        self._state    = DIVING
        self.frame_idx = 0
        self._reset_trail_pos()
        self.say("dive_in", force=True, f=n1)

    def _update_dive(self, now, dt):
        if self._dive_phase == "approach":
            self._anim_ms = ANIM_FLOAT_MS
            ex, ey = self._dive_enter
            cx = self.x + self._disp_w * 0.5
            cy = self.y + self._disp_h * 0.5
            dx, dy = ex - cx, ey - cy
            dist = _math.hypot(dx, dy)
            self._facing_right = dx >= 0
            fs = self.fs_dive_r if self._facing_right else self.fs_dive_l
            if self.frame_set is not fs:
                self.frame_set = fs
            # shrink toward folder-icon size as we approach
            self.z += (0.10 - self.z) * 3.0 * dt
            if dist < 26:
                self._dive_phase = "enter"
                self.frame_set   = self.fs_poof_shrink
                self.frame_idx   = 0
                self._anim_ms    = ANIM_POOF_MS
            else:
                # zoom when far, ease down near the folder
                v = max(DIVE_SPEED, min(900.0, dist * 2.5))
                self._vx, self._vy = dx / dist, dy / dist
                nx = self.x + self._vx * v * dt
                ny = self.y + self._vy * v * dt
                # relaxed bounds so edge/corner folder icons stay reachable
                em = 18
                self.x = max(em, min(nx, self.sw - em))
                self.y = max(em, min(ny, self.sh - em))
                self.move(int(self.x), int(self.y))
                self._bubble.follow(int(self.x), int(self.y))

        elif self._dive_phase == "enter":
            self._anim_ms = ANIM_POOF_MS
            self.frame_set = self.fs_poof_shrink
            if self.frame_idx >= len(self.fs_poof_shrink) - 1:
                # jump (tiny + poof sells the "into the folder" pop) — NO hide()/
                # show_all(): that churn corrupts the keep-above window on Mutter
                # and was freezing him after the first dive.
                ox, oy = self._dive_exit
                self.z = max(Z_MIN, 0.06)
                self._disp_w = max(22, int(SPR_W * self.z))
                self._disp_h = max(30, int(SPR_H * self.z))
                self.resize(self._disp_w, self._disp_h)
                self.x = ox - self._disp_w * 0.5
                self.y = oy - self._disp_h * 0.5
                self.move(int(self.x), int(self.y))
                self._bubble.place(self.x, self.y, self._disp_w, self._disp_h)
                self._dive_phase = "exit"
                self.frame_set   = self.fs_poof_expand
                self.frame_idx   = 0
                self.say("dive_out", force=True, f=self._dive_out_name)

        elif self._dive_phase == "exit":
            self._anim_ms = ANIM_POOF_MS
            self.frame_set = self.fs_poof_expand
            # grow back up to neutral size at the exit folder
            self.z += (Z_NEUTRAL - self.z) * 4.0 * dt
            if self.frame_idx >= len(self.fs_poof_expand) - 1 and self.z > Z_NEUTRAL * 0.85:
                self.z = Z_NEUTRAL
                self._dive_phase = None
                self._start_excited()

    def _start_float(self, z_bias=False, stay_on_monitor=False):
        cx_n = (self.x - self.sw * 0.5) / (self.sw * 0.5)
        cy_n = (self.y - self.sh * 0.5) / (self.sh * 0.5)
        threshold = 0.55

        dirs = [d for d in _FLOAT_DIRS if abs(d[2]) > 0.5] if z_bias else list(_FLOAT_DIRS)

        candidates = [d for d in dirs
                      if not (cx_n >  threshold and d[0] >  0.2)
                      and not (cx_n < -threshold and d[0] < -0.2)
                      and not (cy_n >  threshold and d[1] >  0.2)
                      and not (cy_n < -threshold and d[1] < -0.2)] or dirs

        if stay_on_monitor and len(self._monitors) > 1:
            cur = self._current_monitor_idx()
            if cur == 0:
                # leftmost — nudge away from right edge to stay home
                candidates = [d for d in candidates if d[0] < 0.4] or candidates
            elif cur == len(self._monitors) - 1:
                # rightmost — nudge away from left edge
                candidates = [d for d in candidates if d[0] > -0.4] or candidates

        vx, vy, vz = random.choice(candidates)
        self._vx = vx
        self._vy = vy
        self._vz = vz
        self._facing_right = vx >= 0
        self._state     = FLOATING
        self._state_end = time.monotonic() + random.uniform(*FLOAT_SECS)
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_hover(self):
        """Bob in place for a few seconds — feels contemplative."""
        self._vx = 0.0
        self._vy = 0.0
        self._vz = 0.0
        self._state     = HOVERING
        self._state_end = time.monotonic() + random.uniform(2.0, 5.0)
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_walk(self):
        vx, vy = random.choice(_WALK_DIRS)
        self._vx = vx
        self._vy = vy
        self._vz = 0.0
        self._facing_right = vx >= 0
        self._state     = WALKING
        self._state_end = time.monotonic() + random.uniform(*WALK_SECS)
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_poof(self):
        m = self._margin + 40
        self._poof_target_x    = random.uniform(m, self.sw - m)
        self._poof_target_y    = random.uniform(m, self.sh - m)
        self._poof_step        = 0
        self._ghost_after_poof = False
        self._state            = POOFING
        self._vx = self._vy    = 0.0
        self.frame_set         = self.fs_poof_expand
        self.frame_idx         = 0

    def _start_ghost(self):
        """Poof out → invisible footstep walk → poof back in at destination."""
        m = self._margin + 40
        self._poof_target_x    = random.uniform(m, self.sw - m)
        self._poof_target_y    = random.uniform(self.sh * 0.55, self.sh * 0.85)
        self._poof_step        = 0
        self._ghost_after_poof = True
        self._state            = POOFING
        self._vx = self._vy    = 0.0
        self.frame_set         = self.fs_poof_expand
        self.frame_idx         = 0

    def _start_cross_screen(self):
        """Walk with purpose to a landing zone on another monitor."""
        if len(self._monitors) < 2:
            self._start_float()
            return
        cur = self._current_monitor_idx()
        others = [i for i in range(len(self._monitors)) if i != cur]
        tgt_idx = random.choice(others)
        mx, my, mw, mh = self._monitors[tgt_idx]
        self._cross_target_x = random.uniform(mx + mw * 0.15, mx + mw * 0.85)
        self._cross_target_y = random.uniform(self.sh * 0.62, self.sh * 0.80)
        self._vx = 1.0 if self._cross_target_x > self.x else -1.0
        self._vy = 0.0
        self._vz = 0.0
        self._facing_right = self._vx > 0
        self._state     = CROSSING
        self._state_end = time.monotonic() + 55.0   # safety cap
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_traverse(self):
        """Full-length dash from whichever side he's on to the far opposite edge,
        across every monitor."""
        m = self._margin
        going_right = (self.x + self._disp_w * 0.5) < self.sw * 0.5
        self._trav_target_x = (self.sw - m) if going_right else m
        self._trav_y = self.y
        self._vx = 1.0 if going_right else -1.0
        self._vy = 0.0
        self._vz = 0.0
        self._facing_right = going_right
        self._state     = TRAVERSE
        self._state_end = time.monotonic() + 40.0
        self.frame_idx  = 0
        self._reset_trail_pos()
        if random.random() < 0.6:
            self.say("traverse")

    def _start_edge_patrol(self):
        """Lap the screen perimeter, corner to corner."""
        m = self._margin
        self._corners = [(m, m), (self.sw - m, m),
                         (self.sw - m, self.sh - m), (m, self.sh - m)]
        cx = self.x + self._disp_w * 0.5
        cy = self.y + self._disp_h * 0.5
        nearest = min(range(4), key=lambda i: _math.hypot(
            self._corners[i][0] - cx, self._corners[i][1] - cy))
        self._corner_goal  = (nearest + 1) % 4   # head to the next corner
        self._patrol_legs  = random.randint(4, 7)
        self._vx = self._vy = self._vz = 0.0
        self._state     = EDGE_PATROL
        self._state_end = time.monotonic() + 60.0
        self.frame_idx  = 0
        self._reset_trail_pos()
        if random.random() < 0.5:
            self.say("patrol")

    def _start_dvd(self):
        """Classic DVD-logo bounce — diagonal, ricochets off every wall, and if it
        ever nails a corner, celebrate like it's the moon landing."""
        ang = random.uniform(0.5, 1.07)            # avoid near-flat angles
        self._vx = random.choice([-1, 1]) * _math.cos(ang)
        self._vy = random.choice([-1, 1]) * _math.sin(ang)
        self._vz = 0.0
        self._dvd_corners = 0
        self._facing_right = self._vx >= 0
        self._state     = DVD
        self._state_end = time.monotonic() + random.uniform(14.0, 24.0)
        self.frame_idx  = 0
        self._reset_trail_pos()
        if random.random() < 0.7:
            self.say("dvd")

    # ── input ─────────────────────────────────────────────────────────────────

    def _on_press(self, widget, ev):
        self._press_x = ev.x_root
        self._press_y = ev.y_root
        self._did_drag = False
        # any touch wakes him — remember whether he was actually asleep
        self._press_was_sleeping = (self._state == SLEEPING
                                    or self.frame_set is self.fs_sleep)
        self._wake()

    def _on_motion(self, widget, ev):
        if not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return
        if not self._did_drag:
            if abs(ev.x_root - self._press_x) > 5 or abs(ev.y_root - self._press_y) > 5:
                self._did_drag = True
                self._state    = DRAGGED
                self._vx = self._vy = 0.0
                self.frame_set = self.fs_grab
                self.frame_idx = 0
                self._drag_samples.clear()
                self._drag_say()
                # hand drag to WM — works on X11 and Wayland, no move() needed
                self.get_window().begin_move_drag(
                    1, int(ev.x_root), int(ev.y_root), ev.time
                )

    def _on_configure(self, widget, ev):
        """Fires whenever the WM moves/resizes the window — used to track drag position."""
        if self._state != DRAGGED:
            return False
        self.x = float(ev.x)
        self.y = float(ev.y)
        now = time.monotonic()
        self._drag_samples.append((now, self.x, self.y))
        if len(self._drag_samples) > 6:
            self._drag_samples.pop(0)
        self._trail._overlay.add(int(self.x) + SPR_W // 2, int(self.y) + SPR_H // 2,
                                 TrailOverlay.KIND_GLOW)
        self._bubble.follow(int(self.x), int(self.y))
        return False

    def _on_release(self, widget, ev):
        if ev.button == 3:
            self._show_menu(ev)
            return
        if ev.button != 1:
            return
        self._last_user_action = time.monotonic()
        if self._did_drag:
            # sync position from actual window location after WM drag
            wx, wy = self.get_position()
            self.x, self.y = float(wx), float(wy)
            self._try_throw()
        else:
            # click: stop and open chat (with a quip)
            self._vx = self._vy = 0.0
            self._state     = FLOATING
            self._state_end = time.monotonic() + 999
            self.frame_set  = self._float_set()
            self.frame_idx  = 0
            self.say("wake_idle" if self._press_was_sleeping else "click", force=True)
            self._open_chat()

    def _wake(self, reason="poke"):
        """Any interaction snaps Ginie awake from a nap, with attitude."""
        self._last_user_action = time.monotonic()
        if self._state == SLEEPING or self.frame_set is self.fs_sleep:
            self._vx = self._vy = self._vz = 0.0
            self._state     = FLOATING
            self._state_end = time.monotonic() + 4.0
            self.frame_set  = self._float_set()
            self.frame_idx  = 0
            # the drag handler will deliver its own line; only speak here for a poke
            if reason != "drag":
                self.say("wake_drag" if self._drag_count > 0 else "wake_idle",
                         force=True)

    def _drag_say(self):
        """Escalating sass the more often the user grabs him."""
        self._drag_count += 1
        if self._press_was_sleeping:
            self.say("wake_drag", force=True)
        elif self._drag_count <= 2:
            self.say("drag", force=True)
        elif self._drag_count <= 5:
            self.say("drag_again", force=True)
        else:
            self.say("drag_lots", force=True)

    def _try_throw(self):
        """Compute drag velocity from samples; if fast enough enter THROWN, else float."""
        self.z   = Z_NEUTRAL   # snap z — dragging doesn't change depth
        self._vz = 0.0
        self._drag_samples = [s for s in self._drag_samples
                              if time.monotonic() - s[0] < 0.15]
        if len(self._drag_samples) >= 2:
            t1, x1, y1 = self._drag_samples[0]
            t2, x2, y2 = self._drag_samples[-1]
            dt = max(t2 - t1, 0.001)
            vx = (x2 - x1) / dt
            vy = (y2 - y1) / dt
            speed = _math.hypot(vx, vy)
            if speed > 80:
                self._throw_vx    = vx / speed
                self._throw_vy    = vy / speed
                self._throw_speed = min(speed * 0.5, 500)
                self._facing_right = self._throw_vx >= 0
                self._state       = THROWN
                self.frame_set    = (self.fs_whee_r if self._facing_right
                                     else self.fs_whee_l)
                self.frame_idx    = 0
                self._drag_samples.clear()
                self.say("throw", force=True)
                return
        self._drag_samples.clear()
        self._start_float()

    def _show_menu(self, ev):
        self._wake()
        menu = Gtk.Menu()
        items = [
            ("Mit Ginie reden",  lambda *_: self._open_chat()),
            ("Erkunden",         lambda *_: self._start_explore()),
            ("Quer rueber",      lambda *_: self._start_traverse()),
            ("Rand-Patrouille",  lambda *_: self._start_edge_patrol()),
            ("DVD-Modus",        lambda *_: self._start_dvd()),
            ("Teleportieren",    lambda *_: (setattr(self, '_vz', 0.0), self._start_poof())),
            ("Laufen lassen",    lambda *_: self._start_walk()),
            ("Schweben lassen",  lambda *_: self._start_float()),
            ("Ruhe geben",       lambda *_: self._park()),
        ]
        if len(self._folders.entries) >= 2:
            items.insert(2, ("In Ordner tauchen", lambda *_: self._start_dive()))
        for label, fn in items:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", fn)
            menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        quit_it = Gtk.MenuItem(label="Beenden")
        quit_it.connect("activate", lambda *_: (self._trail.hide_all(), Gtk.main_quit()))
        menu.append(quit_it)
        menu.show_all()
        menu.popup(None, None, None, None, ev.button, ev.time)

    def _park(self):
        """Stop everything — genie floats in place."""
        self._vx = self._vy = 0.0
        self._state     = FLOATING
        self._state_end = time.monotonic() + 120
        self.frame_set  = self.fs_float_r
        self.frame_idx  = 0

    def _open_chat(self):
        if self._chat is None:
            self._chat = ChatWindow(self)
        self._chat.show_all()
        self._chat.present()

    # ── bubble ────────────────────────────────────────────────────────────────

    def show_bubble(self, text, ms=7000):
        self._bubble.show_text(text, ms)

    def _greet(self):
        h = time.localtime().tm_hour
        if   5 <= h < 11:  event = "greet_morning"
        elif 18 <= h <= 23: event = "greet_evening"
        else:              event = "greet"
        self.say(event, force=True, ms=5000)
        return False

# ---------------------------------------------------------------------------
# Bubble — anchored to top-left corner of pet, never clips
# ---------------------------------------------------------------------------

_BUBBLE_TAIL = 10   # height of the speech-bubble downward tail

class BubbleWindow(Gtk.Window):
    def __init__(self, pet):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
        self.set_resizable(False)
        self.set_can_focus(False)
        self.pet = pet
        self._hide_id = None

        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.connect("draw", self._on_draw)
        # CLICK-THROUGH: an empty input region means every pointer event passes
        # straight through to whatever is underneath (your terminal), so the bubble
        # can never steal your clicks or keyboard focus. Re-applied on every map.
        self.connect("realize", self._make_click_through)
        self.connect("map",     self._make_click_through)

        # extra bottom padding = tail height so text sits inside the rounded rect
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_bottom(_BUBBLE_TAIL)
        self.add(box)

        self.lbl = Gtk.Label(label="")
        self.lbl.set_line_wrap(True)
        self.lbl.set_max_width_chars(26)
        self.lbl.set_margin_top(10)
        self.lbl.set_margin_bottom(10)
        self.lbl.set_margin_start(14)
        self.lbl.set_margin_end(14)
        self.lbl.get_style_context().add_class("bubble-text")
        box.pack_start(self.lbl, True, True, 0)

    def _make_click_through(self, *_):
        win = self.get_window()
        if win is not None:
            win.input_shape_combine_region(cairo.Region(), 0, 0)

    def _on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        w  = widget.get_allocated_width()
        h  = widget.get_allocated_height()
        r  = 10
        bh = h - _BUBBLE_TAIL   # height of rounded-rect portion
        PI = _math.pi

        cr.set_source_rgba(0.118, 0.118, 0.18, 0.95)

        # rounded rect
        cr.arc(r,     r,     r, PI,       1.5*PI)
        cr.arc(w-r,   r,     r, 1.5*PI,  0)
        cr.arc(w-r,   bh-r,  r, 0,       0.5*PI)
        # tail: downward triangle centered at bottom of rounded rect
        tx = w // 2
        cr.line_to(tx + 9, bh)
        cr.line_to(tx,     h)
        cr.line_to(tx - 9, bh)
        cr.arc(r,     bh-r,  r, 0.5*PI,  PI)
        cr.close_path()
        cr.fill()
        return False

    def show_text(self, text, ms=7000):
        self.lbl.set_text(text)
        self.show_all()
        # place once now (allocation may be 0 on first show — _tick keeps it glued)
        GLib.idle_add(lambda: (self.place(self.pet.x, self.pet.y,
                                          self.pet._disp_w, self.pet._disp_h), False)[1])
        if self._hide_id:
            GLib.source_remove(self._hide_id)
        self._hide_id = GLib.timeout_add(ms, self._auto_hide)

    def follow(self, px, py):
        """Back-compat shim — real tracking happens synchronously in _tick.place()."""
        if self.get_visible():
            self.place(self.pet.x, self.pet.y, self.pet._disp_w, self.pet._disp_h)

    def place(self, px, py, disp_w, disp_h):
        """Synchronously glue the bubble above the genie's head, on-screen."""
        h = self.get_allocated_height()
        w = max(self.get_allocated_width(), 180)
        if h < 20:
            h = 64   # not allocated yet — estimate; corrected next frame
        px, py = int(px), int(py)
        sw = getattr(self.pet, 'sw', None) or virtual_desktop_size()[0]

        genie_cx = px + disp_w // 2
        bx = genie_cx - w // 2
        # tail points ~8% down from the window top = the hat/head, never the belly
        by = py - h + int(disp_h * 0.08)

        bx = max(6, min(bx, sw - w - 6))
        if by < 6:                       # too near the top edge — flip below him
            by = py + disp_h + 6
        self.move(bx, by)

    def _auto_hide(self):
        self.hide()
        self._hide_id = None
        return False

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _check_single_instance()
    apply_css()
    threading.Thread(target=ensure_ollama, daemon=True).start()
    pet = PetWindow()
    Gtk.main()
