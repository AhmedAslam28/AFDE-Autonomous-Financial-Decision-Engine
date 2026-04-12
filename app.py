"""
app.py — AFDE Flask application — all 9 new features integrated.
"""
from __future__ import annotations
import asyncio, json, os, sqlite3, uuid, sys, hashlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import (Flask, render_template, request, jsonify, Response,
                   stream_with_context, redirect, url_for, flash)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)

from engine import run_afde
from document_processor import process_uploaded_file
from config import OPENAI_API_KEY

from features.streaming     import create_session, get_events
from features.alerts        import (get_active_alerts, get_notifications,
                                    mark_notification_read, dismiss_alert,
                                    check_all_alerts, register_alert)
from features.macro_regime  import get_current_regime, classify_regime
from features.memory        import get_ticker_history_summary, get_memory_context
from features.url_research  import fetch_url_content
from features.backtest      import (store_decision, check_outcomes,
                                    get_accuracy_stats, get_pending_decisions)
from features.morning_brief      import get_brief_preview
from features.email_notifications import (
    send_morning_brief, send_verdict_email, send_signout_summary,
    get_email_prefs, save_email_prefs,
)
from features.pdf_export    import generate_pdf
from features.plain_english import simplify_analysis
from features.ticker_search import search_tickers, get_ticker_info

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "afde-change-in-prod")

UPLOAD_FOLDER     = Path("uploads"); UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXT       = {".pdf",".csv"}
DB_PATH           = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.db")

# ── Auth ────────────────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login_page"

class User(UserMixin):
    def __init__(self, id, username, email):
        self.id=id; self.username=username; self.email=email

@login_manager.user_loader
def load_user(uid):
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute("SELECT id,username,email FROM users WHERE id=?",(uid,)).fetchone()
    conn.close()
    return User(*row) if row else None

