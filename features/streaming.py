"""
features/streaming.py

Server-Sent Events (SSE) streaming for real-time agent progress.

How it works:
  1. Engine calls emit(session_id, event) as each stage completes
  2. Events are stored in an in-memory queue per session
  3. Flask /stream/<session_id> endpoint reads from queue and sends SSE
  4. Browser EventSource receives events and updates UI live

Event types:
  stage    — pipeline stage started (parse, agents, reflect, debate, done)
  agent    — individual agent update (name, status, score, confidence)
  signal   — key signal found (cluster buy, yield curve shape, etc.)
  verdict  — final debate verdict
  error    — something failed
"""

from __future__ import annotations
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# ── Global event store ────────────────────────────────────────────────
# session_id → Queue of SSE event dicts
_sessions: dict[str, queue.Queue] = {}
_lock = threading.Lock()

SESSION_TTL = 300   # seconds before session cleaned up


def create_session(session_id: str) -> None:
    with _lock:
        _sessions[session_id] = queue.Queue(maxsize=200)


def emit(session_id: str, event_type: str, data: dict) -> None:
    """Push an event to a session's queue. Safe to call from async context."""
    with _lock:
        q = _sessions.get(session_id)
    if q:
        try:
            q.put_nowait({"type": event_type, "data": data, "ts": time.time()})
        except queue.Full:
            pass


def get_events(session_id: str, timeout: float = 30.0):
    """
    Generator that yields SSE-formatted strings for a session.
    Yields keepalive comments every 15s to prevent connection timeout.
    """
    with _lock:
        q = _sessions.get(session_id)
    if not q:
        yield "data: {}\n\n"
        return

    deadline = time.time() + SESSION_TTL
    last_keepalive = time.time()

    while time.time() < deadline:
        # Send keepalive every 15s
        if time.time() - last_keepalive > 15:
            yield ": keepalive\n\n"
            last_keepalive = time.time()

        try:
            event = q.get(timeout=1.0)
        except queue.Empty:
            continue

        payload = json.dumps(event["data"])
        yield f"event: {event['type']}\ndata: {payload}\n\n"

        # Stop streaming after 'done' or 'error'
        if event["type"] in ("done", "error"):
            break

    # Cleanup
    with _lock:
        _sessions.pop(session_id, None)


def cleanup_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


# ── Convenience emitters ──────────────────────────────────────────────

def emit_stage(sid: str, stage: str, detail: str = "") -> None:
    """Emit a pipeline stage update."""
    emit(sid, "stage", {"stage": stage, "detail": detail})


def emit_agent(sid: str, agent: str, status: str, score: float = 0,
               confidence: float = 0, summary: str = "") -> None:
    """Emit an individual agent result."""
    emit(sid, "agent", {
        "agent":      agent,
        "status":     status,   # "running" | "done" | "failed"
        "score":      round(score, 1),
        "confidence": round(confidence, 1),
        "summary":    summary[:120] if summary else "",
    })


def emit_signal(sid: str, signal: str, value: str, bullish: bool) -> None:
    """Emit a key signal found."""
    emit(sid, "signal", {"signal": signal, "value": value, "bullish": bullish})


def emit_verdict(sid: str, decision: str, confidence: float,
                 bull_score: float, bear_score: float) -> None:
    """Emit the final debate verdict."""
    emit(sid, "verdict", {
        "decision":   decision,
        "confidence": round(confidence, 1),
        "bull_score": round(bull_score, 1),
        "bear_score": round(bear_score, 1),
    })


def emit_done(sid: str, result: dict) -> None:
    """Signal that the full result is ready."""
    emit(sid, "done", {"status": "complete", "result_key": result.get("ticker", "")})


def emit_error(sid: str, message: str) -> None:
    emit(sid, "error", {"message": message})
