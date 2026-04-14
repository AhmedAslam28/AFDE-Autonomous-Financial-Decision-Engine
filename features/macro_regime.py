"""
features/macro_regime.py

Daily macro regime classifier.

Runs once per day via APScheduler, labels the current market environment,
and adjusts all subsequent analysis confidence scores accordingly.

Regimes:
  RISK_ON_BULL   → yield curve normal, Fed cutting/pausing, VIX < 18
  RATE_SHOCK     → Fed hiking rapidly, yields inverted or rising fast
  STAGFLATION    → inflation high, growth slowing, VIX elevated
  RECESSION      → yield curve inverted, VIX > 25, macro deteriorating
  NEUTRAL        → mixed signals, no clear regime

Confidence adjustments:
  BUY  in RISK_ON_BULL   → +8 confidence points
  BUY  in RECESSION      → -15 confidence points
  SELL in RECESSION      → +8 confidence points
  SELL in RISK_ON_BULL   → -8 confidence points
  HOLD in any regime     → ±3 (minimal impact)
"""

from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from enum import Enum

DB_PATH = os.getenv("AFDE_DB", "/tmp/history.db")


class MacroRegime(str, Enum):
    RISK_ON_BULL = "Risk-on bull market"
    RATE_SHOCK   = "Rate shock / hawkish Fed"
    STAGFLATION  = "Stagflation"
    RECESSION    = "Recession / contraction"
    NEUTRAL      = "Neutral / mixed signals"


# Confidence adjustments: (decision, regime) → delta
REGIME_ADJUSTMENTS: dict[tuple[str, MacroRegime], float] = {
    ("BUY",  MacroRegime.RISK_ON_BULL): +8.0,
    ("BUY",  MacroRegime.RECESSION):   -15.0,
    ("BUY",  MacroRegime.RATE_SHOCK):   -8.0,
    ("BUY",  MacroRegime.STAGFLATION):  -5.0,
    ("SELL", MacroRegime.RECESSION):    +8.0,
    ("SELL", MacroRegime.RISK_ON_BULL): -8.0,
    ("HOLD", MacroRegime.RISK_ON_BULL): +3.0,
    ("HOLD", MacroRegime.RECESSION):    -3.0,
}


