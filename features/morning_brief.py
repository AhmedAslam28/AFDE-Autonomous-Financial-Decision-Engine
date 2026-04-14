"""features/morning_brief.py — Morning intelligence brief via email + in-app notification."""
from __future__ import annotations
import os, sqlite3, smtplib, asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

_APP_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("AFDE_DB", "/tmp/history.db")
SMTP_HOST = os.getenv("SMTP_HOST","smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT","587"))
SMTP_USER = os.getenv("SMTP_USER","")
SMTP_PASS = os.getenv("SMTP_PASS","")
BRIEF_FROM= os.getenv("BRIEF_FROM","AFDE <noreply@afde.ai>")

def _get_users_with_watchlists() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """SELECT u.id,u.username,u.email,GROUP_CONCAT(w.ticker,',') as tickers
               FROM users u JOIN watchlist w ON w.user_id=u.id GROUP BY u.id""").fetchall()
        return [{"id":r[0],"username":r[1],"email":r[2],
                 "tickers":[t.strip() for t in (r[3] or "").split(",") if t.strip()]}
                for r in rows if r[3]]
    except Exception: return []
    finally: conn.close()

async def _quick_signal_check(ticker: str) -> dict:
    import yfinance as yf
    def _f(t=ticker):
        i = yf.Ticker(t).info
        return {"ticker":t.upper(),"current_price":i.get("currentPrice") or i.get("regularMarketPrice"),
                "change_pct":i.get("regularMarketChangePercent",0),"company":i.get("longName",t)}
    try: return await asyncio.get_event_loop().run_in_executor(None, _f)
    except Exception: return {"ticker":ticker,"error":"fetch failed"}

async def build_brief_content(user: dict) -> dict:
    changed, unchanged, errors = [], [], []
    results = await asyncio.gather(*[_quick_signal_check(t) for t in user["tickers"][:8]], return_exceptions=True)
    for ticker, result in zip(user["tickers"][:8], results):
        if isinstance(result, Exception) or "error" in result: errors.append(ticker); continue
        chg = result.get("change_pct",0) or 0
        item = {"ticker":ticker,"company":result.get("company",ticker),"price":result.get("current_price"),
                "change_pct":round(chg*100,2) if abs(chg)<1 else round(chg,2)}
        if abs(item["change_pct"]) > 2:
            item["flag"] = f"Price moved {item['change_pct']:+.1f}% — re-analysis recommended"
            changed.append(item)
        else: unchanged.append(item)
    return {"user":user,"date":datetime.now().strftime("%A, %B %d %Y"),
            "changed":changed,"unchanged":unchanged,"errors":errors}

def _send_email(to_email: str, subject: str, html: str) -> bool:
    if not SMTP_USER or not SMTP_PASS: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"]=subject; msg["From"]=BRIEF_FROM; msg["To"]=to_email
        msg.attach(MIMEText(html,"html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER,SMTP_PASS); s.sendmail(SMTP_USER,to_email,msg.as_string())
        return True
    except Exception: return False

def _store_notification(user_id: int, changed: list) -> None:
    if not changed: return
    conn = sqlite3.connect(DB_PATH)
    try:
        tickers = ", ".join(item["ticker"] for item in changed)
        msg = f"Morning brief: {len(changed)} watchlist ticker(s) moved significantly — {tickers}."
        conn.execute("INSERT INTO alert_notifications VALUES (NULL,?,?,?,0,?)",
                     (user_id, tickers.split(",")[0].strip(), msg, datetime.now().isoformat()))
        conn.commit()
    except Exception: pass
    finally: conn.close()

async def send_morning_brief() -> dict:
    users = _get_users_with_watchlists()
    results = {"users_processed":0,"emails_sent":0,"changed_total":0}
    for user in users:
        try:
            brief = await build_brief_content(user)
            changed = brief["changed"]
            results["users_processed"] += 1
            results["changed_total"]   += len(changed)
            _store_notification(user["id"], changed)
            if changed and user.get("email"):
                html = f"<html><body style='font-family:monospace;background:#0A0A0F;color:#CBD5E1;padding:24px'>" \
                       f"<h2 style='color:#3B82F6'>AFDE Brief — {brief['date']}</h2>" \
                       f"<p>Hi {user['username']}, {len(changed)} ticker(s) moved significantly today:</p>" \
                       + "".join(f"<div style='padding:8px;border:1px solid #1E293B;margin:4px 0'>"
                                 f"<strong>{i['ticker']}</strong> — {i.get('flag','')}</div>" for i in changed) \
                       + "<p style='color:#374151;font-size:11px'>Not financial advice.</p></body></html>"
                if _send_email(user["email"], f"AFDE: {len(changed)} watchlist signal(s)", html):
                    results["emails_sent"] += 1
        except Exception: continue
    return results

async def get_brief_preview(user_id: int, username: str, email: str, tickers: list) -> dict:
    user = {"id":user_id,"username":username,"email":email,"tickers":tickers}
    return await build_brief_content(user)
