"""
features/email_notifications.py

All email notification logic for AFDE:

1. send_verdict_email()     — fired after every analysis if user has email + opted in
2. send_morning_brief()     — 7am APScheduler job, watchlist signal checks + price movement
3. send_signout_summary()   — fired on logout, digest of the session's analyses
4. check_signal_reversals() — extended APScheduler job, detects score reversals from memory

Email approach: direct smtplib — no third-party service, no MCP needed.
Gmail setup: Settings → Security → App Passwords → generate one for "AFDE"
.env keys: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, BRIEF_FROM
"""
from __future__ import annotations
import os, sqlite3, smtplib, asyncio, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

_APP_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("AFDE_DB", "/tmp/history.db")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
BRIEF_FROM= os.getenv("BRIEF_FROM", "AFDE <noreply@afde.ai>")


# ── Shared email sender ───────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, html: str) -> bool:
    """Send a single HTML email. Returns True if sent, False if SMTP not configured."""
    if not SMTP_USER or not SMTP_PASS:
        return False   # SMTP not configured — silently skip
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = BRIEF_FROM
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[AFDE email] Failed to send to {to_email}: {e}")
        return False


# ── Email preferences ─────────────────────────────────────────────────────────

def get_email_prefs(user_id: int) -> dict:
    """Return email notification preferences for a user."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT email_verdict, email_morning, email_signout, email_alerts "
            "FROM email_prefs WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            return {"verdict": bool(row[0]), "morning": bool(row[1]),
                    "signout": bool(row[2]),  "alerts":  bool(row[3])}
    except Exception:
        pass
    finally:
        conn.close()
    # Default: all on
    return {"verdict": True, "morning": True, "signout": True, "alerts": True}


def save_email_prefs(user_id: int, verdict: bool, morning: bool,
                     signout: bool, alerts: bool) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO email_prefs VALUES(?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             email_verdict=excluded.email_verdict,
             email_morning=excluded.email_morning,
             email_signout=excluded.email_signout,
             email_alerts=excluded.email_alerts""",
        (user_id, 1 if verdict else 0, 1 if morning else 0,
         1 if signout else 0, 1 if alerts else 0)
    )
    conn.commit()
    conn.close()


