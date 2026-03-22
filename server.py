#!/usr/bin/env python3
"""
LifeBridge — Autonomous Agent Operating System
Master agent orchestration server.
"""

import os
import sys
import json
from pathlib import Path

from flask import Flask, request, jsonify, Response

import anthropic

# ── Config ───────────────────────────────────────────────────────────────────

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    print("FATAL: ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)

MODEL = "claude-sonnet-4-20250514"
ROOT = Path(__file__).parent
SYSTEM_PROMPT = (ROOT / "system-prompt.txt").read_text()
REGISTRY_PATH = ROOT / "registry.json"

client = anthropic.Anthropic(api_key=API_KEY)
app = Flask(__name__)

# ── Registry ─────────────────────────────────────────────────────────────────

def load_registry():
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {"agents": [], "domain_signals": [], "pending_builds": [], "connectors": [], "claude_capabilities": []}

def save_registry(data):
    REGISTRY_PATH.write_text(json.dumps(data, indent=2))

# ── Master agent ─────────────────────────────────────────────────────────────

def route_request(user_input):
    registry = load_registry()

    registry_block = f"""[REGISTRY STATE]
Agents: {json.dumps(registry.get('agents', []))}
Connectors: {json.dumps(registry.get('connectors', []))}
Claude-native capabilities: {json.dumps(registry.get('claude_capabilities', []))}
Domain signals learned: {json.dumps(registry.get('domain_signals', []))}
Pending builds: {json.dumps(registry.get('pending_builds', []))}
[END REGISTRY STATE]"""

    messages = [{
        "role": "user",
        "content": f"""{registry_block}

User request: {user_input}"""
    }]

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/route", methods=["POST"])
def api_route():
    body = request.get_json(silent=True) or {}
    user_input = body.get("input", "").strip()
    if not user_input:
        return jsonify({"error": "Missing 'input' field"}), 400

    try:
        output = route_request(user_input)
        return jsonify({"input": user_input, "output": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/registry", methods=["GET"])
def api_registry():
    return jsonify(load_registry())

@app.route("/registry/update", methods=["POST"])
def api_registry_update():
    body = request.get_json(silent=True) or {}
    registry = load_registry()

    if "agent" in body:
        registry["agents"].append(body["agent"])
    if "domain_signal" in body:
        registry["domain_signals"].append(body["domain_signal"])
    if "pending_build" in body:
        registry["pending_builds"].append(body["pending_build"])
    if "connector" in body:
        registry.setdefault("connectors", []).append(body["connector"])

    save_registry(registry)
    return jsonify({"status": "updated", "registry": registry})

@app.route("/")
def index():
    return Response(HTML, content_type="text/html")

# ── Frontend ─────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LifeBridge</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');

  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0c0c10; color:#d4d4dc; font-family:'Inter',sans-serif; min-height:100vh; display:flex; }

  .sidebar {
    width:280px; background:#101016; border-right:1px solid #1c1c26;
    padding:20px 16px; overflow-y:auto; flex-shrink:0;
    display:flex; flex-direction:column;
  }
  .sidebar h2 {
    font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:0.15em;
    color:#6366f1; text-transform:uppercase; margin-bottom:16px;
  }
  .sidebar .section { margin-bottom:20px; }
  .sidebar .section-title {
    font-size:10px; letter-spacing:0.12em; color:#555; text-transform:uppercase;
    margin-bottom:8px; font-family:'JetBrains Mono',monospace;
  }
  .sidebar .empty { font-size:12px; color:#333; font-style:italic; }
  .sidebar .entry {
    background:#16161e; border:1px solid #1c1c26; border-radius:6px;
    padding:8px 10px; margin-bottom:6px; font-size:11px; color:#888;
    font-family:'JetBrains Mono',monospace; word-break:break-word;
  }
  .sidebar .entry strong { color:#d4d4dc; }

  .main { flex:1; display:flex; flex-direction:column; min-width:0; }

  .header {
    padding:20px 28px; border-bottom:1px solid #1c1c26;
    display:flex; align-items:baseline; gap:12px;
  }
  .header h1 {
    font-family:'JetBrains Mono',monospace; font-size:18px; font-weight:700;
    letter-spacing:0.12em; color:#d4d4dc;
  }
  .header .tag {
    font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:0.1em;
    color:#6366f1; background:#6366f118; padding:3px 8px; border-radius:4px;
  }

  .output-area { flex:1; overflow-y:auto; padding:24px 28px; }

  .message { margin-bottom:20px; }
  .message.user .label { color:#6366f1; }
  .message.agent .label { color:#22c55e; }
  .label {
    font-family:'JetBrains Mono',monospace; font-size:10px;
    letter-spacing:0.12em; text-transform:uppercase; margin-bottom:6px;
  }
  .message.user .body {
    color:#d4d4dc; font-size:14px; line-height:1.5; padding:12px 16px;
    background:#16161e; border-radius:8px; border:1px solid #1c1c26;
  }
  .message.agent .body {
    font-family:'JetBrains Mono',monospace; font-size:12px; line-height:1.7;
    color:#c8c8d4; white-space:pre-wrap; word-break:break-word;
    padding:16px 20px; background:#0f0f16; border-radius:8px;
    border:1px solid #1a1a24;
  }

  .input-area {
    padding:16px 28px 20px; border-top:1px solid #1c1c26; background:#101016;
    display:flex; gap:10px;
  }
  .input-area input {
    flex:1; background:#16161e; border:1px solid #1c1c26; border-radius:8px;
    color:#d4d4dc; padding:12px 16px; font-size:14px; outline:none;
    font-family:'Inter',sans-serif;
  }
  .input-area input:focus { border-color:#6366f1; }
  .input-area input::placeholder { color:#444; }
  .input-area button {
    background:#6366f1; border:none; border-radius:8px; color:#fff;
    padding:12px 24px; font-size:13px; font-weight:600; cursor:pointer;
    font-family:'JetBrains Mono',monospace; letter-spacing:0.06em;
    white-space:nowrap;
  }
  .input-area button:disabled { opacity:0.4; cursor:not-allowed; }
  .input-area button:hover:not(:disabled) { background:#5558e6; }

  .loading {
    display:inline-block; font-family:'JetBrains Mono',monospace;
    font-size:12px; color:#6366f1;
  }
  .loading::after {
    content:''; animation:dots 1.4s steps(4) infinite;
  }
  @keyframes dots {
    0% { content:''; } 25% { content:'.'; } 50% { content:'..'; } 75% { content:'...'; }
  }

  .reasoning-toggle {
    font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:0.08em;
    color:#555; cursor:pointer; margin-bottom:8px; user-select:none;
  }
  .reasoning-toggle:hover { color:#888; }
  .reasoning-block {
    font-family:'JetBrains Mono',monospace; font-size:11px; line-height:1.6;
    color:#888; white-space:pre-wrap; word-break:break-word;
    padding:12px 16px; background:#0a0a10; border-radius:6px;
    border-left:3px solid #333; margin-bottom:12px;
  }
  .reasoning-label {
    font-family:'JetBrains Mono',monospace; font-size:9px; letter-spacing:0.12em;
    color:#555; text-transform:uppercase; margin-bottom:4px;
  }

  @media(max-width:700px) {
    body { flex-direction:column; }
    .sidebar { width:100%; max-height:200px; border-right:none; border-bottom:1px solid #1c1c26; }
  }
</style>
</head>
<body>

<div class="sidebar">
  <h2>LifeBridge</h2>
  <div class="section">
    <div class="section-title">Registered Agents</div>
    <div id="agents-list"><div class="empty">No agents registered</div></div>
  </div>
  <div class="section">
    <div class="section-title">Domain Signals</div>
    <div id="signals-list"><div class="empty">No signals logged</div></div>
  </div>
  <div class="section">
    <div class="section-title">Connectors</div>
    <div id="connectors-list"><div class="empty">No connectors</div></div>
  </div>
  <div class="section">
    <div class="section-title">Pending Builds</div>
    <div id="builds-list"><div class="empty">No pending builds</div></div>
  </div>
</div>

<div class="main">
  <div class="header">
    <h1>LIFEBRIDGE</h1>
    <span class="tag">MASTER AGENT v1</span>
  </div>

  <div class="output-area" id="output"></div>

  <div class="input-area">
    <input id="input" type="text" placeholder="Enter a request for the master agent..." autocomplete="off">
    <button id="submit" onclick="send()">ROUTE</button>
  </div>
</div>

<script>
const output = document.getElementById('output');
const input = document.getElementById('input');
const btn = document.getElementById('submit');

input.addEventListener('keydown', e => { if (e.key === 'Enter' && !btn.disabled) send(); });

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  btn.disabled = true;

  // User message
  output.innerHTML += `<div class="message user"><div class="label">Input</div><div class="body">${esc(text)}</div></div>`;

  // Loading
  const loadId = 'load-' + Date.now();
  output.innerHTML += `<div class="message agent" id="${loadId}"><div class="label">Master Agent</div><div class="body"><span class="loading">Routing</span></div></div>`;
  output.scrollTop = output.scrollHeight;

  try {
    const res = await fetch('/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: text }),
    });
    const data = await res.json();
    const el = document.getElementById(loadId);
    if (data.error) {
      el.querySelector('.body').textContent = 'ERROR: ' + data.error;
    } else {
      el.querySelector('.body').innerHTML = formatResponse(data.output);
    }
  } catch (e) {
    const el = document.getElementById(loadId);
    el.querySelector('.body').textContent = 'CONNECTION ERROR: ' + e.message;
  }

  btn.disabled = false;
  output.scrollTop = output.scrollHeight;
  refreshRegistry();
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function formatResponse(raw) {
  // Split on REASONING block boundaries
  const reasoningStart = raw.indexOf('REASONING');
  if (reasoningStart === -1) return esc(raw);

  // Find the end of the reasoning block (next ────── line after the content)
  const lines = raw.split('\\n');
  let rStart = -1, rEnd = -1, dashCount = 0;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith('REASONING')) { rStart = i; dashCount = 0; continue; }
    if (rStart >= 0 && lines[i].includes('──────')) {
      dashCount++;
      if (dashCount === 1) continue; // opening line
      if (dashCount === 2) { rEnd = i; break; } // closing line
    }
  }

  if (rStart === -1 || rEnd === -1) return esc(raw);

  const before = lines.slice(0, rStart).join('\\n').trim();
  const reasoning = lines.slice(rStart, rEnd + 1).join('\\n').trim();
  const after = lines.slice(rEnd + 1).join('\\n').trim();

  const toggleId = 'reason-' + Date.now();
  let html = '';
  if (before) html += esc(before) + '\\n';
  html += `<div class="reasoning-toggle" onclick="document.getElementById('${toggleId}').style.display = document.getElementById('${toggleId}').style.display === 'none' ? 'block' : 'none'">▶ Show reasoning</div>`;
  html += `<div id="${toggleId}" style="display:none"><div class="reasoning-label">Agent reasoning</div><div class="reasoning-block">${esc(reasoning)}</div></div>`;
  if (after) html += esc(after);
  return html;
}

async function refreshRegistry() {
  try {
    const res = await fetch('/registry');
    const reg = await res.json();
    renderList('agents-list', reg.agents, a => `<strong>${a.name || a}</strong>`);
    renderList('connectors-list', reg.connectors || [], c => typeof c === 'string' ? c : `<strong>${c.name || ''}</strong> ${c.provides || ''}`);
    renderList('signals-list', reg.domain_signals, s => typeof s === 'string' ? s : JSON.stringify(s));
    renderList('builds-list', reg.pending_builds, b => typeof b === 'string' ? b : `<strong>${b.name || ''}</strong> ${b.purpose || ''}`);
  } catch {}
}

function renderList(id, items, fmt) {
  const el = document.getElementById(id);
  if (!items || items.length === 0) {
    el.innerHTML = '<div class="empty">None</div>';
    return;
  }
  el.innerHTML = items.map(i => `<div class="entry">${fmt(i)}</div>`).join('');
}

refreshRegistry();
</script>

</body>
</html>"""

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"LifeBridge starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
