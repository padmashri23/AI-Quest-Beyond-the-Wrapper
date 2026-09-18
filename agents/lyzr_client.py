"""Thin client for the Lyzr Agent API (v3 inference).

    POST https://agent-prod.studio.lyzr.ai/v3/inference/chat/
    headers: x-api-key: <LYZR_API_KEY>
    body:    {"user_id", "agent_id", "session_id", "message"}
    returns: {"response": "<agent text>", ...}

If LYZR_API_KEY is not set the client reports itself unavailable and the orchestrator
runs in rules-only fallback mode. Nothing in the numeric pipeline depends on this call.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

LYZR_CHAT_URL = os.getenv("LYZR_CHAT_URL", "https://agent-prod.studio.lyzr.ai/v3/inference/chat/")


@dataclass
class AgentReply:
    text: str
    latency_ms: int
    session_id: str
    raw: dict


class LyzrClient:
    def __init__(self, api_key: Optional[str] = None, user_id: Optional[str] = None, timeout: float = 60.0):
        self.api_key = api_key if api_key is not None else os.getenv("LYZR_API_KEY", "").strip()
        if os.getenv('LYZR_DISABLED','').lower() in {'1','true','yes'}:
            self.api_key = ''
        self.user_id = user_id or os.getenv("LYZR_USER_ID", "carbon-copilot@local")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, agent_id: str, message: str, session_id: Optional[str] = None) -> AgentReply:
        if not self.available:
            raise RuntimeError("LYZR_API_KEY not configured")
        if not agent_id:
            raise RuntimeError("agent_id not configured")
        sid = session_id or f"{agent_id}-{uuid.uuid4().hex[:12]}"
        payload = {"user_id": self.user_id, "agent_id": agent_id, "session_id": sid, "message": message}
        t0 = time.perf_counter()
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(LYZR_CHAT_URL, json=payload, headers={"x-api-key": self.api_key, "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        latency = int((time.perf_counter() - t0) * 1000)
        text = data.get("response") if isinstance(data, dict) else str(data)
        if not isinstance(text, str):
            raise ValueError('Agent response must contain a text response')
        return AgentReply(text=text or "", latency_ms=latency, session_id=sid, raw=data if isinstance(data, dict) else {"raw": data})
