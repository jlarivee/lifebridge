# LifeBridge — Autonomous Agent Operating System

LifeBridge is a master agent that receives requests, classifies them by domain, checks a capability registry for existing agents, decomposes complex goals, flags actions requiring human approval, and routes to the right agent or initiates a build if none exists.

## How it works

Every request goes through five decisions in order: domain classification, capability check, goal decomposition, approval assessment, and routing. The output is a structured routing package that tells you exactly what will happen and why.

The capability registry starts empty. As you use LifeBridge, it learns which domains your requests belong to and logs gaps where no agent exists yet. Each gap becomes a build brief for a new agent.

## Running locally

```
export ANTHROPIC_API_KEY=your-key-here
pip install flask anthropic
python server.py
```

Open http://localhost:5000 in a browser.

## Endpoints

**GET /** — Web UI. Chat-style interface for sending requests to the master agent.

**POST /route** — API endpoint. Send `{"input": "your request"}`, receive a routing package.

**GET /registry** — Returns the current capability registry (agents, domain signals, pending builds).

**POST /registry/update** — Add entries to the registry. Send `{"agent": {...}}`, `{"domain_signal": {...}}`, or `{"pending_build": {...}}`.

## Deploying on Replit

1. Import from GitHub
2. Set `ANTHROPIC_API_KEY` in Secrets
3. Run command: `python server.py`
