"""Mining news aggregation MCP server.

Tools:
- search(query, days): search recent mining news.
- fetch_article(url): fetch and extract article content.
"""

import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from shared.config import get_settings
from shared.mcp_app import create_mcp_starlette_app
from shared.mock_data import get_mock_news

logger = logging.getLogger(__name__)

mcp = FastMCP("mining-news-mcp")


def _commodity_from_query(query: str) -> str | None:
    """Infer commodity keyword from query for mock filtering."""
    q = query.lower()
    for token in ["lithium", "锂", "copper", "铜", "nickel", "镍", "gold", "金", "iron", "铁"]:
        if token in q:
            return "lithium" if token in ("lithium", "锂") else token
    return None


@mcp.tool()
async def search(query: str, days: int = 7) -> list[dict]:
    """Search recent mining news for the given query.

    Args:
        query: Search keywords, e.g. "Pilbara lithium".
        days: Number of days to look back.

    Returns:
        A list of articles with title, source, published, summary, url.
    """
    settings = get_settings()
    logger.info("search query=%r days=%d mock=%s", query, days, settings.use_mock)

    if settings.use_mock:
        return get_mock_news(query=query, commodity=_commodity_from_query(query))

    if settings.currents_api_key:
        return await _search_currents(query, days, settings.currents_api_key)

    return await _search_google_news(query, days)


async def _search_currents(query: str, days: int, api_key: str) -> list[dict]:
    """Search via Currents API."""
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "keywords": query,
        "start_date": start_date,
        "language": "en",
        "apiKey": api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://api.currentsapi.services/v1/search", params=params)
        r.raise_for_status()
        data = r.json()

    articles = []
    for item in data.get("news", [])[:10]:
        articles.append(
            {
                "title": item.get("title", ""),
                "source": item.get("author") or item.get("source", "Currents"),
                "published": item.get("published", ""),
                "summary": item.get("description", ""),
                "url": item.get("url", ""),
            }
        )
    return articles


async def _search_google_news(query: str, days: int) -> list[dict]:
    """Search via Google News RSS (no API key required)."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        logger.warning("Failed to parse Google News RSS for %r", query)
        return get_mock_news(query=query)

    items = root.findall(".//item")
    articles = []
    cutoff = datetime.utcnow() - timedelta(days=days)
    for item in items[:15]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        source = item.findtext("source", default="")
        desc = item.findtext("description", default="")

        # Basic date filtering
        try:
            parsed = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
            if parsed < cutoff:
                continue
        except ValueError:
            pass

        summary = ""
        if desc:
            soup = BeautifulSoup(desc, "html.parser")
            summary = soup.get_text(strip=True)

        articles.append(
            {
                "title": title,
                "source": source or "Google News",
                "published": pub_date,
                "summary": summary,
                "url": link,
            }
        )
    return articles


@mcp.tool()
async def fetch_article(url: str) -> dict:
    """Fetch and extract the main content of a news article.

    Args:
        url: The article URL.

    Returns:
        dict with title, content, source, url.
    """
    logger.info("fetch_article url=%r", url)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    )
                },
            )
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch %r: %s", url, exc)
        return {
            "title": "",
            "content": f"Failed to fetch article: {exc}",
            "source": "",
            "url": url,
        }

    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""

    # Remove noisy elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find main content
    main = soup.find("main") or soup.find("article") or soup.find("body")
    text = main.get_text(separator="\n", strip=True) if main else ""
    lines = [line for line in text.splitlines() if line]
    content = "\n".join(lines[:80])  # Limit length

    return {
        "title": title,
        "content": content,
        "source": title,
        "url": url,
    }


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    port = int(os.environ.get("NEWS_MCP_PORT", "8000"))
    app = create_mcp_starlette_app(
        mcp,
        health_response={"status": "healthy", "server": "mining-news-mcp"},
    )
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
