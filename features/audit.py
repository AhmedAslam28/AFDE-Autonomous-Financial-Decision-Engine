"""
features/audit.py

Explainability audit trail — every data point links back to its source.

For each signal in the analysis, builds a URL to the exact source document:
  - Revenue figure → SEC EDGAR 10-K filing URL
  - Insider cluster → SEC Form 4 search URL for the ticker
  - Yield curve → FRED series URL
  - VIX → Yahoo Finance ^VIX page
  - News sentiment → Tavily search results (stored in signal data_points)

Returns an audit_trail dict that gets embedded in the final result JSON.
UI renders each data point as a clickable link.
"""

from __future__ import annotations
import re
from datetime import datetime


# ── URL builders ──────────────────────────────────────────────────────

def sec_10k_url(ticker: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=10-K&dateb=&owner=include&count=5"

def sec_form4_url(ticker: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=4&dateb=&owner=include&count=20"

def sec_8k_url(ticker: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=8-K&dateb=&owner=include&count=10"

def fred_yield_url(series: str = "DGS10") -> str:
    return f"https://fred.stlouisfed.org/series/{series}"

def fred_fed_rate_url() -> str:
    return "https://fred.stlouisfed.org/series/FEDFUNDS"

def yahoo_vix_url() -> str:
    return "https://finance.yahoo.com/quote/%5EVIX/"

def yahoo_ticker_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}/"

def yahoo_financials_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}/financials/"


# ── Signal → source mapping ───────────────────────────────────────────

_SIGNAL_PATTERNS = [
    # (regex pattern in data_point text, source_label, url_builder_key)
    (r"revenue|sales|growth",                  "SEC 10-K filing",      "10k"),
    (r"margin|eps|earnings per share|fcf|free cash", "SEC 10-K filing", "10k"),
    (r"p/e|pe ratio|valuation|price.earnings", "Yahoo Finance",        "yahoo"),
    (r"cluster|form 4|insider|buying|selling", "SEC Form 4 filings",   "form4"),
    (r"yield curve|treasury|2y|10y|spread",    "FRED Treasury data",   "fred_yield"),
    (r"fed|federal funds|rate|hiking|cutting|pausing", "FRED Fed Funds", "fred_rate"),
    (r"vix|volatility|fear",                   "CBOE VIX (Yahoo)",     "vix"),
    (r"sentiment|news|analyst|upgrade|downgrade", "News search",       "news"),
]


def _url_for_key(key: str, ticker: str) -> str:
    mapping = {
        "10k":       sec_10k_url(ticker),
        "form4":     sec_form4_url(ticker),
        "yahoo":     yahoo_financials_url(ticker),
        "fred_yield": fred_yield_url("DGS10"),
        "fred_rate": fred_fed_rate_url(),
        "vix":       yahoo_vix_url(),
        "news":      f"https://finance.yahoo.com/quote/{ticker}/news/",
    }
    return mapping.get(key, yahoo_ticker_url(ticker))


def build_audit_trail(
    ticker: str,
    signals: dict,          # agent_name → AgentSignal
    decision: str,
    timestamp: str,
    doc_filename: str | None = None,
) -> dict:
    """
    Build a full audit trail for a completed analysis.
    Returns dict with per-agent source links and data point annotations.
    """
    trail = {
        "ticker":     ticker,
        "decision":   decision,
        "timestamp":  timestamp,
        "agents":     {},
        "sources_used": [],
    }

    sources_seen = set()

    for agent_name, sig in signals.items():
        if hasattr(sig, 'data_points'):
            data_points = sig.data_points
            source      = getattr(sig, 'source', 'live')
            summary     = sig.summary
        else:
            data_points = sig.get('data_points', [])
            source      = sig.get('source', 'live')
            summary     = sig.get('summary', '')

        annotated_points = []
        for dp in data_points:
            dp_lower  = dp.lower()
            url_key   = "yahoo"
            src_label = "Yahoo Finance"

            for pattern, label, key in _SIGNAL_PATTERNS:
                if re.search(pattern, dp_lower):
                    src_label = label
                    url_key   = key
                    break

            # Document source overrides live source
            if source == "document" and doc_filename:
                src_label = f"Uploaded: {doc_filename}"
                url       = None
            else:
                url = _url_for_key(url_key, ticker)

            annotated_points.append({
                "text":   dp,
                "source": src_label,
                "url":    url,
            })
            sources_seen.add(src_label)

        # Agent-level source link
        agent_source_url = {
            "fundamental": sec_10k_url(ticker),
            "insider":     sec_form4_url(ticker),
            "macro":       fred_yield_url(),
            "sentiment":   f"https://finance.yahoo.com/quote/{ticker}/news/",
        }.get(agent_name, yahoo_ticker_url(ticker))

        trail["agents"][agent_name] = {
            "source_label": source,
            "source_url":   agent_source_url,
            "data_points":  annotated_points,
            "summary":      summary,
        }

    trail["sources_used"] = sorted(sources_seen)

    # Add standard reference links
    trail["reference_links"] = {
        "SEC EDGAR filings":  sec_10k_url(ticker),
        "SEC Form 4 insider": sec_form4_url(ticker),
        "Yahoo Finance":      yahoo_financials_url(ticker),
        "FRED macro data":    fred_yield_url(),
    }

    return trail
