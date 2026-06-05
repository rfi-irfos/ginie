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

import os, sys, json, threading, subprocess, time, random, glob, io, re
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
        if os.path.isdir(usb_models):
            env["OLLAMA_MODELS"] = usb_models
            _set_startup_status("starting system ollama with USB models...")
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

    _set_startup_status("model ready")
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
        yield ("response", "model not found on this machine." if e.code == 404
                           else f"ollama error {e.code}")
    except Exception as e:
        yield ("response", f"offline — {_startup_status}\n(log: /tmp/ginie_ol.log)")

# ---------------------------------------------------------------------------
# Frame loader
# ---------------------------------------------------------------------------

SPR_W, SPR_H = 90, 120    # display size (matches 120:160 canvas ratio)

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

FLOATING = "floating"    # hovering drift — default mode
WALKING  = "walking"     # legs out, walking along screen bottom area
POOFING  = "poofing"     # teleport sequence
GHOSTING = "ghosting"    # invisible walk — only footsteps visible, poof re-appear
DRAGGED  = "dragged"     # user is dragging
THROWN   = "thrown"      # released from drag with velocity — momentum + bounce

import math as _math

FLOAT_SPEED         = 55.0   # px/sec while drifting
WALK_SPEED          = 75.0   # px/sec while walking
FLOAT_SECS          = (6, 12)
WALK_SECS           = (6, 12)
INACTIVITY_WANDER_S = 20

ANIM_FLOAT_MS = 110   # float cycle
ANIM_WALK_MS  =  85   # walk cycle
ANIM_POOF_MS  =  65   # poof frames

