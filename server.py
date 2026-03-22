#!/usr/bin/env python3
"""
LifeBridge — Autonomous Agent Operating System
Master agent orchestration server.
"""

import os
import sys
import json
import uuid
import re
import threading
import time
from datetime import datetime
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
REQUEST_LOG_PATH = ROOT / "request-log.json"

client = anthropic.Anthropic(api_key=API_KEY)
app = Flask(__name__)

# ── Request logging ──────────────────────────────────────────────────────────

def _load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return []

def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def _parse_routing_field(text, field):
    """Extract a field value from routing package text."""
    match = re.search(rf'{field}:\s*(.+)', text)
    return match.group(1).strip() if match else ""

def log_request(user_input, response_text):
    """Append a request entry to request-log.json."""
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "input": user_input,
        "domain": _parse_routing_field(response_text, "Domain"),
        "routed_to": _parse_routing_field(response_text, "Route to"),
        "approval_required": "APPROVAL REQUIRED" in response_text,
        "clarification_asked": "?" in response_text and "ROUTING PACKAGE" not in response_text,
        "build_brief_triggered": "BUILD BRIEF" in response_text,
        "raw_response": response_text,
    }
    log = _load_json(REQUEST_LOG_PATH)
    log.append(entry)
    _save_json(REQUEST_LOG_PATH, log)

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
        log_request(user_input, output)
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

# ── Improvement endpoints ────────────────────────────────────────────────────

@app.route("/improve/run", methods=["POST"])
def api_improve_run():
    try:
        from improvement_agent import run_improvement_cycle
        proposal = run_improvement_cycle(API_KEY)
        return jsonify(proposal)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/improve/approve", methods=["POST"])
def api_improve_approve():
    body = request.get_json(silent=True) or {}
    pid = body.get("proposal_id", "")
    cidx = body.get("change_index")
    if not pid or cidx is None:
        return jsonify({"error": "proposal_id and change_index required"}), 400
    try:
        from improvement_agent import apply_change
        desc = apply_change(pid, int(cidx))
        # Reload system prompt in case it was edited
        global SYSTEM_PROMPT
        SYSTEM_PROMPT = (ROOT / "system-prompt.txt").read_text()
        return jsonify({"success": True, "change_applied": desc})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/improve/reject", methods=["POST"])
def api_improve_reject():
    body = request.get_json(silent=True) or {}
    pid = body.get("proposal_id", "")
    cidx = body.get("change_index")
    if not pid or cidx is None:
        return jsonify({"error": "proposal_id and change_index required"}), 400
    try:
        from improvement_agent import reject_change
        reject_change(pid, int(cidx))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/improve/history", methods=["GET"])
