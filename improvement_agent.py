"""
LifeBridge Improvement Agent
Analyzes request log and registry, proposes evidence-based improvements.
Never executes changes — only proposes. Human approves or rejects.
"""

import json
import uuid
import re
from datetime import datetime
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent
SYSTEM_PROMPT_PATH = ROOT / "system-prompt.txt"
REGISTRY_PATH = ROOT / "registry.json"
REQUEST_LOG_PATH = ROOT / "request-log.json"
HISTORY_PATH = ROOT / "improvement-history.json"

IMPROVEMENT_SYSTEM = """You are the LifeBridge Improvement Agent. Your job is to analyze how the master agent has been performing and propose specific, evidence-based improvements. You never execute changes. You only propose them. Every proposal must cite specific evidence from the request log. Vague suggestions are not acceptable."""

IMPROVEMENT_USER_TEMPLATE = """Here is the current master agent system prompt:
{system_prompt}

Here is the current registry:
{registry}

Here is the request log (last 50 entries max):
{request_log}

Here is the improvement history (what has already been proposed and decided):
{history}

Analyze this data and produce a structured improvement proposal using exactly this format:

IMPROVEMENT PROPOSAL
──────────────────────────
Analysis date:    {date}
Requests reviewed: {count}
──────────────────────────

PATTERNS OBSERVED
[numbered list — what is working well, what is breaking down, what is missing]

PROPOSED CHANGES
[For each proposed change:]

Change [N]:
  Type:       [System prompt edit | Registry addition | Connector addition | No change needed]
  Evidence:   [specific request IDs or patterns that justify this change]
  Current:    [exact current text or state, if editing]
  Proposed:   [exact replacement text or new entry]
  Reasoning:  [why this makes the master agent better]
  Risk:       [what could go wrong if this change is wrong]
  Confidence: [High | Medium | Low]

OVERALL ASSESSMENT
[One paragraph — is the master agent improving, degrading, or stable? What is the single most important change?]
──────────────────────────"""


def _load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return []


def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def run_improvement_cycle(api_key):
    """Run a full improvement analysis cycle. Returns the proposal object."""

    # Step 1 — Load context
    system_prompt = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""
    registry = json.dumps(_load_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {}, indent=2)
    request_log = _load_json(REQUEST_LOG_PATH)
    history = _load_json(HISTORY_PATH)

    # Last 50 entries only
    recent_log = request_log[-50:]
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Step 2 — Build and send the improvement prompt
    client = anthropic.Anthropic(api_key=api_key)

    user_msg = IMPROVEMENT_USER_TEMPLATE.format(
        system_prompt=system_prompt,
        registry=registry,
        request_log=json.dumps(recent_log, indent=2, default=str),
        history=json.dumps(history, indent=2, default=str),
        date=today,
        count=len(recent_log),
    )

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=IMPROVEMENT_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    proposal_text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

    # Step 3 — Store the proposal
    proposal = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pending",
        "requests_reviewed": len(recent_log),
        "proposal": proposal_text,
        "approved_changes": [],
        "rejected_changes": [],
    }

    history.append(proposal)
    _save_json(HISTORY_PATH, history)

    return proposal


def apply_change(proposal_id, change_index):
    """Apply an approved change from a proposal. Returns description of what changed."""
    history = _load_json(HISTORY_PATH)
    proposal = next((p for p in history if p["id"] == proposal_id), None)
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")

    # Parse changes from proposal text
    changes = _parse_changes(proposal["proposal"])
    if change_index < 0 or change_index >= len(changes):
        raise ValueError(f"Change index {change_index} out of range (0-{len(changes)-1})")

    change = changes[change_index]
    change_type = change.get("type", "").lower()
    applied = ""

    if "system prompt edit" in change_type:
        current = change.get("current", "")
        proposed = change.get("proposed", "")
        if current and proposed:
            sp = SYSTEM_PROMPT_PATH.read_text()
            if current in sp:
                sp = sp.replace(current, proposed, 1)
                SYSTEM_PROMPT_PATH.write_text(sp)
                applied = f"System prompt edited: replaced '{current[:50]}...' with '{proposed[:50]}...'"
            else:
                applied = f"System prompt edit: exact match for 'Current' text not found — wrote proposed text to end of prompt"
                sp += f"\n\n{proposed}"
                SYSTEM_PROMPT_PATH.write_text(sp)
        else:
            applied = "System prompt edit: missing current/proposed text in change"

    elif "registry addition" in change_type:
        proposed = change.get("proposed", "")
        registry = _load_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {}
        try:
            entry = json.loads(proposed) if proposed.strip().startswith("{") else {"entry": proposed}
        except json.JSONDecodeError:
            entry = {"entry": proposed}

        if "agents" not in registry:
            registry["agents"] = []
        registry["agents"].append(entry)
        _save_json(REGISTRY_PATH, registry)
        applied = f"Registry addition: added to agents list"

    elif "connector addition" in change_type:
        proposed = change.get("proposed", "")
        registry = _load_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {}
        try:
            entry = json.loads(proposed) if proposed.strip().startswith("{") else {"entry": proposed}
        except json.JSONDecodeError:
            entry = {"entry": proposed}

        registry.setdefault("connectors", []).append(entry)
        _save_json(REGISTRY_PATH, registry)
        applied = f"Connector addition: added to connectors list"

    elif "no change" in change_type:
        applied = "No change needed — acknowledged"

    else:
        applied = f"Unknown change type: {change_type}"

    # Update proposal status
    proposal.setdefault("approved_changes", []).append({
        "change_index": change_index,
        "committed_at": datetime.utcnow().isoformat(),
        "description": applied,
    })

    # Check if all changes are resolved
    total_changes = len(changes)
    resolved = len(proposal.get("approved_changes", [])) + len(proposal.get("rejected_changes", []))
    if resolved >= total_changes:
        proposal["status"] = "resolved"

    _save_json(HISTORY_PATH, history)
    return applied


def reject_change(proposal_id, change_index):
    """Reject a proposed change."""
    history = _load_json(HISTORY_PATH)
    proposal = next((p for p in history if p["id"] == proposal_id), None)
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")

    proposal.setdefault("rejected_changes", []).append({
        "change_index": change_index,
        "rejected_at": datetime.utcnow().isoformat(),
    })

    changes = _parse_changes(proposal["proposal"])
    total_changes = len(changes)
    resolved = len(proposal.get("approved_changes", [])) + len(proposal.get("rejected_changes", []))
    if resolved >= total_changes:
        proposal["status"] = "resolved"

    _save_json(HISTORY_PATH, history)


def _parse_changes(proposal_text):
    """Parse Change [N] blocks from proposal text."""
    changes = []
    # Split on "Change [N]:" or "Change N:" patterns
    parts = re.split(r'Change\s*\[?\d+\]?\s*:', proposal_text)
    if len(parts) <= 1:
        return changes

    for part in parts[1:]:
        change = {}
        for field in ["Type", "Evidence", "Current", "Proposed", "Reasoning", "Risk", "Confidence"]:
            match = re.search(rf'{field}:\s*(.*?)(?=\n\s*(?:Type|Evidence|Current|Proposed|Reasoning|Risk|Confidence|Change|OVERALL|$))', part, re.DOTALL)
            if match:
                change[field.lower()] = match.group(1).strip()
        if change:
            changes.append(change)

    return changes
