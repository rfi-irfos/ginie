#!/usr/bin/env python3
import os, sys, json, threading, subprocess, time, webbrowser, urllib.parse
import urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_PATH  = os.path.dirname(os.path.abspath(__file__))
USB_ROOT   = os.path.normpath(os.path.join(BASE_PATH, ".."))
OLLAMA_URL = "http://localhost:11434"
MODEL      = "qwen2.5-coder:1.5b"
PORT       = 7891

# ---------------------------------------------------------------------------
# Ollama bootstrap
# ---------------------------------------------------------------------------

def ensure_ollama():
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1)
        print("ollama already running.")
        return
    except Exception:
        pass

    portable = os.path.join(BASE_PATH, "..", "ollama_portable", "ollama")
    portable = os.path.normpath(portable)
    if os.path.exists(portable):
        models_dir = os.path.normpath(os.path.join(BASE_PATH, "..", "ollama_portable", "models"))
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = models_dir
        print(f"starting portable ollama from {portable}")
        subprocess.Popen([portable, "serve"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("starting system ollama")
        try:
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            print("ollama not found — chat will show an error")
    time.sleep(2)

# ---------------------------------------------------------------------------
# HTML (single-file frontend — no external files needed)
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ginie</title>
<style>
  :root {
    --bg:      #0f0f11;
    --surface: #18181c;
    --border:  #2a2a32;
    --accent:  #6c8ef5;
    --text:    #e8e8f0;
    --sub:     #9090a8;
    --green:   #4caf82;
    --red:     #e05c5c;
    --radius:  10px;
    --font:    'Segoe UI', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font);
         display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

  /* header */
  header { display: flex; align-items: center; gap: 10px;
           padding: 14px 20px; border-bottom: 1px solid var(--border);
           background: var(--surface); flex-shrink: 0; }
  header h1 { font-size: 1.1rem; font-weight: 600; letter-spacing: .04em; }
  #status-dot { width: 9px; height: 9px; border-radius: 50%;
                background: var(--sub); flex-shrink: 0; transition: background .3s; }
  #status-dot.online  { background: var(--green); box-shadow: 0 0 6px var(--green); }
  #status-dot.offline { background: var(--red); }
  #model-label { margin-left: auto; font-size: .75rem; color: var(--sub);
                 background: var(--border); padding: 3px 9px; border-radius: 20px; }

  /* tabs */
  nav { display: flex; border-bottom: 1px solid var(--border);
        background: var(--surface); flex-shrink: 0; }
  nav button { flex: 1; padding: 10px; background: none; border: none;
               color: var(--sub); font-size: .85rem; cursor: pointer; transition: color .2s; }
  nav button.active { color: var(--accent); border-bottom: 2px solid var(--accent); }
  nav button:hover  { color: var(--text); }

  /* panes */
  .pane { display: none; flex: 1; overflow: hidden; flex-direction: column; }
  .pane.active { display: flex; }

  /* chat */
  #chat-log { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex;
              flex-direction: column; gap: 12px; }
  .msg { max-width: 72%; padding: 10px 14px; border-radius: var(--radius);
         line-height: 1.55; font-size: .9rem; white-space: pre-wrap; word-break: break-word; }
  .msg.user  { align-self: flex-end; background: var(--accent); color: #fff;
               border-bottom-right-radius: 3px; }
  .msg.ginie { align-self: flex-start; background: var(--surface);
               border: 1px solid var(--border); border-bottom-left-radius: 3px; }
  .msg.sys   { align-self: center; background: none; color: var(--sub);
               font-size: .78rem; text-align: center; padding: 2px 0; }
  .typing::after { content: '...'; animation: blink 1s infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.2} }

  /* input bar */
  #input-bar { display: flex; gap: 8px; padding: 12px 16px;
               border-top: 1px solid var(--border); background: var(--surface); flex-shrink: 0; }
  #user-input { flex: 1; background: var(--bg); border: 1px solid var(--border);
                border-radius: var(--radius); padding: 10px 14px; color: var(--text);
                font-size: .9rem; resize: none; outline: none; font-family: var(--font); }
  #user-input:focus { border-color: var(--accent); }
  .btn { padding: 10px 16px; border: none; border-radius: var(--radius); cursor: pointer;
         font-size: .85rem; font-weight: 500; transition: opacity .2s; }
  .btn:hover { opacity: .85; }
  #send-btn  { background: var(--accent); color: #fff; }
  #voice-btn { background: var(--border); color: var(--text); min-width: 44px; }
  #voice-btn.recording { background: var(--red); color: #fff; }

  /* search */
  #search-pane { padding: 20px; gap: 12px; }
  #search-row  { display: flex; gap: 8px; }
  #search-input { flex: 1; background: var(--bg); border: 1px solid var(--border);
                  border-radius: var(--radius); padding: 10px 14px; color: var(--text);
                  font-size: .9rem; outline: none; font-family: var(--font); }
  #search-input:focus { border-color: var(--accent); }
  #results { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
  .result-item { background: var(--surface); border: 1px solid var(--border);
                 border-radius: var(--radius); padding: 10px 14px; font-size: .82rem;
                 color: var(--sub); cursor: pointer; word-break: break-all;
                 transition: border-color .2s; }
  .result-item:hover { border-color: var(--accent); color: var(--text); }
  .result-count { font-size: .78rem; color: var(--sub); }

  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
