"""
features/url_research.py

Research mode — fetch any URL and extract usable text for the sentiment agent.

Supports:
  - News articles (Reuters, WSJ, CNBC, Bloomberg, etc.)
  - Reddit posts and comments
  - Company blog posts / press releases
  - Earnings call transcripts
  - Any public webpage

Returns a ResearchContext that gets injected into the sentiment agent
as supplementary evidence alongside (or instead of) Tavily search.
"""

from __future__ import annotations
import re
import sys
import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class ResearchContext:
    url:         str
    title:       str
    text:        str        # extracted clean text, capped at 6000 chars
    domain:      str
    word_count:  int
    is_reddit:   bool = False
    is_news:     bool = False


async def fetch_url_content(url: str) -> ResearchContext | None:
    """
    Fetch a URL and extract clean text content.
    Handles news articles, Reddit posts, and general webpages.
    """
    try:
        import httpx
        from html.parser import HTMLParser

        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        is_reddit = "reddit.com" in domain
        is_news   = any(d in domain for d in [
            "reuters.com", "bloomberg.com", "wsj.com", "cnbc.com",
            "marketwatch.com", "ft.com", "businessinsider.com",
            "seekingalpha.com", "fool.com", "barrons.com"
        ])

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }

        # Some news sites block standard requests — try with extended headers
        headers_extended = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers_extended)
            # Accept 200 and also 403 where we still get partial HTML
            if resp.status_code not in (200, 403):
                return None
            html = resp.text
            # If we got blocked (403 or very short response), try Google AMP version
            if resp.status_code == 403 or len(html) < 500:
                try:
                    amp_url = f"https://amp.dev/documentation/?url={url}"
                    # Try archive.org as fallback for public news
                    archive_url = f"https://archive.org/wayback/available?url={url.replace('https://','').replace('http://','')}"
                    ar = await client.get(archive_url, timeout=10)
                    if ar.status_code == 200:
                        aj = ar.json()
                        archived = aj.get("archived_snapshots",{}).get("closest",{}).get("url")
                        if archived:
                            ar2 = await client.get(archived, headers=headers_extended, timeout=15)
                            if ar2.status_code == 200 and len(ar2.text) > 500:
                                html = ar2.text
                except Exception:
                    pass
            if len(html) < 200:
                return None

        # Extract clean text using simple HTML parser
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.texts = []
                self.skip  = False
                self.title = ""
                self._in_title = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer", "header", "aside"):
                    self.skip = True
                if tag == "title":
                    self._in_title = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer", "header", "aside"):
                    self.skip = False
                if tag == "title":
                    self._in_title = False

            def handle_data(self, data):
                if self._in_title:
                    self.title = data.strip()
                if not self.skip:
                    text = data.strip()
                    if len(text) > 20:
                        self.texts.append(text)

        extractor = TextExtractor()
        extractor.feed(html)

        full_text = " ".join(extractor.texts)

        # Clean up whitespace
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        full_text = re.sub(r'(\. ){2,}', '. ', full_text)

        # For Reddit, try to extract post body more specifically
        if is_reddit:
            # Reddit puts post content in specific patterns
            post_match = re.search(r'"body":"([^"]{100,})"', html)
            if post_match:
                import json
                try:
                    body = json.loads(f'"{post_match.group(1)}"')
                    full_text = body + "\n\n" + full_text[:2000]
                except Exception:
                    pass

        word_count = len(full_text.split())
        # Cap at 6000 chars for LLM context
        capped_text = full_text[:6000]

        return ResearchContext(
            url=url, title=extractor.title or domain,
            text=capped_text, domain=domain,
            word_count=word_count,
            is_reddit=is_reddit, is_news=is_news,
        )

    except Exception as e:
        return None


def research_to_sentiment_context(ctx: ResearchContext, ticker: str) -> str:
    """
    Format a ResearchContext into a string for injection into the sentiment agent.
    """
    source_type = "Reddit post" if ctx.is_reddit else "news article" if ctx.is_news else "web page"
    return f"""
=== RESEARCH CONTEXT (user-provided {source_type}) ===
Source: {ctx.url}
Domain: {ctx.domain}
Title:  {ctx.title}
Words:  {ctx.word_count}

Content:
{ctx.text}

INSTRUCTION: This user-provided source is supplementary evidence for {ticker.upper()} sentiment.
Weight it alongside (not instead of) live news data.
Note the source type ({source_type}) when citing this in your analysis.
=== END RESEARCH CONTEXT ===
"""


async def extract_ticker_from_url(url: str) -> str | None:
    """Try to detect a stock ticker mentioned in a URL or its content."""
    # Check URL itself first
    url_upper = url.upper()
    common_tickers = [
        "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM",
        "JNJ","BRK","NFLX","AMD","INTC","CRM","ORCL","PYPL","UBER",
        "LYFT","SNAP","SQ","SHOP","SPOT","ZM","COIN","PLTR","RBLX"
    ]
    for t in common_tickers:
        if t in url_upper:
            return t

    # Try fetching and scanning content
    ctx = await fetch_url_content(url)
    if not ctx:
        return None

    text_upper = ctx.text.upper()
    for t in common_tickers:
        if f"({t})" in text_upper or f"NASDAQ: {t}" in text_upper or f"NYSE: {t}" in text_upper:
            return t

    return None