# ── DB ───────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    stmts = [
        """CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,
           username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,
           password TEXT NOT NULL,created TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER DEFAULT 0,ticker TEXT,goal TEXT,decision TEXT,
           confidence REAL,mode TEXT,loops_run INTEGER,
           has_document INTEGER DEFAULT 0,doc_filename TEXT,
           result_json TEXT,created TEXT)""",
        """CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER NOT NULL,ticker TEXT NOT NULL,added TEXT NOT NULL,
           UNIQUE(user_id,ticker))""",
        """CREATE TABLE IF NOT EXISTS user_profiles(user_id INTEGER PRIMARY KEY,
           investor_type TEXT DEFAULT 'general',sectors_interest TEXT DEFAULT '[]',
           has_portfolio INTEGER DEFAULT 0,onboarding_done INTEGER DEFAULT 0,updated TEXT)""",
        """CREATE TABLE IF NOT EXISTS price_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER DEFAULT 0,ticker TEXT NOT NULL,decision TEXT NOT NULL,
           analysis_price REAL NOT NULL,alert_threshold REAL NOT NULL,
           current_price REAL,status TEXT DEFAULT 'active',triggered_at TEXT,created TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS alert_notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER DEFAULT 0,ticker TEXT NOT NULL,message TEXT NOT NULL,
           read INTEGER DEFAULT 0,created TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS agent_memory(id INTEGER PRIMARY KEY AUTOINCREMENT,
           ticker TEXT NOT NULL,user_id INTEGER DEFAULT 0,agent TEXT NOT NULL,
           score REAL,confidence REAL,summary TEXT,data_points TEXT,
           source TEXT,decision TEXT,created TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS macro_regime(id INTEGER PRIMARY KEY,
           regime TEXT NOT NULL,confidence REAL NOT NULL,reasoning TEXT,
           vix REAL,yield_curve TEXT,fed_stance TEXT,updated TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS decision_outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER DEFAULT 0,ticker TEXT NOT NULL,decision TEXT NOT NULL,
           confidence REAL,price_at_decision REAL,price_at_30d REAL,return_30d REAL,
           outcome TEXT DEFAULT 'pending',decision_date TEXT NOT NULL,outcome_date TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_mem_ticker ON agent_memory(ticker)",
        """CREATE TABLE IF NOT EXISTS email_prefs(
           user_id INTEGER PRIMARY KEY,
           email_verdict INTEGER DEFAULT 1,
           email_morning INTEGER DEFAULT 1,
           email_signout INTEGER DEFAULT 1,
           email_alerts  INTEGER DEFAULT 1)""",
        "CREATE INDEX IF NOT EXISTS idx_mem_user   ON agent_memory(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pw_ticker  ON price_alerts(ticker)",
    ]
    for s in stmts:
        conn.execute(s)
    conn.commit(); conn.close()

def save_result(result: dict, user_id:int=0, has_document:bool=False, doc_filename:str=""):
    conn = sqlite3.connect(DB_PATH)
    mode = result.get("mode","single")
    ticker = result.get("ticker", result.get("winner",
             (result.get("holdings_analysed",["PORTFOLIO"])[0] if mode=="portfolio" else "MACRO")))
    decision = result.get("decision", result.get("overall_stance",
               result.get("winner_decision", result.get("overall_risk","?"))))
    conn.execute("INSERT INTO analyses VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, ticker, result.get("goal",""), decision, result.get("confidence",0),
         mode, result.get("loops_run",0), 1 if has_document else 0, doc_filename,
         json.dumps(result), datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()

def get_history(user_id:int=0, limit:int=30) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ticker,decision,confidence,mode,created,loops_run,has_document,doc_filename "
        "FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id,limit)).fetchall()
    conn.close()
    return [{"ticker":r[0],"decision":r[1],"confidence":r[2],"mode":r[3],
             "created":r[4],"loops_run":r[5],"has_document":bool(r[6]),"doc_filename":r[7] or ""} for r in rows]

def get_watchlist(user_id:int) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added DESC",(user_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_uid(): return current_user.id if current_user.is_authenticated else 0
def allowed_file(f): return Path(f).suffix.lower() in ALLOWED_EXT

# ── APScheduler ──────────────────────────────────────────────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(classify_regime()),    "cron", hour=7, minute=0,  id="macro")
    scheduler.add_job(lambda: asyncio.run(check_all_alerts()),   "cron", hour=8, minute=0,  id="alerts")
    scheduler.add_job(lambda: asyncio.run(check_outcomes()),     "cron", hour=8, minute=30, id="backtest")
    scheduler.add_job(lambda: asyncio.run(send_morning_brief()), "cron", hour=7, minute=30, id="brief")
    scheduler.start()
except Exception:
    pass

# ── Auth routes ──────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login_page():
    if request.method == "POST":
        pw   = hashlib.sha256(request.form.get("password","").encode()).hexdigest()
        conn = sqlite3.connect(DB_PATH)
        row  = conn.execute("SELECT id,username,email FROM users WHERE username=? AND password=?",
                            (request.form.get("username",""), pw)).fetchone()
        conn.close()
        if row: login_user(User(*row)); return redirect(url_for("index"))
        flash("Invalid username or password")
    return render_template("login.html")

@app.route("/register", methods=["GET","POST"])
def register_page():
    if request.method == "POST":
        pw = hashlib.sha256(request.form.get("password","").encode()).hexdigest()
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO users VALUES (NULL,?,?,?,?)",
                         (request.form.get("username",""), request.form.get("email",""),
                          pw, datetime.now().isoformat()))
            conn.commit()
            row = conn.execute("SELECT id,username,email FROM users WHERE username=?",
                               (request.form.get("username",""),)).fetchone()
            conn.close()
            login_user(User(*row)); return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash("Username or email already exists")
    return render_template("register.html")

@app.route("/logout")
def logout():
    if current_user.is_authenticated:
        uid      = current_user.id
        username = current_user.username
        email    = current_user.email
        # Send session summary email in background thread (non-blocking)
        import threading
        threading.Thread(
            target=send_signout_summary,
            args=(uid, username, email),
            daemon=True
        ).start()
    logout_user()
    return redirect(url_for("login_page"))

# ── Main routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    uid = get_uid()
    return render_template("index.html",
        history=get_history(uid), regime=get_current_regime(),
        alerts=get_active_alerts(uid) if uid else [],
        notifications=get_notifications(uid, unread_only=True) if uid else [],
        watchlist=get_watchlist(uid) if uid else [],
        unread_count=len(get_notifications(uid, unread_only=True)) if uid else 0)

@app.route("/analyse", methods=["POST"])
def analyse():
    data = request.get_json(silent=True) or {}
    goal = data.get("goal","").strip()
    sid  = data.get("session_id","")
    if not goal: return jsonify({"error":"No goal provided"}),400
    if not OPENAI_API_KEY: return jsonify({"error":"OPENAI_API_KEY not configured"}),503
    try:
        uid    = get_uid()
        result = asyncio.run(run_afde(goal, verbose=False, session_id=sid, user_id=uid))
        save_result(result, uid)
        return jsonify(result)
    except ValueError as e: return jsonify({"error":str(e)}),400
    except Exception as e:  return jsonify({"error":f"Engine error: {e}"}),500

@app.route("/upload", methods=["POST"])
def upload():
    if not OPENAI_API_KEY: return jsonify({"error":"OPENAI_API_KEY not configured"}),503
    goal = request.form.get("goal","").strip()
    sid  = request.form.get("session_id","")
    if "file" not in request.files: return jsonify({"error":"No file uploaded"}),400
    file = request.files["file"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error":"Only .pdf and .csv files supported"}),400
    ext      = Path(file.filename).suffix.lower()
    filepath = str(UPLOAD_FOLDER / f"{uuid.uuid4().hex}{ext}")
    file.save(filepath)
    try:
        uid = get_uid()
        doc = asyncio.run(process_uploaded_file(filepath))
        if not goal:
            goal = ("Analyse my portfolio risk" if ext==".csv"
                    else f"Analyse {doc.ticker_hint or 'this company'} from the document")
        result = asyncio.run(run_afde(goal, verbose=False, doc_context=doc, session_id=sid, user_id=uid))
        result["uploaded_file"]         = file.filename
        result["doc_type"]              = doc.doc_type.value
        result["extraction_confidence"] = round(doc.extraction_confidence, 2)
        save_result(result, uid, has_document=True, doc_filename=file.filename)
        return jsonify(result)
    except ValueError as e: return jsonify({"error":str(e)}),400
    except Exception as e:  return jsonify({"error":f"Processing error: {e}"}),500
    finally:
        try: os.remove(filepath)
        except: pass

@app.route("/stream/<sid>")
def stream(sid: str):
    create_session(sid)
    @stream_with_context
    def gen():
        yield ": connected\n\n"
        yield from get_events(sid)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── Profile / onboarding ─────────────────────────────────────────────────────
@app.route("/profile", methods=["GET","POST"])
def profile():
    uid = get_uid()
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """INSERT INTO user_profiles VALUES(?,?,?,?,1,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 investor_type=excluded.investor_type,sectors_interest=excluded.sectors_interest,
                 has_portfolio=excluded.has_portfolio,onboarding_done=1,updated=excluded.updated""",
            (uid, d.get("investor_type","general"), json.dumps(d.get("sectors_interest",[])),
             1 if d.get("has_portfolio") else 0, datetime.now().isoformat()))
        conn.commit(); conn.close()
        return jsonify({"status":"saved"})
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute("SELECT investor_type,sectors_interest,has_portfolio,onboarding_done "
                        "FROM user_profiles WHERE user_id=?",(uid,)).fetchone()
    conn.close()
    if not row: return jsonify({"investor_type":"general","sectors_interest":[],"has_portfolio":False,"onboarding_done":False})
    return jsonify({"investor_type":row[0],"sectors_interest":json.loads(row[1] or "[]"),
                    "has_portfolio":bool(row[2]),"onboarding_done":bool(row[3])})

# ── New AI feature routes ────────────────────────────────────────────────────
@app.route("/plain_english", methods=["POST"])
def plain_english_route():
    data = request.get_json(silent=True) or {}
    result = data.get("result",{})
    if not result: return jsonify({"error":"No result"}),400
    try:    return jsonify(asyncio.run(simplify_analysis(result)))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/what_would_change", methods=["POST"])
def what_would_change():
    from config import WHAT_WOULD_CHANGE_PROMPT
    from openai import OpenAI
    data   = request.get_json(silent=True) or {}
    result = data.get("result",{})
    if not result: return jsonify({"error":"No result"}),400
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role":"system","content":WHAT_WOULD_CHANGE_PROMPT},
                {"role":"user",  "content":json.dumps({
                    "ticker":result.get("ticker",""),"decision":result.get("decision",""),
                    "confidence":result.get("confidence",0),"reasoning":result.get("reasoning",{}),
                    "bull_case":result.get("bull_case",""),"bear_case":result.get("bear_case",""),
                    "signals_used":result.get("signals_used",[]),})},
            ],
            response_format={"type":"json_object"}, temperature=0.1)
        return jsonify(json.loads(resp.choices[0].message.content))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/follow_up_questions", methods=["POST"])
def follow_up_questions():
    from config import FOLLOW_UP_PROMPT
    from openai import OpenAI
    data   = request.get_json(silent=True) or {}
    result = data.get("result",{})
    if not result: return jsonify({"error":"No result"}),400
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role":"system","content":FOLLOW_UP_PROMPT},
                {"role":"user",  "content":json.dumps({
                    "ticker":result.get("ticker",""),"decision":result.get("decision",""),
                    "mode":result.get("mode","single"),"reasoning":result.get("reasoning",{}),
                    "macro_regime":result.get("macro_regime",""),})},
            ],
            response_format={"type":"json_object"}, temperature=0.4)
        out = json.loads(resp.choices[0].message.content)
        return jsonify({"questions":out.get("questions",[])})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/whats_changed/<ticker>")
def whats_changed(ticker: str):
    from config import WHATS_CHANGED_PROMPT
    from openai import OpenAI
    uid     = get_uid()
    mem_ctx = get_memory_context(ticker.upper(), uid)
    if not mem_ctx:
        return jsonify({"message":f"No prior analysis found for {ticker.upper()}."})
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role":"system","content":WHATS_CHANGED_PROMPT},
                {"role":"user",  "content":f"Ticker: {ticker.upper()}\n\n{mem_ctx}"},
            ],
            response_format={"type":"json_object"}, temperature=0.1)
        return jsonify(json.loads(resp.choices[0].message.content))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/pdf", methods=["POST"])
def export_pdf():
    import traceback as _tb
    data   = request.get_json(silent=True) or {}
    result = data.get("result",{})
    if not result: return jsonify({"error":"No result provided"}),400
    try:
        pdf    = generate_pdf(result)
        if not pdf or len(pdf) < 100:
            return jsonify({"error":"PDF generation returned empty output"}),500
        ticker = result.get("ticker","analysis")
        fname  = f"afde_{ticker}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition":f"attachment; filename={fname}"})
    except ImportError as e:
        return jsonify({"error":f"PDF library missing: {e}. Run: pip install reportlab"}),500
    except Exception as e:
        app.logger.error(f"PDF generation failed: {e}\n{_tb.format_exc()}")
        return jsonify({"error":f"PDF generation failed: {e}"}),500

@app.route("/backtest")
def backtest_stats():
    uid = get_uid()
    return jsonify({"stats":get_accuracy_stats(uid),"pending":get_pending_decisions(uid)})

@app.route("/backtest/resolve", methods=["POST"])
def backtest_resolve():
    try:    return jsonify({"resolved":asyncio.run(check_outcomes())})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/ticker_search")
def ticker_search_route():
    q = request.args.get("q","").strip()
    return jsonify({"results":search_tickers(q, limit=6)})

@app.route("/ticker_info/<ticker>")
def ticker_info_route(ticker:str):
    try:    return jsonify(asyncio.run(get_ticker_info(ticker.upper())))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/brief_preview")
def brief_preview():
    uid = get_uid()
    if not current_user.is_authenticated: return jsonify({"error":"Login required"}),401
    tickers = get_watchlist(uid)
    if not tickers: return jsonify({"message":"Add tickers to your watchlist first."})
    try:    return jsonify(asyncio.run(get_brief_preview(uid, current_user.username, current_user.email, tickers)))
    except Exception as e: return jsonify({"error":str(e)}),500

# ── Watchlist ────────────────────────────────────────────────────────────────
@app.route("/watchlist/add", methods=["POST"])
@login_required
def watchlist_add():
    ticker = (request.get_json(silent=True) or {}).get("ticker","").upper().strip()
    if not ticker: return jsonify({"error":"No ticker"}),400
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT OR IGNORE INTO watchlist VALUES(NULL,?,?,?)",
                     (current_user.id, ticker, datetime.now().isoformat()))
        conn.commit()
    except Exception: pass
    finally: conn.close()
    return jsonify({"status":"added","ticker":ticker})

@app.route("/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    ticker = (request.get_json(silent=True) or {}).get("ticker","").upper().strip()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM watchlist WHERE user_id=? AND ticker=?",(current_user.id,ticker))
    conn.commit(); conn.close()
    return jsonify({"status":"removed","ticker":ticker})

@app.route("/watchlist")
@login_required
def watchlist_list():
    return jsonify({"tickers":get_watchlist(current_user.id)})

# ── Alerts ───────────────────────────────────────────────────────────────────
@app.route("/alerts")
def alerts_list():
    uid = get_uid()
    return jsonify({"alerts":get_active_alerts(uid),"notifications":get_notifications(uid)})

@app.route("/alerts/dismiss/<int:aid>", methods=["POST"])
def alert_dismiss(aid:int):
    from features.alerts import dismiss_alert
    dismiss_alert(aid); return jsonify({"status":"dismissed"})

@app.route("/notifications/read/<int:nid>", methods=["POST"])
def notif_read(nid:int):
    mark_notification_read(nid); return jsonify({"status":"read"})

# ── Other ────────────────────────────────────────────────────────────────────
@app.route("/history")
def history():
    return jsonify(get_history(get_uid(),50))

@app.route("/macro_regime")
def macro_regime_route():
    return jsonify(get_current_regime())

@app.route("/ticker_history/<ticker>")
def ticker_history(ticker:str):
    return jsonify(get_ticker_history_summary(ticker.upper(), get_uid()))

@app.route("/clear", methods=["POST"])
def clear():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM analyses WHERE user_id=?",(get_uid(),))
    conn.commit(); conn.close()
    return jsonify({"status":"cleared"})

@app.route("/research_url", methods=["POST"])
def research_url():
    from urllib.parse import urlparse
    data = request.get_json(silent=True) or {}
    url  = data.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}),400
    blocked = ["reuters.com","bloomberg.com","wsj.com","ft.com","barrons.com","seekingalpha.com"]
    domain  = urlparse(url).netloc.lower().replace("www.","")
    if any(d in domain for d in blocked):
        return jsonify({"error":f"{domain} blocks automated access. Try: CNBC, MarketWatch, or Reddit.","blocked":True}),400
    try:
        ctx = asyncio.run(fetch_url_content(url))
        if not ctx or ctx.word_count < 50:
            return jsonify({"error":f"Could not fetch useful content from {domain}."}),400
        return jsonify({"title":ctx.title,"domain":ctx.domain,"word_count":ctx.word_count,
                        "snippet":ctx.text[:400],"is_news":ctx.is_news,"is_reddit":ctx.is_reddit})
    except Exception as e: return jsonify({"error":str(e)}),500

# ── Email preferences routes ─────────────────────────────────────────────────
@app.route("/email_prefs", methods=["GET"])
def email_prefs_get():
    return jsonify(get_email_prefs(get_uid()))

@app.route("/email_prefs", methods=["POST"])
def email_prefs_save():
    d = request.get_json(silent=True) or {}
    save_email_prefs(
        get_uid(),
        verdict=d.get("verdict", True),
        morning=d.get("morning", True),
        signout=d.get("signout", True),
        alerts =d.get("alerts",  True),
    )
    return jsonify({"status": "saved"})

# ── Test email routes (for manual testing) ──────────────────────────────────
@app.route("/test_brief", methods=["POST"])
def test_brief():
    """Manually trigger morning brief for the current user — for testing."""
    try:
        result = asyncio.run(send_morning_brief())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status":"ok","openai":bool(OPENAI_API_KEY),"regime":get_current_regime().get("regime")})

if __name__ == "__main__":
    init_db()
    print("AFDE → http://localhost:5000")
    app.run(debug=False, port=5000)