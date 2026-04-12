"""features/backtest.py — Outcome tracking and accuracy stats."""
from __future__ import annotations
import os, sqlite3, asyncio
from datetime import datetime, timedelta

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.getenv("AFDE_DB", os.path.join(_APP_DIR, "history.db"))

def _init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS decision_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 0,
        ticker TEXT NOT NULL, decision TEXT NOT NULL,
        confidence REAL, price_at_decision REAL,
        price_at_30d REAL, return_30d REAL,
        outcome TEXT DEFAULT 'pending',
        decision_date TEXT NOT NULL, outcome_date TEXT)""")
    conn.commit()

def store_decision(ticker: str, decision: str, confidence: float,
                   price: float, user_id: int = 0) -> None:
    if not price or not ticker or decision not in ("BUY","HOLD","SELL"):
        return
    conn = sqlite3.connect(DB_PATH)
    _init(conn)
    conn.execute(
        "INSERT INTO decision_outcomes VALUES (NULL,?,?,?,?,?,NULL,NULL,'pending',?,NULL)",
        (user_id, ticker.upper(), decision, confidence, price, datetime.now().isoformat()))
    conn.commit(); conn.close()

async def check_outcomes() -> int:
    import yfinance as yf
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    conn   = sqlite3.connect(DB_PATH); _init(conn)
    pending = conn.execute(
        "SELECT id,ticker,decision,price_at_decision FROM decision_outcomes "
        "WHERE outcome='pending' AND decision_date<=?", (cutoff,)).fetchall()
    conn.close()
    resolved = 0
    for rid, ticker, decision, entry in pending:
        try:
            def _f(t=ticker):
                i = yf.Ticker(t).info
                return i.get("currentPrice") or i.get("regularMarketPrice")
            cur = await asyncio.get_event_loop().run_in_executor(None, _f)
            if not cur or not entry: continue
            ret = round((cur - entry) / entry * 100, 2)
            if decision=="BUY":   outcome = "outperformed" if ret>2 else "underperformed" if ret<-2 else "neutral"
            elif decision=="SELL":outcome = "outperformed" if ret<-2 else "underperformed" if ret>2 else "neutral"
            else:                 outcome = "neutral"
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE decision_outcomes SET price_at_30d=?,return_30d=?,outcome=?,outcome_date=? WHERE id=?",
                         (cur, ret, outcome, datetime.now().isoformat(), rid))
            conn.commit(); conn.close(); resolved += 1
        except Exception: continue
    return resolved

def get_accuracy_stats(user_id: int = 0) -> dict:
    conn = sqlite3.connect(DB_PATH); _init(conn)
    rows = conn.execute(
        "SELECT decision,return_30d,outcome,confidence,ticker,decision_date "
        "FROM decision_outcomes WHERE user_id=? AND outcome!='pending' ORDER BY decision_date DESC",
        (user_id,)).fetchall()
    pending = conn.execute(
        "SELECT COUNT(*) FROM decision_outcomes WHERE user_id=? AND outcome='pending'",
        (user_id,)).fetchone()[0]
    conn.close()
    if not rows:
        return {"total_resolved":0,"pending":pending,
                "message":"No resolved decisions yet — check back in 30 days after your first BUY/SELL."}
    by: dict = {"BUY":[],"HOLD":[],"SELL":[]}
    recent = []
    for dec,ret,outcome,conf,ticker,date in rows:
        if ret is not None: by.get(dec,by["HOLD"]).append(ret)
        recent.append({"ticker":ticker,"decision":dec,"return_30d":ret,
                       "outcome":outcome,"confidence":conf,"date":date[:10]})
    def _avg(l): return round(sum(l)/len(l),2) if l else None
    def _win(l): return round(sum(1 for r in l if r>0)/len(l)*100,1) if l else None
    all_r = [r["return_30d"] for r in recent if r["return_30d"] is not None]
    return {
        "total_resolved":    len(rows),   "pending":         pending,
        "overall_avg_return":_avg(all_r), "buy_avg_return":  _avg(by["BUY"]),
        "hold_avg_return":   _avg(by["HOLD"]),"sell_avg_return": _avg(by["SELL"]),
        "buy_win_rate":      _win(by["BUY"]),"buy_count":       len(by["BUY"]),
        "hold_count":        len(by["HOLD"]),"sell_count":      len(by["SELL"]),
        "best_call":  max(recent,key=lambda r:r["return_30d"] or -999) if recent else None,
        "worst_call": min(recent,key=lambda r:r["return_30d"] or 999)  if recent else None,
        "recent_outcomes": recent[:10],
    }

def get_pending_decisions(user_id: int = 0) -> list[dict]:
    conn = sqlite3.connect(DB_PATH); _init(conn)
    rows = conn.execute(
        "SELECT ticker,decision,confidence,price_at_decision,decision_date "
        "FROM decision_outcomes WHERE user_id=? AND outcome='pending' ORDER BY decision_date DESC LIMIT 20",
        (user_id,)).fetchall()
    conn.close()
    return [{"ticker":r[0],"decision":r[1],"confidence":r[2],"entry_price":r[3],"date":r[4][:10]} for r in rows]