</style>
</head>
<body>

<header>
  <div id="status-dot"></div>
  <h1>Ginie</h1>
  <span id="model-label">""" + MODEL + r"""</span>
</header>

<nav>
  <button class="active" onclick="switchTab('chat',this)">Chat</button>
  <button onclick="switchTab('search',this)">File Search</button>
</nav>

<div id="chat-pane" class="pane active">
  <div id="chat-log"></div>
  <div id="input-bar">
    <textarea id="user-input" rows="1" placeholder="Ask Ginie anything..."></textarea>
    <button class="btn" id="voice-btn" title="Voice input" onclick="toggleVoice()">mic</button>
    <button class="btn" id="send-btn" onclick="sendMessage()">Send</button>
  </div>
</div>

<div id="search-pane" class="pane">
  <div id="search-row">
    <input id="search-input" placeholder="Search files on this USB stick..." onkeydown="if(event.key==='Enter')doSearch()">
    <button class="btn" id="send-btn" onclick="doSearch()">Search</button>
  </div>
  <div class="result-count" id="result-count"></div>
  <div id="results"></div>
</div>

<script>
const log = document.getElementById('chat-log');
const inp = document.getElementById('user-input');

function switchTab(name, btn) {
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(name + '-pane').classList.add('active');
  btn.classList.add('active');
}

function addMsg(cls, text) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

function addTyping() {
  const d = document.createElement('div');
  d.className = 'msg ginie typing';
  d.textContent = 'Ginie is thinking';
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

async function sendMessage() {
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  inp.style.height = 'auto';
  addMsg('user', text);
  const t = addTyping();
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: text})
    });
    const data = await res.json();
    t.remove();
    addMsg('ginie', data.response || data.error || 'No response.');
  } catch(e) {
    t.remove();
    addMsg('sys', 'Connection error: ' + e.message);
  }
}

inp.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  setTimeout(() => { inp.style.height='auto'; inp.style.height=inp.scrollHeight+'px'; }, 0);
});

// voice
let recognition = null;
const voiceBtn = document.getElementById('voice-btn');

function toggleVoice() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    addMsg('sys', 'Voice not supported in this browser. Try Chromium.');
    return;
  }
  if (recognition) { recognition.stop(); return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = 'de-DE';
  recognition.interimResults = false;
  recognition.onstart = () => voiceBtn.classList.add('recording');
  recognition.onresult = e => {
    inp.value = e.results[0][0].transcript;
    sendMessage();
  };
  recognition.onend = () => { voiceBtn.classList.remove('recording'); recognition = null; };
  recognition.onerror = e => {
    voiceBtn.classList.remove('recording');
    recognition = null;
    addMsg('sys', 'Voice error: ' + e.error);
  };
  recognition.start();
}

// file search
async function doSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  document.getElementById('result-count').textContent = 'Searching...';
  document.getElementById('results').innerHTML = '';
  const res = await fetch('/search?q=' + encodeURIComponent(q));
  const data = await res.json();
  document.getElementById('result-count').textContent =
    data.results.length ? data.results.length + ' result(s)' : 'Nothing found.';
  data.results.forEach(p => {
    const d = document.createElement('div');
    d.className = 'result-item';
    d.textContent = p;
    d.onclick = () => fetch('/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: p})});
    document.getElementById('results').appendChild(d);
  });
}

// status check
async function checkStatus() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    const dot = document.getElementById('status-dot');
    dot.className = d.online ? 'online' : 'offline';
  } catch(e) {}
}
checkStatus();
setInterval(checkStatus, 5000);

addMsg('sys', 'Ginie ready. Say hey or type something.');
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def ollama_chat(prompt):
    data = json.dumps({"model": MODEL, "prompt": prompt, "stream": False}).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("response", "No response.")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (f"Model '{MODEL}' not found in the running Ollama instance. "
                    f"If a system Ollama was already running before you plugged in this USB, "
                    f"stop it first (`pkill ollama`) and relaunch Ginie so the portable model loads.")
        return f"Ollama HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"Cannot reach Ollama: {e.reason}. Is it still starting up?"
    except Exception as e:
        return f"Error: {e}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access log

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/status":
            try:
                urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1)
                self.send_json(200, {"online": True})
            except Exception:
                self.send_json(200, {"online": False})

        elif parsed.path == "/search":
            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0].lower()
            results = []
            if q:
                for root, dirs, files in os.walk(USB_ROOT):
                    for f in files:
                        if q in f.lower():
                            results.append(os.path.join(root, f))
            self.send_json(200, {"results": results[:200]})

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/chat":
            prompt   = body.get("prompt", "")
            response = ollama_chat(prompt)
            self.send_json(200, {"response": response})

        elif self.path == "/open":
            path = body.get("path", "")
            if os.path.exists(path):
                subprocess.Popen(["xdg-open", path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "not found"})

        else:
            self.send_response(404); self.end_headers()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def open_browser():
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:{PORT}")

if __name__ == "__main__":
    ensure_ollama()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"ginie running at http://localhost:{PORT}")
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nginie stopped.")
