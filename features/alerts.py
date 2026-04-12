"""
features/alerts.py

Price alert system — monitors BUY decisions and re-triggers analysis
when price drops 10% from the analysis date price.

Flow:
  1. After every BUY decision, store ticker + price at analysis date
  2. APScheduler runs check_all_alerts() daily at 8am
  3. If current price < stored price * 0.90, trigger re-analysis
  4. Store alert notification for user to see in UI
"""

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv("AFDE_DB", "history.db")


def _init_alerts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER DEFAULT 0,
            ticker          TEXT NOT NULL,
            decision        TEXT NOT NULL,
            analysis_price  REAL NOT NULL,
            alert_threshold REAL NOT NULL,   -- analysis_price * 0.90
            current_price   REAL,
            status          TEXT DEFAULT 'active',   -- active | triggered | dismissed
            triggered_at    TEXT,
            created         TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER DEFAULT 0,
            ticker      TEXT NOT NULL,
            message     TEXT NOT NULL,
            read        INTEGER DEFAULT 0,
            created     TEXT NOT NULL
        )
    """)
    conn.commit()


def register_alert(ticker: str, decision: str, analysis_price: float,
                   user_id: int = 0) -> None:
    """Register a price alert after a BUY decision."""
    if decision != "BUY" or not analysis_price:
        return
    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    # Remove any existing active alert for this ticker+user
    conn.execute(
        "UPDATE price_alerts SET status='dismissed' WHERE ticker=? AND user_id=? AND status='active'",
        (ticker.upper(), user_id)
    )
    conn.execute(
        "INSERT INTO price_alerts VALUES (NULL,?,?,?,?,?,NULL,'active',NULL,?)",
        (user_id, ticker.upper(), decision, analysis_price,
         round(analysis_price * 0.90, 2), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_active_alerts(user_id: int = 0) -> list[dict]:
    """Return all active price alerts for a user."""
    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    rows = conn.execute(
        """SELECT id, ticker, decision, analysis_price, alert_threshold,
                  current_price, status, created
           FROM price_alerts
           WHERE user_id = ? AND status = 'active'
           ORDER BY created DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [
        {
            "id":               r[0], "ticker":          r[1],
            "decision":         r[2], "analysis_price":  r[3],
            "alert_threshold":  r[4], "current_price":   r[5],
            "status":           r[6], "created":         r[7],
            "drop_pct": round(((r[5] or r[3]) - r[3]) / r[3] * 100, 1) if r[5] else 0,
        }
        for r in rows
    ]


def get_notifications(user_id: int = 0, unread_only: bool = False) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    query = ("SELECT id, ticker, message, read, created FROM alert_notifications "
             "WHERE user_id = ?")
    params = [user_id]
    if unread_only:
        query += " AND read = 0"
    query += " ORDER BY id DESC LIMIT 20"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [{"id": r[0], "ticker": r[1], "message": r[2],
             "read": bool(r[3]), "created": r[4]} for r in rows]


def mark_notification_read(notif_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    conn.execute("UPDATE alert_notifications SET read=1 WHERE id=?", (notif_id,))
    conn.commit()
    conn.close()


def dismiss_alert(alert_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    conn.execute("UPDATE price_alerts SET status='dismissed' WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()


async def check_all_alerts() -> list[str]:
    """
    APScheduler job — check all active alerts against current prices.
    Returns list of triggered ticker symbols.
    """
    import yfinance as yf
    import asyncio

    conn = sqlite3.connect(DB_PATH)
    _init_alerts_table(conn)
    alerts = conn.execute(
        "SELECT id, user_id, ticker, analysis_price, alert_threshold "
        "FROM price_alerts WHERE status = 'active'"
    ).fetchall()
    conn.close()

    triggered = []
    for alert_id, user_id, ticker, analysis_price, threshold in alerts:
        try:
            def _price(t=ticker):
                info = yf.Ticker(t).info
                return info.get("currentPrice") or info.get("regularMarketPrice")
            current = await asyncio.get_event_loop().run_in_executor(None, _price)
            if not current:
                continue

            # Update current price
            conn = sqlite3.connect(DB_PATH)
            _init_alerts_table(conn)
            conn.execute(
                "UPDATE price_alerts SET current_price=? WHERE id=?",
                (current, alert_id)
            )

            if current <= threshold:
                drop_pct = round((current - analysis_price) / analysis_price * 100, 1)
                msg = (f"{ticker} has dropped {abs(drop_pct):.1f}% from your BUY analysis "
                       f"(${analysis_price:.2f} → ${current:.2f}). "
                       f"Re-analysis recommended.")
                conn.execute(
                    "INSERT INTO alert_notifications VALUES (NULL,?,?,?,0,?)",
                    (user_id, ticker, msg, datetime.now().isoformat())
                )
                conn.execute(
                    "UPDATE price_alerts SET status='triggered', triggered_at=? WHERE id=?",
                    (datetime.now().isoformat(), alert_id)
                )
                triggered.append(ticker)
            conn.commit()
            conn.close()
        except Exception:
            continue

    return triggered