def api_improve_history():
    return jsonify(_load_json(ROOT / "improvement-history.json"))

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

  /* Nav tabs */
  .nav-tabs {
    display:flex; border-bottom:1px solid #1c1c26; background:#101016;
  }
  .nav-tab {
    font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:0.08em;
    padding:12px 20px; cursor:pointer; border:none; background:transparent;
    color:#555; text-transform:uppercase; border-bottom:2px solid transparent;
  }
  .nav-tab.active { color:#d4d4dc; border-bottom-color:#6366f1; }
  .nav-tab.improve-active { color:#d4d4dc; border-bottom-color:#f59e0b; }
  .nav-tab:hover { color:#888; }

  /* Improvement panel */
  .improve-panel { flex:1; overflow-y:auto; padding:24px 28px; display:none; }
  .improve-panel.visible { display:block; }

  .imp-btn {
    background:#f59e0b; border:none; border-radius:8px; color:#000;
    padding:12px 24px; font-size:13px; font-weight:600; cursor:pointer;
    font-family:'JetBrains Mono',monospace; letter-spacing:0.06em;
  }
  .imp-btn:disabled { opacity:0.4; cursor:not-allowed; }
  .imp-btn.sm { padding:6px 12px; font-size:10px; border-radius:6px; }
  .imp-btn.approve { background:#22c55e; }
  .imp-btn.reject { background:transparent; border:1px solid #555; color:#888; }

  .proposal-card {
    background:#16161e; border:1px solid #1c1c26; border-radius:8px;
    padding:16px 20px; margin-bottom:16px;
  }
  .proposal-card.resolved { opacity:0.5; }
  .change-card {
    background:#0f0f16; border:1px solid #1a1a24; border-radius:6px;
    padding:12px 16px; margin-bottom:8px; border-left:3px solid #f59e0b;
  }
  .change-card.approved-card { border-left-color:#22c55e; opacity:0.6; }
  .change-card.rejected-card { border-left-color:#555; opacity:0.3; }
  .change-field {
    font-family:'JetBrains Mono',monospace; font-size:10px;
    color:#555; letter-spacing:0.08em; text-transform:uppercase;
    margin-bottom:2px;
  }
  .change-value {
    font-size:12px; color:#c8c8d4; line-height:1.5; margin-bottom:8px;
    white-space:pre-wrap; word-break:break-word;
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

  <div class="nav-tabs">
    <button class="nav-tab active" id="tab-routing" onclick="switchTab('routing')">Routing</button>
    <button class="nav-tab" id="tab-improve" onclick="switchTab('improve')">Improvement</button>
  </div>

  <div class="output-area" id="output"></div>
  <div class="improve-panel" id="improve-panel"></div>

  <div class="input-area" id="routing-input">
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

// ── Tab switching ────────────────────────────────────────────────
function switchTab(tab) {
  const routing = document.getElementById('output');
  const routingInput = document.getElementById('routing-input');
  const improve = document.getElementById('improve-panel');
  const tabR = document.getElementById('tab-routing');
  const tabI = document.getElementById('tab-improve');

  if (tab === 'routing') {
    routing.style.display = 'block';
    routingInput.style.display = 'flex';
    improve.classList.remove('visible');
    tabR.classList.add('active'); tabR.classList.remove('improve-active');
    tabI.classList.remove('active'); tabI.classList.remove('improve-active');
  } else {
    routing.style.display = 'none';
    routingInput.style.display = 'none';
    improve.classList.add('visible');
    tabI.classList.add('improve-active');
    tabR.classList.remove('active');
    renderImprovePanel();
  }
}

// ── Improvement panel ────────────────────────────────────────────
async function renderImprovePanel() {
  const panel = document.getElementById('improve-panel');
  let history = [];
  try {
    const res = await fetch('/improve/history');
    history = await res.json();
  } catch {}

  const pending = history.filter(p => p.status === 'pending');
  const resolved = history.filter(p => p.status !== 'pending');

  let html = `
    <div style="margin-bottom:24px;">
      <button class="imp-btn" id="run-improve-btn" onclick="runImprove()">Run improvement cycle now</button>
      <span id="improve-status" style="margin-left:12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#555;"></span>
    </div>
  `;

  if (pending.length > 0) {
    html += `<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.12em;color:#f59e0b;text-transform:uppercase;margin-bottom:12px;">Pending Proposals (${pending.length})</div>`;
    for (const p of pending) {
      html += renderProposal(p, false);
    }
  }

  if (resolved.length > 0) {
    html += `<div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.12em;color:#555;text-transform:uppercase;margin:24px 0 12px;">History (${resolved.length})</div>`;
    for (const p of resolved.reverse().slice(0, 10)) {
      html += renderProposal(p, true);
    }
  }

  if (history.length === 0) {
    html += `<div style="color:#333;font-style:italic;margin-top:20px;">No improvement proposals yet. Run a cycle after routing some requests.</div>`;
  }

  panel.innerHTML = html;
}

function renderProposal(p, collapsed) {
  // Parse sections from proposal text
  const text = p.proposal || '';
  const patternsMatch = text.match(/PATTERNS OBSERVED\n([\s\S]*?)(?=PROPOSED CHANGES|$)/);
  const assessmentMatch = text.match(/OVERALL ASSESSMENT\n([\s\S]*?)(?=──────|$)/);
  const patterns = patternsMatch ? patternsMatch[1].trim() : '';
  const assessment = assessmentMatch ? assessmentMatch[1].trim() : '';

  // Parse individual changes
  const changeParts = text.split(/Change\s*\[?\d+\]?\s*:/);
  const changes = [];
  for (let i = 1; i < changeParts.length; i++) {
    const c = changeParts[i];
    const get = (f) => { const m = c.match(new RegExp(f + ':\\\\s*(.*?)(?=\\\\n\\\\s*(?:Type|Evidence|Current|Proposed|Reasoning|Risk|Confidence|$))', 's')); return m ? m[1].trim() : ''; };
    changes.push({
      type: get('Type') || extractField(c, 'Type'),
      evidence: get('Evidence') || extractField(c, 'Evidence'),
      current: get('Current') || extractField(c, 'Current'),
      proposed: get('Proposed') || extractField(c, 'Proposed'),
      reasoning: get('Reasoning') || extractField(c, 'Reasoning'),
      risk: get('Risk') || extractField(c, 'Risk'),
      confidence: get('Confidence') || extractField(c, 'Confidence'),
    });
  }

  const approvedIdxs = (p.approved_changes || []).map(a => a.change_index);
  const rejectedIdxs = (p.rejected_changes || []).map(r => r.change_index);

  let html = `<div class="proposal-card ${p.status !== 'pending' ? 'resolved' : ''}">`;
  html += `<div style="display:flex;justify-content:space-between;margin-bottom:8px;">`;
  html += `<span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#888;">${p.timestamp?.slice(0,10)} · ${p.requests_reviewed || 0} requests</span>`;
  html += `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;padding:2px 8px;border-radius:4px;background:${p.status==='pending'?'#f59e0b22':'#33333344'};color:${p.status==='pending'?'#f59e0b':'#555'};">${p.status}</span>`;
  html += `</div>`;

  if (!collapsed) {
    if (patterns) {
      html += `<div class="change-field">Patterns Observed</div>`;
      html += `<div class="change-value">${esc(patterns)}</div>`;
    }
    if (assessment) {
      html += `<div class="change-field">Overall Assessment</div>`;
      html += `<div class="change-value">${esc(assessment)}</div>`;
    }

    for (let i = 0; i < changes.length; i++) {
      const ch = changes[i];
      const isApproved = approvedIdxs.includes(i);
      const isRejected = rejectedIdxs.includes(i);
      const cls = isApproved ? 'approved-card' : isRejected ? 'rejected-card' : '';

      html += `<div class="change-card ${cls}">`;
      html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">`;
      html += `<span style="font-size:12px;font-weight:600;color:#d4d4dc;">Change ${i+1}</span>`;
      if (ch.confidence) html += `<span style="font-size:10px;color:${ch.confidence==='High'?'#22c55e':ch.confidence==='Medium'?'#f59e0b':'#888'};font-family:'JetBrains Mono',monospace;">${ch.confidence}</span>`;
      html += `</div>`;

      if (ch.type) { html += `<div class="change-field">Type</div><div class="change-value">${esc(ch.type)}</div>`; }
      if (ch.evidence) { html += `<div class="change-field">Evidence</div><div class="change-value">${esc(ch.evidence)}</div>`; }
      if (ch.reasoning) { html += `<div class="change-field">Reasoning</div><div class="change-value">${esc(ch.reasoning)}</div>`; }
      if (ch.risk) { html += `<div class="change-field">Risk</div><div class="change-value">${esc(ch.risk)}</div>`; }

      if (ch.current || ch.proposed) {
        html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0;">`;
        html += `<div><div class="change-field">Current</div><div style="background:#1a0a0a;border:1px solid #331a1a;border-radius:4px;padding:8px;font-size:11px;color:#c88;font-family:'JetBrains Mono',monospace;white-space:pre-wrap;">${esc(ch.current || '(none)')}</div></div>`;
        html += `<div><div class="change-field">Proposed</div><div style="background:#0a1a0a;border:1px solid #1a331a;border-radius:4px;padding:8px;font-size:11px;color:#8c8;font-family:'JetBrains Mono',monospace;white-space:pre-wrap;">${esc(ch.proposed || '(none)')}</div></div>`;
        html += `</div>`;
      }

      if (!isApproved && !isRejected && p.status === 'pending') {
        html += `<div style="display:flex;gap:8px;margin-top:8px;">`;
        html += `<button class="imp-btn sm approve" onclick="approveChange('${p.id}',${i})">APPROVE</button>`;
        html += `<button class="imp-btn sm reject" onclick="rejectChange('${p.id}',${i})">REJECT</button>`;
        html += `</div>`;
      } else if (isApproved) {
        html += `<div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#22c55e;margin-top:6px;">✓ Approved</div>`;
      } else if (isRejected) {
        html += `<div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#555;margin-top:6px;">✗ Rejected</div>`;
      }

      html += `</div>`;
    }
  }

  html += `</div>`;
  return html;
}

function extractField(text, field) {
  const lines = text.split('\\n');
  for (const line of lines) {
    if (line.trim().startsWith(field + ':')) {
      return line.trim().substring(field.length + 1).trim();
    }
  }
  return '';
}

async function runImprove() {
  const btn = document.getElementById('run-improve-btn');
  const status = document.getElementById('improve-status');
  btn.disabled = true;
  status.textContent = 'Running analysis...';
  status.style.color = '#f59e0b';
  try {
    const res = await fetch('/improve/run', { method: 'POST' });
    const data = await res.json();
    if (data.error) {
      status.textContent = 'Error: ' + data.error;
      status.style.color = '#ef4444';
    } else {
      status.textContent = 'Proposal generated';
      status.style.color = '#22c55e';
      renderImprovePanel();
    }
  } catch (e) {
    status.textContent = 'Connection error';
    status.style.color = '#ef4444';
  }
  btn.disabled = false;
}

async function approveChange(pid, idx) {
  try {
    await fetch('/improve/approve', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: pid, change_index: idx }),
    });
    renderImprovePanel();
    refreshRegistry();
  } catch {}
}

async function rejectChange(pid, idx) {
  try {
    await fetch('/improve/reject', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: pid, change_index: idx }),
    });
    renderImprovePanel();
  } catch {}
}
</script>

</body>
</html>"""

# ── Daily improvement scheduler ──────────────────────────────────────────────

def _daily_improvement_loop():
    """Run improvement cycle daily at midnight UTC."""
    while True:
        now = datetime.utcnow()
        # Calculate seconds until next midnight UTC
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if tomorrow <= now:
            tomorrow = tomorrow.replace(day=tomorrow.day + 1)
        wait = (tomorrow - now).total_seconds()
        print(f"Improvement agent: next cycle in {wait/3600:.1f} hours (midnight UTC)")
        time.sleep(wait)
        try:
            from improvement_agent import run_improvement_cycle
            proposal = run_improvement_cycle(API_KEY)
            print(f"Improvement cycle complete: proposal {proposal['id']}, {proposal['requests_reviewed']} requests reviewed")
        except Exception as e:
            print(f"Improvement cycle failed: {e}")

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start daily improvement scheduler in background
    t = threading.Thread(target=_daily_improvement_loop, daemon=True)
    t.start()
    print("Daily improvement scheduler registered")

    port = int(os.environ.get("PORT", 5000))
    print(f"LifeBridge starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
