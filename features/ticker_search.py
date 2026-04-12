"""features/ticker_search.py — Ticker autocomplete and live price lookup."""
from __future__ import annotations
import asyncio

POPULAR = [
    {"ticker":"AAPL","name":"Apple Inc.","sector":"Technology","logo":"https://logo.clearbit.com/apple.com"},
    {"ticker":"MSFT","name":"Microsoft Corporation","sector":"Technology","logo":"https://logo.clearbit.com/microsoft.com"},
    {"ticker":"GOOGL","name":"Alphabet Inc.","sector":"Technology","logo":"https://logo.clearbit.com/google.com"},
    {"ticker":"AMZN","name":"Amazon.com Inc.","sector":"Consumer Discretionary","logo":"https://logo.clearbit.com/amazon.com"},
    {"ticker":"NVDA","name":"NVIDIA Corporation","sector":"Technology","logo":"https://logo.clearbit.com/nvidia.com"},
    {"ticker":"META","name":"Meta Platforms Inc.","sector":"Technology","logo":"https://logo.clearbit.com/meta.com"},
    {"ticker":"TSLA","name":"Tesla Inc.","sector":"Consumer Discretionary","logo":"https://logo.clearbit.com/tesla.com"},
    {"ticker":"JPM","name":"JPMorgan Chase & Co.","sector":"Financials","logo":"https://logo.clearbit.com/jpmorganchase.com"},
    {"ticker":"JNJ","name":"Johnson & Johnson","sector":"Healthcare","logo":"https://logo.clearbit.com/jnj.com"},
    {"ticker":"V","name":"Visa Inc.","sector":"Financials","logo":"https://logo.clearbit.com/visa.com"},
    {"ticker":"BRK-B","name":"Berkshire Hathaway","sector":"Financials","logo":"https://logo.clearbit.com/berkshirehathaway.com"},
    {"ticker":"XOM","name":"Exxon Mobil Corp.","sector":"Energy","logo":"https://logo.clearbit.com/exxonmobil.com"},
    {"ticker":"AMD","name":"Advanced Micro Devices","sector":"Technology","logo":"https://logo.clearbit.com/amd.com"},
    {"ticker":"NFLX","name":"Netflix Inc.","sector":"Communication Services","logo":"https://logo.clearbit.com/netflix.com"},
    {"ticker":"INTC","name":"Intel Corporation","sector":"Technology","logo":"https://logo.clearbit.com/intel.com"},
    {"ticker":"CRM","name":"Salesforce Inc.","sector":"Technology","logo":"https://logo.clearbit.com/salesforce.com"},
    {"ticker":"PLTR","name":"Palantir Technologies","sector":"Technology","logo":"https://logo.clearbit.com/palantir.com"},
    {"ticker":"UBER","name":"Uber Technologies","sector":"Technology","logo":"https://logo.clearbit.com/uber.com"},
    {"ticker":"COIN","name":"Coinbase Global","sector":"Financials","logo":"https://logo.clearbit.com/coinbase.com"},
    {"ticker":"SHOP","name":"Shopify Inc.","sector":"Technology","logo":"https://logo.clearbit.com/shopify.com"},
    {"ticker":"SQ","name":"Block Inc.","sector":"Financials","logo":"https://logo.clearbit.com/block.xyz"},
    {"ticker":"SPOT","name":"Spotify Technology","sector":"Communication Services","logo":"https://logo.clearbit.com/spotify.com"},
    {"ticker":"PFE","name":"Pfizer Inc.","sector":"Healthcare","logo":"https://logo.clearbit.com/pfizer.com"},
    {"ticker":"BAC","name":"Bank of America Corp.","sector":"Financials","logo":"https://logo.clearbit.com/bankofamerica.com"},
    {"ticker":"DIS","name":"Walt Disney Co.","sector":"Communication Services","logo":"https://logo.clearbit.com/disney.com"},
]

def search_tickers(query: str, limit: int = 6) -> list[dict]:
    if not query:
        return POPULAR[:limit]
    q = query.upper().strip()
    results, seen = [], set()
    def _add(t):
        if t["ticker"] not in seen:
            seen.add(t["ticker"]); results.append(t)
    for t in POPULAR:
        if t["ticker"] == q: _add(t)
    for t in POPULAR:
        if t["ticker"].startswith(q): _add(t)
    ql = query.lower()
    for t in POPULAR:
        if ql in t["name"].lower(): _add(t)
    return results[:limit]

async def get_ticker_info(ticker: str) -> dict:
    import yfinance as yf
    def _f(t=ticker):
        i    = yf.Ticker(t).info
        logo = next((p["logo"] for p in POPULAR if p["ticker"]==t.upper()), None)
        if not logo:
            domain = i.get("website","").replace("https://","").replace("http://","").split("/")[0]
            logo   = f"https://logo.clearbit.com/{domain}" if domain else None
        return {"ticker":t.upper(),"name":i.get("longName",t),"sector":i.get("sector",""),
                "current_price":i.get("currentPrice") or i.get("regularMarketPrice"),
                "change_pct":i.get("regularMarketChangePercent",0),"logo":logo}
    return await asyncio.get_event_loop().run_in_executor(None, _f)
