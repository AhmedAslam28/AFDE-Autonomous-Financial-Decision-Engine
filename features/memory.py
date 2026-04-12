"""
features/memory.py

Agent memory layer using sqlite-vec for vector similarity search.

Every time a stock is analysed:
  - Key signals are stored as text in SQLite
  - On the next analysis of the same stock, agents receive a summary
    of what was found last time and what has changed

Uses simple TF-IDF style keyword matching via sqlite-vec if available,
falls back to plain SQLite text search if vector extension unavailable.
"""

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from dataclasses import asdict

DB_PATH = os.getenv("AFDE_DB", "history.db")


def _init_memory_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            user_id     INTEGER DEFAULT 0,
            agent       TEXT NOT NULL,
            score       REAL,
            confidence  REAL,
            summary     TEXT,
            data_points TEXT,   -- JSON array
            source      TEXT,
            decision    TEXT,
            created     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_ticker ON agent_memory(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user   ON agent_memory(user_id)")
    conn.commit()


def store_analysis_memory(
    ticker: str,
    signals: dict,          # dict[agent_name, AgentSignal]
    decision: str,
    user_id: int = 0,
) -> None:
    """Store all agent signals from a completed analysis into memory."""
    conn = sqlite3.connect(DB_PATH)
    _init_memory_table(conn)
    now = datetime.now().isoformat()

    for agent_name, sig in signals.items():
        # Handle both AgentSignal dataclass and plain dicts
        if hasattr(sig, 'score'):
            score      = sig.score
            confidence = sig.confidence
            summary    = sig.summary
            data_points= sig.data_points
            source     = getattr(sig, 'source', 'live')
        else:
            score      = sig.get('score', 50)
            confidence = sig.get('confidence', 50)
            summary    = sig.get('summary', '')
            data_points= sig.get('data_points', [])
            source     = sig.get('source', 'live')

        conn.execute(
            "INSERT INTO agent_memory VALUES (NULL,?,?,?,?,?,?,?,?,?,?)",
            (
                ticker.upper(), user_id, agent_name,
                score, confidence, summary,
                json.dumps(data_points), source,
                decision, now,
            )
        )
    conn.commit()
    conn.close()


def get_memory_context(ticker: str, user_id: int = 0, limit: int = 2) -> str:
    """
    Retrieve previous analysis summaries for a ticker.
    Returns a formatted string injected into agent context.
    """
    conn = sqlite3.connect(DB_PATH)
    _init_memory_table(conn)

    rows = conn.execute(
        """SELECT agent, score, confidence, summary, data_points, decision, created
           FROM agent_memory
           WHERE ticker = ? AND user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (ticker.upper(), user_id, limit * 4)   # 4 agents × limit analyses
    ).fetchall()
    conn.close()

    if not rows:
        return ""

    # Group by analysis timestamp (approximate by decision+created)
    analyses = {}
    for agent, score, conf, summary, dps_json, decision, created in rows:
        key = created[:10]   # group by date
        if key not in analyses:
            analyses[key] = {"date": key, "decision": decision, "agents": []}
        analyses[key]["agents"].append({
            "agent":   agent,
            "score":   score,
            "summary": summary[:80],
        })

    if not analyses:
        return ""

    lines = [f"\n=== MEMORY: Previous analyses for {ticker.upper()} ==="]
    for date, data in sorted(analyses.items(), reverse=True)[:limit]:
        lines.append(f"\n[{date}] Decision: {data['decision']}")
        for a in data["agents"]:
            lines.append(f"  {a['agent']}: score={a['score']:.0f} — {a['summary']}")

    lines.append("\nINSTRUCTION: Note what has CHANGED since the last analysis.")
    lines.append("If signals are similar, note continuity. If reversed, highlight the change.")
    lines.append("=== END MEMORY ===\n")

    return "\n".join(lines)


def get_ticker_history_summary(ticker: str, user_id: int = 0) -> list[dict]:
    """Return list of past decisions for a ticker (for UI display)."""
    conn = sqlite3.connect(DB_PATH)
    _init_memory_table(conn)
    rows = conn.execute(
        """SELECT DISTINCT created, decision,
                  AVG(score) as avg_score, AVG(confidence) as avg_conf
           FROM agent_memory
           WHERE ticker = ? AND user_id = ?
           GROUP BY substr(created, 1, 16)
           ORDER BY created DESC LIMIT 10""",
        (ticker.upper(), user_id)
    ).fetchall()
    conn.close()
    return [
        {"date": r[0][:10], "decision": r[1],
         "avg_score": round(r[2], 1), "avg_confidence": round(r[3], 1)}
        for r in rows
    ]