def _get_user_email(user_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()


# ── HTML email template ───────────────────────────────────────────────────────

def _html_wrap(title: str, body_html: str) -> str:
    """Wrap content in a consistent dark-themed email template."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0A0A0F;font-family:'Courier New',monospace">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#111827;border:1px solid #1E293B;border-radius:10px;overflow:hidden">

        <!-- Header -->
        <tr><td style="background:#0D0D14;border-bottom:2px solid #1D4ED8;padding:18px 28px">
          <span style="font-size:22px;font-weight:700;color:#E2E8F0;letter-spacing:1px">
            AF<span style="color:#3B82F6">DE</span>
          </span>
          <span style="color:#374151;font-size:11px;margin-left:12px">
            Autonomous Financial Decision Engine
          </span>
          <div style="color:#374151;font-size:10px;margin-top:4px">{title}</div>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:24px 28px;color:#CBD5E1;font-size:13px;line-height:1.7">
          {body_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#0D0D14;border-top:1px solid #1E293B;
                       padding:14px 28px;font-size:10px;color:#374151">
          AI-generated financial analysis for educational purposes only.
          Not financial advice. Always consult a licensed financial advisor
          before making investment decisions.
          <br><br>
          <a href="http://localhost:5000/settings" style="color:#3B82F6">
            Manage email preferences
          </a>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _decision_badge(decision: str) -> str:
    colours = {
        "BUY":  ("#166534", "#4ADE80"),
        "HOLD": ("#78350F", "#FCD34D"),
        "SELL": ("#7F1D1D", "#FCA5A5"),
    }
    bg, fg = colours.get(decision.upper(), ("#1E293B", "#94A3B8"))
    return (f'<span style="background:{bg};color:{fg};padding:3px 10px;'
            f'border-radius:4px;font-weight:700;font-size:12px">{decision}</span>')


# ── 1. VERDICT EMAIL — sent after every single-stock analysis ─────────────────

async def send_verdict_email(result: dict, user_id: int) -> bool:
    """
    Send an analysis verdict email to the user immediately after an analysis.
    Only fires for SINGLE mode (not compare/macro/portfolio).
    """
    if result.get("mode") != "single":
        return False

    prefs = get_email_prefs(user_id)
    if not prefs["verdict"]:
        return False

    email = _get_user_email(user_id)
    if not email:
        return False

    ticker    = result.get("ticker", "")
    decision  = result.get("decision", "")
    conf      = result.get("confidence", 0)
    reasoning = result.get("reasoning", {})
    bull      = result.get("bull_case", "")
    bear      = result.get("bear_case", "")
    regime    = result.get("macro_regime", "")
    rn        = result.get("regime_note", "")
    price     = result.get("alert_price")

    # Build reasoning rows
    reasoning_rows = ""
    for agent, summary in reasoning.items():
        colors = {"fundamental":"#60A5FA","sentiment":"#F472B6",
                  "insider":"#4ADE80","macro":"#A78BFA"}
        col = colors.get(agent, "#94A3B8")
        reasoning_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #1E293B;
                     color:{col};font-weight:700;font-size:11px;white-space:nowrap;
                     vertical-align:top;width:110px">{agent.upper()}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #1E293B;
                     color:#4B5563;font-size:11px;line-height:1.5">{summary[:200]}</td>
        </tr>"""

    price_line = (f'<div style="color:#374151;font-size:11px;margin-top:6px">'
                  f'Price at analysis: <strong style="color:#94A3B8">${price:.2f}</strong>'
                  f'{"  ·  🔔 10% drop alert registered" if decision=="BUY" else ""}'
                  f'</div>') if price else ""

    regime_line = (f'<div style="background:#1A1205;border:1px solid #92400E;'
                   f'border-radius:4px;padding:6px 12px;font-size:10px;color:#FCD34D;margin-top:10px">'
                   f'📊 Macro regime: {regime}'
                   f'{f"  ·  {rn}" if rn else ""}</div>') if regime else ""

    body = f"""
    <p style="margin-bottom:16px">
      Hi, here is your analysis for
      <strong style="color:#E2E8F0">{ticker}</strong>:
    </p>

    <!-- Verdict banner -->
    <div style="background:#0D0D14;border:1px solid #1E293B;border-radius:8px;
                padding:18px 20px;margin-bottom:18px">
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        {_decision_badge(decision)}
        <span style="font-size:22px;font-weight:700;color:#E2E8F0">{ticker}</span>
        <span style="color:#6B7280;font-size:13px">{conf:.0f}% confidence</span>
      </div>
      {price_line}
      {regime_line}
    </div>

    <!-- Agent reasoning -->
    <div style="margin-bottom:18px">
      <div style="color:#374151;font-size:10px;font-weight:700;letter-spacing:1px;
                  text-transform:uppercase;margin-bottom:8px">Agent Signals</div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#0D0D14;border:1px solid #1E293B;border-radius:6px">
        {reasoning_rows}
      </table>
    </div>

    <!-- Bull vs Bear -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px">
      <tr>
        <td width="49%" style="background:#0A1F0A;border:1px solid #166534;
            border-radius:6px;padding:12px;vertical-align:top">
          <div style="color:#4ADE80;font-size:10px;font-weight:700;margin-bottom:6px">
            BULL CASE
          </div>
          <div style="color:#4B5563;font-size:11px;line-height:1.6">{bull[:250]}</div>
        </td>
        <td width="2%"></td>
        <td width="49%" style="background:#1A0808;border:1px solid #991B1B;
            border-radius:6px;padding:12px;vertical-align:top">
          <div style="color:#F87171;font-size:10px;font-weight:700;margin-bottom:6px">
            BEAR CASE
          </div>
          <div style="color:#4B5563;font-size:11px;line-height:1.6">{bear[:250]}</div>
        </td>
      </tr>
    </table>

    <div style="text-align:center;margin-top:20px">
      <a href="http://localhost:5000"
         style="background:#2563EB;color:#fff;padding:10px 24px;border-radius:6px;
                text-decoration:none;font-size:12px;font-weight:600">
        Open AFDE →
      </a>
    </div>
    """

    subject = f"AFDE: {_decision_badge_text(decision)} {ticker} — {conf:.0f}% confidence"
    html    = _html_wrap(
        f"Analysis result · {datetime.now().strftime('%B %d, %Y at %H:%M')}",
        body
    )
    return send_email(email, subject, html)


def _decision_badge_text(decision: str) -> str:
    return {"BUY":"✅ BUY","SELL":"🔴 SELL","HOLD":"🟡 HOLD"}.get(decision.upper(), decision)


# ── 2. MORNING BRIEF — 7am APScheduler, extended with signal reversals ────────

async def _check_signal_reversal(ticker: str, user_id: int) -> dict | None:
    """
    Compare latest stored agent_memory scores against the prior analysis.
    Returns a dict if a meaningful reversal is detected, None otherwise.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # Get last TWO analyses for this ticker
        rows = conn.execute(
            """SELECT agent, score, decision, created
               FROM agent_memory WHERE ticker=? AND user_id=?
               ORDER BY id DESC LIMIT 8""",
            (ticker.upper(), user_id)
        ).fetchall()
    except Exception:
        return None
    finally:
        conn.close()

    if len(rows) < 2:
        return None

    # Group by date (first 4 = latest, next 4 = previous)
    latest   = {r[0]: r[1] for r in rows[:4]}
    previous = {r[0]: r[1] for r in rows[4:8]}
    decision = rows[0][2] if rows else "?"

    reversals = []
    for agent, latest_score in latest.items():
        prior_score = previous.get(agent)
        if prior_score is None:
            continue
        delta = latest_score - prior_score
        if abs(delta) >= 20:   # significant shift threshold
            direction = "improved ↑" if delta > 0 else "weakened ↓"
            reversals.append({
                "agent":     agent,
                "before":    round(prior_score, 0),
                "after":     round(latest_score, 0),
                "delta":     round(delta, 0),
                "direction": direction,
            })

    if not reversals:
        return None

    return {
        "ticker":    ticker,
        "decision":  decision,
        "reversals": reversals,
    }


async def send_morning_brief() -> dict:
    """
    Full morning brief: price movement + signal reversals.
    Replaces the basic version in the old morning_brief.py.
    """
    import yfinance as yf

    conn = sqlite3.connect(DB_PATH)
    try:
        users = conn.execute(
            """SELECT u.id, u.username, u.email,
                      GROUP_CONCAT(w.ticker, ',') as tickers
               FROM users u
               JOIN watchlist w ON w.user_id = u.id
               GROUP BY u.id"""
        ).fetchall()
    except Exception:
        users = []
    finally:
        conn.close()

    results = {"users_processed": 0, "emails_sent": 0}

    for uid, username, email, tickers_str in users:
        if not tickers_str:
            continue

        prefs = get_email_prefs(uid)
        if not prefs["morning"]:
            continue

        tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
        results["users_processed"] += 1

        price_changes = []
        reversals     = []

        # ── Price checks ──────────────────────────────────────────
        async def _fetch(t):
            def _f():
                i = yf.Ticker(t).info
                chg = i.get("regularMarketChangePercent", 0) or 0
                return {
                    "ticker":  t.upper(),
                    "company": i.get("longName", t),
                    "price":   i.get("currentPrice") or i.get("regularMarketPrice"),
                    "chg_pct": round(chg * 100, 2) if abs(chg) < 1 else round(chg, 2),
                }
            try: return await asyncio.get_event_loop().run_in_executor(None, _f)
            except Exception: return None

        price_results = await asyncio.gather(*[_fetch(t) for t in tickers[:8]],
                                             return_exceptions=True)
        for pr in price_results:
            if isinstance(pr, Exception) or not pr:
                continue
            if abs(pr["chg_pct"]) > 2:
                price_changes.append(pr)

        # ── Signal reversal checks ────────────────────────────────
        reversal_results = await asyncio.gather(
            *[_check_signal_reversal(t, uid) for t in tickers[:8]],
            return_exceptions=True
        )
        for rv in reversal_results:
            if rv and not isinstance(rv, Exception):
                reversals.append(rv)

        # ── Store in-app notification ─────────────────────────────
        if price_changes or reversals:
            msgs = []
            for pc in price_changes:
                msgs.append(f"{pc['ticker']} moved {pc['chg_pct']:+.1f}%")
            for rv in reversals:
                agents_str = ", ".join(f"{r['agent']} {r['direction']}" for r in rv["reversals"])
                msgs.append(f"{rv['ticker']} signal changed: {agents_str}")

            conn2 = sqlite3.connect(DB_PATH)
            try:
                conn2.execute(
                    "INSERT INTO alert_notifications VALUES (NULL,?,?,?,0,?)",
                    (uid,
                     (price_changes+reversals)[0].get("ticker",""),
                     "Morning brief: " + " · ".join(msgs[:3]),
                     datetime.now().isoformat())
                )
                conn2.commit()
            except Exception:
                pass
            finally:
                conn2.close()

        # ── Build and send email ──────────────────────────────────
        if not email or (not price_changes and not reversals):
            continue

        price_html = ""
        if price_changes:
            rows_html = "".join(
                f"""<tr>
                  <td style="padding:8px 12px;color:#E2E8F0;font-weight:700">{pc['ticker']}</td>
                  <td style="padding:8px 12px;color:#4B5563">{pc['company'][:30]}</td>
                  <td style="padding:8px 12px;color:{'#4ADE80' if pc['chg_pct']>0 else '#F87171'};
                             font-weight:700">{pc['chg_pct']:+.1f}%</td>
                  <td style="padding:8px 12px;color:#F59E0B;font-size:11px">
                    Re-analysis recommended
                  </td>
                </tr>"""
                for pc in price_changes
            )
            price_html = f"""
            <div style="margin-bottom:18px">
              <div style="color:#F59E0B;font-size:10px;font-weight:700;
                          text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
                ⚠ Price movements (&gt;2%)
              </div>
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#0D0D14;border:1px solid #1E293B;border-radius:6px">
                <tr style="background:#111827">
                  <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Ticker</th>
                  <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Company</th>
                  <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Change</th>
                  <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Action</th>
                </tr>
                {rows_html}
              </table>
            </div>"""

        reversal_html = ""
        if reversals:
            rv_items = ""
            for rv in reversals:
                for r in rv["reversals"]:
                    col = "#4ADE80" if r["delta"] > 0 else "#F87171"
                    rv_items += f"""
                    <div style="padding:8px 12px;border-bottom:1px solid #1E293B">
                      <span style="color:#E2E8F0;font-weight:700">{rv['ticker']}</span>
                      <span style="color:#374151;font-size:11px;margin:0 8px">—</span>
                      <span style="color:#94A3B8;font-size:11px">{r['agent'].upper()}</span>
                      <span style="color:#374151;font-size:11px;margin:0 6px">
                        {r['before']:.0f} →
                      </span>
                      <span style="color:{col};font-weight:700">{r['after']:.0f}</span>
                      <span style="color:{col};font-size:11px;margin-left:6px">
                        {r['direction']}
                      </span>
                    </div>"""
            reversal_html = f"""
            <div style="margin-bottom:18px">
              <div style="color:#EF4444;font-size:10px;font-weight:700;
                          text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
                🔄 Signal reversals detected
              </div>
              <div style="background:#0D0D14;border:1px solid #1E293B;border-radius:6px">
                {rv_items}
              </div>
            </div>"""

        total_flags = len(price_changes) + len(reversals)
        body = f"""
        <p style="margin-bottom:18px">
          Good morning, <strong style="color:#E2E8F0">{username}</strong>.
          AFDE detected <strong style="color:#F59E0B">{total_flags} signal(s)</strong>
          across your watchlist today.
        </p>
        {price_html}
        {reversal_html}
        <div style="text-align:center;margin-top:20px">
          <a href="http://localhost:5000"
             style="background:#2563EB;color:#fff;padding:10px 24px;border-radius:6px;
                    text-decoration:none;font-size:12px;font-weight:600">
            Open AFDE to re-analyse →
          </a>
        </div>"""

        subject = f"AFDE Morning Brief — {total_flags} signal(s) on your watchlist"
        html    = _html_wrap(
            f"Daily watchlist brief · {datetime.now().strftime('%A, %B %d')}",
            body
        )
        if send_email(email, subject, html):
            results["emails_sent"] += 1

    return results


# ── 3. SIGN-OUT SESSION SUMMARY ───────────────────────────────────────────────

def send_signout_summary(user_id: int, username: str, email: str) -> bool:
    """
    Send a session summary email when a user logs out.
    Covers analyses run in the last 24 hours (current session proxy).
    """
    prefs = get_email_prefs(user_id)
    if not prefs["signout"] or not email:
        return False

    conn = sqlite3.connect(DB_PATH)
    try:
        # Analyses from the last 24 hours
        cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        rows = conn.execute(
            """SELECT ticker, decision, confidence, mode, created
               FROM analyses
               WHERE user_id=? AND created >= ?
               ORDER BY id DESC""",
            (user_id, cutoff)
        ).fetchall()
    except Exception:
        return False
    finally:
        conn.close()

    if not rows:
        return False   # nothing done this session — no need to email

    # Summary stats
    decisions = [r[1] for r in rows]
    buy_count  = decisions.count("BUY")
    sell_count = decisions.count("SELL")
    hold_count = decisions.count("HOLD")
    avg_conf   = round(sum(r[2] or 0 for r in rows) / len(rows), 1)

    rows_html = "".join(
        f"""<tr>
          <td style="padding:8px 12px;color:#E2E8F0;font-weight:700">{r[0]}</td>
          <td style="padding:8px 12px">{_decision_badge(r[1])}</td>
          <td style="padding:8px 12px;color:#94A3B8">{r[2]:.0f}%</td>
          <td style="padding:8px 12px;color:#374151;font-size:11px">{r[3]}</td>
          <td style="padding:8px 12px;color:#374151;font-size:11px">{r[4]}</td>
        </tr>"""
        for r in rows
    )

    body = f"""
    <p style="margin-bottom:18px">
      Hi <strong style="color:#E2E8F0">{username}</strong>,
      here is a summary of your AFDE session today.
    </p>

    <!-- Stats -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px">
      <tr>
        <td style="background:#0A1F0A;border:1px solid #166534;border-radius:6px;
                   padding:14px;text-align:center;width:24%">
          <div style="font-size:22px;font-weight:700;color:#22C55E">{buy_count}</div>
          <div style="font-size:10px;color:#374151;margin-top:2px">BUY signals</div>
        </td>
        <td width="2%"></td>
        <td style="background:#1A1205;border:1px solid #92400E;border-radius:6px;
                   padding:14px;text-align:center;width:24%">
          <div style="font-size:22px;font-weight:700;color:#F59E0B">{hold_count}</div>
          <div style="font-size:10px;color:#374151;margin-top:2px">HOLD signals</div>
        </td>
        <td width="2%"></td>
        <td style="background:#1A0808;border:1px solid #991B1B;border-radius:6px;
                   padding:14px;text-align:center;width:24%">
          <div style="font-size:22px;font-weight:700;color:#EF4444">{sell_count}</div>
          <div style="font-size:10px;color:#374151;margin-top:2px">SELL signals</div>
        </td>
        <td width="2%"></td>
        <td style="background:#0D0D14;border:1px solid #1E293B;border-radius:6px;
                   padding:14px;text-align:center;width:24%">
          <div style="font-size:22px;font-weight:700;color:#E2E8F0">{avg_conf}%</div>
          <div style="font-size:10px;color:#374151;margin-top:2px">avg confidence</div>
        </td>
      </tr>
    </table>

    <!-- Analysis table -->
    <div style="color:#374151;font-size:10px;font-weight:700;
                text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
      Analyses this session
    </div>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0D0D14;border:1px solid #1E293B;border-radius:6px;
                  margin-bottom:20px">
      <tr style="background:#111827">
        <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Ticker</th>
        <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Decision</th>
        <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Confidence</th>
        <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Mode</th>
        <th style="padding:7px 12px;color:#374151;font-size:10px;text-align:left">Time</th>
      </tr>
      {rows_html}
    </table>

    <div style="text-align:center">
      <a href="http://localhost:5000"
         style="background:#2563EB;color:#fff;padding:10px 24px;border-radius:6px;
                text-decoration:none;font-size:12px;font-weight:600">
        Return to AFDE →
      </a>
    </div>"""

    subject = f"AFDE Session Summary — {len(rows)} analysis/analyses today"
    html    = _html_wrap(
        f"Session summary · {datetime.now().strftime('%B %d, %Y')}",
        body
    )
    return send_email(email, subject, html)
