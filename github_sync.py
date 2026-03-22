"""
LifeBridge GitHub Sync — auto-commits living state files to GitHub.
Best-effort: never raises exceptions that break the calling operation.
"""

import os
import json
import base64
import logging
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent
SYNC_STATUS_PATH = ROOT / "sync-status.json"
LIVING_FILES = {"system-prompt.txt", "registry.json", "context.json", "improvement-history.json", "request-log.json"}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")

logger = logging.getLogger("github-sync")


def _load_sync_status():
    if SYNC_STATUS_PATH.exists():
        return json.loads(SYNC_STATUS_PATH.read_text())
    return {"enabled": False, "last_sync": None, "last_sync_result": None, "last_commit_sha": None}


def _save_sync_status(status):
    SYNC_STATUS_PATH.write_text(json.dumps(status, indent=2, default=str))


def is_configured():
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def commit_state_file(filename, reason):
    """Commit a living state file to GitHub. Best-effort — never crashes the caller."""
    if not is_configured():
        return {"synced": False, "reason": "not configured"}

    if filename not in LIVING_FILES:
        return {"synced": False, "reason": f"'{filename}' is not a living state file"}

    filepath = ROOT / filename
    if not filepath.exists():
        return {"synced": False, "reason": f"file not found: {filename}"}

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"

    try:
        # Step 1: Get current SHA
        resp = requests.get(api_url, headers=headers, timeout=15)
        current_sha = None
        if resp.status_code == 200:
            current_sha = resp.json().get("sha")
        elif resp.status_code != 404:
            logger.warning(f"GitHub GET failed ({resp.status_code}): {resp.text[:200]}")

        # Step 2: Encode file content
        content = filepath.read_bytes()
        b64_content = base64.b64encode(content).decode("utf-8")

        # Step 3: PUT to update/create file
        body = {
            "message": f"LifeBridge auto-sync: {reason}",
            "content": b64_content,
            "branch": "main",
        }
        if current_sha:
            body["sha"] = current_sha

        put_resp = requests.put(api_url, headers=headers, json=body, timeout=15)

        if put_resp.status_code in (200, 201):
            commit_sha = put_resp.json().get("commit", {}).get("sha", "unknown")
            logger.info(f"Synced {filename}: {reason} (commit: {commit_sha[:8]})")
            status = _load_sync_status()
            status.update({
                "enabled": True,
                "last_sync": datetime.utcnow().isoformat(),
                "last_sync_result": "success",
                "last_commit_sha": commit_sha,
            })
            _save_sync_status(status)
            return {"synced": True, "commit_sha": commit_sha}
        else:
            logger.warning(f"GitHub PUT failed ({put_resp.status_code}): {put_resp.text[:200]}")
            status = _load_sync_status()
            status["last_sync_result"] = "failed"
            status["last_sync"] = datetime.utcnow().isoformat()
            _save_sync_status(status)
            return {"synced": False, "reason": f"GitHub API error {put_resp.status_code}"}

    except Exception as e:
        logger.warning(f"GitHub sync failed for {filename}: {e}")
        status = _load_sync_status()
        status["last_sync_result"] = "failed"
        status["last_sync"] = datetime.utcnow().isoformat()
        _save_sync_status(status)
        return {"synced": False, "reason": str(e)}


def full_sync(reason="Daily full sync"):
    """Sync all living state files."""
    results = {}
    for f in LIVING_FILES:
        results[f] = commit_state_file(f, reason)
    return results


def startup_check():
    """Run at server startup to verify GitHub connectivity."""
    if not is_configured():
        print("GitHub sync disabled — GITHUB_TOKEN or GITHUB_REPO not set")
        print("  To enable: add GITHUB_TOKEN and GITHUB_REPO as Replit Secrets")
        print("  GITHUB_TOKEN: create at github.com/settings/tokens (scope: repo)")
        print("  GITHUB_REPO: format 'username/reponame'")
        status = _load_sync_status()
        status["enabled"] = False
        _save_sync_status(status)
        return False

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    try:
        resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}", headers=headers, timeout=10)
        if resp.status_code == 200:
            print(f"GitHub sync enabled — connected to {GITHUB_REPO}")
            status = _load_sync_status()
            status["enabled"] = True
            _save_sync_status(status)
            # Startup sync
            full_sync("Startup sync — verifying state")
            return True
        else:
            print(f"GitHub sync error — could not reach {GITHUB_REPO} (HTTP {resp.status_code})")
            return False
    except Exception as e:
        print(f"GitHub sync error — {e}")
        return False