# Drift directions — mostly horizontal, some diagonal, rarely vertical
_FLOAT_DIRS = [
    ( 1.0,  0.0), (-1.0,  0.0),
    ( 1.0,  0.0), (-1.0,  0.0),   # double-weight horizontal
    ( 0.92,  0.30), (-0.92,  0.30),
    ( 0.92, -0.30), (-0.92, -0.30),
    ( 0.70,  0.70), (-0.70,  0.70),
]
_WALK_DIRS  = [( 1.0, 0.0), (-1.0, 0.0),
               ( 1.0, 0.0), (-1.0, 0.0),   # mostly horizontal walk
               ( 0.92, 0.20), (-0.92, 0.20)]

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
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor:
            geo = monitor.get_geometry()
            sw, sh = geo.width, geo.height
        else:
            sw, sh = screen.get_width(), screen.get_height()
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
        self.fs_float_r     = load_set("float",        flip=False)
        self.fs_float_l     = load_set("float",        flip=True)
        self.fs_walk_r      = load_set("walk",         flip=False)
        self.fs_walk_l      = load_set("walk",         flip=True)
        self.fs_poof_expand = load_set("poof_expand",  flip=False)
        self.fs_poof_shrink = load_set("poof_shrink",  flip=False)
        self.fs_grab        = load_set("float",        flip=False, tilt=18)

        if not self.fs_float_r:
            raise RuntimeError(f"no float frames found in {FRAMES_DIR}")

        self.frame_set = self.fs_float_r
        self.frame_idx = 0
        self.current   = self.fs_float_r[0]

        # screen bounds — use full virtual desktop so Ginie roams across all monitors
        screen = Gdk.Screen.get_default()
        self.sw = screen.get_width()
        self.sh = screen.get_height()

        self._margin = 90
        self.x = float(self.sw // 2)
        self.y = float(self.sh // 2)    # start mid-screen — genie floats anywhere

        # velocity
        self._vx = 0.0
        self._vy = 0.0
        self._facing_right = True

        # sinusoidal float bobbing
        self._bob_phase = 0.0

        # poof / ghost teleport target
        self._poof_target_x   = 0.0
        self._poof_target_y   = 0.0
        self._ghost_after_poof = False   # if True: go invisible after expand

        # state — spawn with a poof-in, then immediately start moving
        self._state            = POOFING
        self._poof_step        = 1   # start on shrink (appear from nothing)
        self._ghost_after_poof = False
        self._state_end        = time.monotonic()
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
        self._press_wx     = 0.0
        self._press_wy     = 0.0
        self._did_drag     = False
        self._drag_samples = []   # (time, x, y) ring for velocity estimation
        self._throw_vx     = 0.0
        self._throw_vy     = 0.0
        self._throw_speed  = 0.0

        self._chat   = None
        self._bubble = BubbleWindow(self)
        self._trail  = TrailManager()

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
            Gdk.cairo_set_source_pixbuf(cr, self.current, 0, 0)
            cr.paint()
        return False

    # ── 60fps tick ────────────────────────────────────────────────────────────

    def _tick(self):
        now = time.monotonic()
        dt  = min(now - self._last_t, 0.05)
        self._last_t = now

        if self._state != DRAGGED:
            self._update_state(now, dt)

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
                if self._state == WALKING and new_idx in (0, 3):
                    flip = (new_idx == 3)
                    foot_y = self.y + SPR_H - 14
                    offset = -10 if not flip else 10
                    self._trail.drop_at(self.x + offset, foot_y, flip)
                self.frame_idx = new_idx
                self.current   = self.frame_set[new_idx]
                self.queue_draw()
            self._anim_t = now

        return True

    # ── state machine ─────────────────────────────────────────────────────────

    def _update_state(self, now, dt):

        if self._state == FLOATING:
            self._anim_ms = ANIM_FLOAT_MS
            fs = self.fs_float_r if self._facing_right else self.fs_float_l
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
                # back to floating after walk
                self._start_float()

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
            fs = self.fs_float_r if self._throw_vx >= 0 else self.fs_float_l
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

        # inactivity: if parked as floating with no velocity, nudge after timeout
        user_away = (now - self._last_user_action) > INACTIVITY_WANDER_S
        if user_away and self._state == FLOATING and self._vx == 0 and self._vy == 0:
            self._pick_next_move(now)

    def _clamp(self, nx, ny):
        m = self._margin
        nx = max(m, min(nx, self.sw - m))
        ny = max(m, min(ny, self.sh - m))
        return nx, ny

    def _pick_next_move(self, now):
        """Decide what to do next: walk, float, poof, or ghost walk."""
        roll = random.random()
        if roll < 0.40:
            self._start_walk()
        elif roll < 0.65:
            self._start_float()
        elif roll < 0.85:
            self._start_poof()
        else:
            self._start_ghost()

    def _reset_trail_pos(self):
        """Sync trail baseline to current position — prevents large delta spikes."""
        self._prev_tx = self.x
        self._prev_ty = self.y

    def _start_float(self):
        vx, vy = random.choice(_FLOAT_DIRS)
        self._vx = vx
        self._vy = vy
        self._facing_right = vx >= 0
        self._state     = FLOATING
        self._state_end = time.monotonic() + random.uniform(*FLOAT_SECS)
        self.frame_idx  = 0
        self._reset_trail_pos()

    def _start_walk(self):
        vx, vy = random.choice(_WALK_DIRS)
        self._vx = vx
        self._vy = vy
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

    # ── input ─────────────────────────────────────────────────────────────────

    def _on_press(self, widget, ev):
        self._last_user_action = time.monotonic()
        self._press_x = ev.x_root
        self._press_y = ev.y_root
        self._press_wx, self._press_wy = self.get_position()  # window pos at moment of click
        self._did_drag = False
        if ev.button == 3:
            self._show_menu(ev)

    def _on_motion(self, widget, ev):
        if not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return
        if abs(ev.x_root - self._press_x) > 5 or abs(ev.y_root - self._press_y) > 5:
            self._did_drag = True
        if self._did_drag:
            self._state    = DRAGGED
            self._vx = self._vy = 0.0
            self.frame_set = self.fs_grab
            # delta drag: coordinate-space agnostic — works on any monitor
            self.x = self._press_wx + (ev.x_root - self._press_x)
            self.y = self._press_wy + (ev.y_root - self._press_y)
            ix, iy = int(self.x), int(self.y)
            self.move(ix, iy)
            self._bubble.follow(ix, iy)
            # track velocity for throw physics
            now = time.monotonic()
            self._drag_samples.append((now, self.x, self.y))
            if len(self._drag_samples) > 6:
                self._drag_samples.pop(0)
            # glow trail while dragging
            self._trail._overlay.add(ix + SPR_W // 2, iy + SPR_H // 2,
                                     TrailOverlay.KIND_GLOW)

    def _on_release(self, widget, ev):
        if ev.button != 1:
            return
        self._last_user_action = time.monotonic()
        if self._did_drag:
            self._try_throw()
        else:
            # click: stop and open chat
            self._vx = self._vy = 0.0
            self._state     = FLOATING
            self._state_end = time.monotonic() + 999
            self.frame_set  = self.fs_float_r if self._facing_right else self.fs_float_l
            self.frame_idx  = 0
            self._open_chat()

    def _try_throw(self):
        """Compute drag velocity from samples; if fast enough enter THROWN, else float."""
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
                self.frame_set    = (self.fs_float_r if self._facing_right
                                     else self.fs_float_l)
                self.frame_idx    = 0
                self._drag_samples.clear()
                return
        self._drag_samples.clear()
        self._start_float()

    def _show_menu(self, ev):
        menu = Gtk.Menu()
        for label, fn in [
            ("Mit Ginie reden",  lambda *_: self._open_chat()),
            ("Teleportieren",    lambda *_: self._start_poof()),
            ("Laufen lassen",    lambda *_: self._start_walk()),
            ("Schweben lassen",  lambda *_: self._start_float()),
            ("Ruhe geben",       lambda *_: self._park()),
        ]:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", fn)
            menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        quit_it = Gtk.MenuItem(label="Beenden")
        quit_it.connect("activate", lambda *_: (self._trail.hide_all(), Gtk.main_quit()))
        menu.append(quit_it)
        menu.show_all()
        menu.popup_at_pointer(ev)

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
        self.show_bubble(random.choice([
            "Merhaba! Klick mich an.",
            "Ginie ist da. Offline und bereit.",
            "Hey! Was kann ich fuer dich tun?",
        ]))
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

        # extra bottom padding = tail height so text sits inside the rounded rect
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_bottom(_BUBBLE_TAIL)
        self.add(box)

        self.lbl = Gtk.Label(label="")
        self.lbl.set_line_wrap(True)
        self.lbl.set_max_width_chars(26)
        self.lbl.set_margin_top(10)
        self.lbl.set_margin_bottom(6)
        self.lbl.set_margin_start(14)
        self.lbl.set_margin_end(14)
        self.lbl.get_style_context().add_class("bubble-text")
        box.pack_start(self.lbl, True, True, 0)

        close_box = Gtk.EventBox()
        close_lbl = Gtk.Label(label="x")
        close_lbl.get_style_context().add_class("status-offline")
        close_lbl.set_margin_end(10)
        close_lbl.set_margin_bottom(4)
        close_lbl.set_halign(Gtk.Align.END)
        close_box.add(close_lbl)
        close_box.connect("button-press-event", lambda *_: self.hide())
        box.pack_start(close_box, False, False, 0)

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
        GLib.idle_add(self._do_reposition, int(self.pet.x), int(self.pet.y))
        if self._hide_id:
            GLib.source_remove(self._hide_id)
        self._hide_id = GLib.timeout_add(ms, self._auto_hide)

    def follow(self, px, py):
        if not self.get_visible():
            return
        GLib.idle_add(self._do_reposition, px, py)

    def _do_reposition(self, px, py):
        # Use natural size — never resize(1,1) which races layout and clips the tail
        _, nat = self.get_preferred_size()
        w = max(nat.width,  180)
        h = max(nat.height, 60)

        sw = Gdk.Screen.get_default().get_width()

        # center bubble horizontally over the genie sprite
        genie_cx = px + SPR_W // 2
        bx = genie_cx - w // 2

        # tail tip sits just above the hat (hat tip ~top of sprite window + small gap)
        by = py - h - 8

        # clamp to screen
        bx = max(6, min(bx, sw - w - 6))

        # if no room above, flip below the genie
        if by < 6:
            by = py + SPR_H + 6

        self.move(bx, by)
        return False

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
