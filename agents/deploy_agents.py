"""Create (or refresh) the two Lyzr agents from the JSON configs in this folder.

Usage:
    LYZR_API_KEY=... python agents/deploy_agents.py

Prints the agent IDs to paste into .env as LYZR_CLASSIFIER_AGENT_ID and
LYZR_WRITER_AGENT_ID. The Agent Studio REST schema evolves; if the create call
rejects a field, create the agents in the Studio UI with the same system prompts
(classifier/system_prompt.md, disclosure_writer/system_prompt.md) and copy the IDs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).parent
BASE = os.getenv("LYZR_API_BASE", "https://agent-prod.studio.lyzr.ai")


def load(folder: str) -> dict:
    cfg = json.loads((HERE / folder / "agent.json").read_text(encoding="utf-8"))
    prompt = (HERE / folder / cfg.pop("agent_instructions_file")).read_text(encoding="utf-8")
    body = {
        "name": cfg["name"],
        "description": cfg["description"],
        "agent_role": cfg["agent_role"],
        "agent_instructions": prompt,
        "provider_id": cfg["provider_id"],
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
        "features": cfg.get("features", []),
        "tools": [],
        "llm_credential_id": os.getenv("LYZR_LLM_CREDENTIAL_ID", "lyzr_openai"),
    }
    if cfg.get("response_format"):
        body["response_format"] = cfg["response_format"]
    return body


def main() -> int:
    key = os.getenv("LYZR_API_KEY")
    if not key:
        print("LYZR_API_KEY is not set", file=sys.stderr)
        return 1
    out = {}
    with httpx.Client(timeout=60, headers={"x-api-key": key, "Content-Type": "application/json"}) as c:
        for folder, env in (("classifier", "LYZR_CLASSIFIER_AGENT_ID"), ("disclosure_writer", "LYZR_WRITER_AGENT_ID")):
            body = load(folder)
            r = c.post(f"{BASE}/v3/agents/", json=body)
            if r.status_code >= 300:
                print(f"[{folder}] create failed {r.status_code}: {r.text[:400]}", file=sys.stderr)
                continue
            data = r.json()
            agent_id = data.get("agent_id") or data.get("id") or data.get("_id")
            out[env] = agent_id
            print(f"{env}={agent_id}")
    return 0 if len(out) == 2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