def _init_regime_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_regime (
            id          INTEGER PRIMARY KEY,
            regime      TEXT NOT NULL,
            confidence  REAL NOT NULL,
            reasoning   TEXT,
            vix         REAL,
            yield_curve TEXT,
            fed_stance  TEXT,
            updated     TEXT NOT NULL
        )
    """)
    conn.commit()


def get_current_regime() -> dict:
    """Return the latest stored macro regime. Falls back to NEUTRAL if not set."""
    try:
        conn = sqlite3.connect(DB_PATH)
        _init_regime_table(conn)
        row = conn.execute(
            "SELECT regime, confidence, reasoning, vix, yield_curve, fed_stance, updated "
            "FROM macro_regime ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return {
                "regime":      row[0],
                "confidence":  row[1],
                "reasoning":   row[2],
                "vix":         row[3],
                "yield_curve": row[4],
                "fed_stance":  row[5],
                "updated":     row[6],
            }
    except Exception:
        pass
    return {
        "regime":      MacroRegime.NEUTRAL.value,
        "confidence":  50.0,
        "reasoning":   "No macro regime data yet. Will update on first daily run.",
        "vix":         None,
        "yield_curve": None,
        "fed_stance":  None,
        "updated":     None,
    }


def save_regime(regime: MacroRegime, confidence: float, reasoning: str,
                vix: float | None, yield_curve: str | None, fed_stance: str | None) -> None:
    conn = sqlite3.connect(DB_PATH)
    _init_regime_table(conn)
    conn.execute(
        "INSERT INTO macro_regime VALUES (NULL,?,?,?,?,?,?,?)",
        (regime.value, confidence, reasoning, vix, yield_curve, fed_stance,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


async def classify_regime() -> dict:
    """
    Fetch live macro data and classify the current market regime.
    Called by APScheduler daily at 7am.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from openai import AsyncOpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL

    # Fetch raw macro data
    try:
        import httpx
        import yfinance as yf

        # Yield curve
        fred_key = os.getenv("FRED_API_KEY", "")
        yields   = {}
        if fred_key:
            async with httpx.AsyncClient(timeout=15) as client:
                for label, sid in {"2Y": "DGS2", "10Y": "DGS10"}.items():
                    try:
                        r = await client.get(
                            f"https://api.stlouisfed.org/fred/series/observations"
                            f"?series_id={sid}&api_key={fred_key}&limit=1&sort_order=desc&file_type=json"
                        )
                        obs = r.json().get("observations", [])
                        val = obs[-1]["value"] if obs else "."
                        yields[label] = float(val) if val != "." else None
                    except Exception:
                        yields[label] = None

                # Fed rate
                try:
                    r = await client.get(
                        f"https://api.stlouisfed.org/fred/series/observations"
                        f"?series_id=FEDFUNDS&api_key={fred_key}&limit=4&sort_order=desc&file_type=json"
                    )
                    obs = [float(o["value"]) for o in r.json().get("observations", [])
                           if o.get("value", ".") != "."]
                    fed_rate    = obs[0] if obs else None
                    fed_stance  = ("hiking" if len(obs)>=2 and obs[0]>obs[-1]
                                   else "cutting" if len(obs)>=2 and obs[0]<obs[-1]
                                   else "pausing")
                except Exception:
                    fed_rate, fed_stance = None, "unknown"

        # VIX
        import asyncio
        def _vix():
            hist = yf.Ticker("^VIX").history(period="1d")
            return float(hist["Close"].iloc[-1]) if not hist.empty else None
        vix = await asyncio.get_event_loop().run_in_executor(None, _vix)

        spread = None
        if yields.get("10Y") and yields.get("2Y"):
            spread = round(yields["10Y"] - yields["2Y"], 3)
        curve_shape = ("inverted" if spread and spread < -0.1
                       else "flat" if spread and spread < 0.3
                       else "normal" if spread else "unknown")

        macro_summary = f"""
Current macro data:
- 2Y yield: {yields.get('2Y')}%
- 10Y yield: {yields.get('10Y')}%
- 2s10s spread: {spread} ({curve_shape})
- Fed funds rate: {fed_rate}% — trajectory: {fed_stance}
- VIX: {vix} ({'extreme fear' if vix and vix>30 else 'elevated' if vix and vix>20 else 'normal' if vix and vix>15 else 'complacency'})
"""
    except Exception as e:
        macro_summary = f"Could not fetch live macro data: {e}"
        curve_shape  = "unknown"
        fed_stance   = "unknown"
        vix          = None

    # Ask LLM to classify regime
    llm = AsyncOpenAI(api_key=OPENAI_API_KEY)
    resp = await llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a macro regime classifier. Given current macro data, "
                "classify the regime as exactly one of: "
                "'Risk-on bull market', 'Rate shock / hawkish Fed', "
                "'Stagflation', 'Recession / contraction', 'Neutral / mixed signals'. "
                "Return JSON: {\"regime\": \"...\", \"confidence\": 0-100, \"reasoning\": \"2-3 sentences\"}"
            )},
            {"role": "user", "content": macro_summary},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    result     = json.loads(resp.choices[0].message.content)
    regime_str = result.get("regime", MacroRegime.NEUTRAL.value)

    # Map string to enum
    regime_map = {r.value: r for r in MacroRegime}
    regime     = regime_map.get(regime_str, MacroRegime.NEUTRAL)

    save_regime(
        regime, float(result.get("confidence", 50)),
        result.get("reasoning", ""), vix, curve_shape, fed_stance
    )

    return {
        "regime":     regime.value,
        "confidence": float(result.get("confidence", 50)),
        "reasoning":  result.get("reasoning", ""),
        "updated":    datetime.now().isoformat(),
    }


def apply_regime_adjustment(decision: str, confidence: float) -> tuple[float, str]:
    """
    Adjust confidence score based on current macro regime.
    Returns (adjusted_confidence, adjustment_note).
    """
    regime_data = get_current_regime()
    regime_str  = regime_data.get("regime", MacroRegime.NEUTRAL.value)
    regime_map  = {r.value: r for r in MacroRegime}
    regime      = regime_map.get(regime_str, MacroRegime.NEUTRAL)

    delta = REGIME_ADJUSTMENTS.get((decision.upper(), regime), 0.0)
    if delta == 0:
        return confidence, ""

    adjusted = round(min(max(confidence + delta, 5), 99), 1)
    direction = f"+{delta:.0f}" if delta > 0 else f"{delta:.0f}"
    note = f"Regime adjustment ({regime.value}): {direction} pts → {adjusted}%"
    return adjusted, note
