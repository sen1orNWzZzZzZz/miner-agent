"""LME / commodity price MCP server.

Backed by MetalpriceAPI (https://metalpriceapi.com), which has a generous free
tier and covers precious metals plus several base metals. Set METALPRICE_API_KEY
in the environment to use real data; otherwise the server returns mock data.

Tools:
- get_price(commodity, date): get price for a commodity on a date.
- get_trend(commodity, days): get price trend over recent days.
"""

import logging
import os
from datetime import datetime, timedelta

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from price_mcp.config_store import get_price_config, update_price_config
from shared.config import get_settings
from shared.mcp_app import create_mcp_starlette_app
from shared.mock_data import get_mock_price, get_mock_trend

logger = logging.getLogger(__name__)

mcp = FastMCP("lme-price-mcp")

API_BASE = "https://api.metalpriceapi.com/v1"

# Map friendly commodity names to MetalpriceAPI symbols. Extend this freely —
# any symbol supported by your plan (see /v1/symbols) can be added here.
COMMODITY_SYMBOLS = {
    "gold": "XAU",
    "silver": "XAG",
    "platinum": "XPT",
    "palladium": "XPD",
    "copper": "XCU",
    "zinc": "ZNC",
    "aluminium": "ALU",
    "aluminum": "ALU",
    "nickel": "NI",
    "lead": "LEAD",
    "tin": "TIN",
    "lithium": "LITHIUM",
}

# Precious metals are quoted per troy ounce; other metals per ounce.
PRECIOUS = {"XAU", "XAG", "XPT", "XPD"}


def _symbol_for(commodity: str) -> str:
    return COMMODITY_SYMBOLS.get(commodity.lower(), commodity.upper())


def _unit_for(symbol: str) -> str:
    return "troy ounce" if symbol in PRECIOUS else "ounce"


def _resolve() -> tuple[str | None, str, bool]:
    """Resolve effective (api_key, base_url, use_mock).

    Runtime config (set via the web UI, stored in SQLite) takes precedence over
    environment variables. Mock resolution mirrors the LLM's: a configured API
    key (web or env) overrides the global ``USE_MOCK`` flag, so the web config is
    never silently ignored. Mock is used only when explicitly forced, or when no
    key is available and the global demo flag is on.
    """
    settings = get_settings()
    cfg = get_price_config()
    api_key = cfg.api_key or settings.metalprice_api_key or settings.metals_api_key
    base_url = (cfg.base_url or API_BASE).rstrip("/")
    use_mock = cfg.use_mock or (not api_key and settings.use_mock)
    return api_key, base_url, use_mock


@mcp.tool()
async def get_price(commodity: str, date: str | None = None) -> dict:
    """Get the latest or historical market price for a commodity.

    Args:
        commodity: Commodity name, e.g. gold, silver, copper, nickel, aluminium.
        date: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        dict with date, price, currency, unit, benchmark.
    """
    target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    api_key, base_url, use_mock = _resolve()
    logger.info(
        "get_price commodity=%r date=%r mock=%s has_key=%s",
        commodity,
        target_date,
        use_mock,
        bool(api_key),
    )

    if use_mock or not api_key:
        price = get_mock_price(commodity)
        price["date"] = target_date
        return price

    try:
        return await _fetch_price(commodity, target_date, api_key, base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Price API failed: %s; returning mock", exc)
        price = get_mock_price(commodity)
        price["date"] = target_date
        price["benchmark"] += " (fallback from API error)"
        return price


@mcp.tool()
async def get_trend(commodity: str, days: int = 30) -> list[dict]:
    """Get the price trend for a commodity over the last N days.

    Args:
        commodity: Commodity name, e.g. gold, copper, nickel.
        days: Number of days to return.

    Returns:
        List of daily {date, price, currency, unit} dicts.
    """
    api_key, base_url, use_mock = _resolve()
    logger.info(
        "get_trend commodity=%r days=%d mock=%s has_key=%s",
        commodity,
        days,
        use_mock,
        bool(api_key),
    )

    if use_mock or not api_key:
        return get_mock_trend(commodity, days)

    # 1. Preferred: pull a real time series from the timeframe endpoint.
    try:
        return await _fetch_trend(commodity, days, api_key, base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Price API timeframe failed: %s; trying anchored trend", exc)

    # 2. Fallback: anchor a synthetic walk around the latest real price (cheaper,
    #    works even when historical/timeframe is not in the plan).
    try:
        latest = await _fetch_price(
            commodity, datetime.utcnow().strftime("%Y-%m-%d"), api_key, base_url
        )
        base_price = float(latest["price"])
        trend = []
        for i in range(days, -1, -1):
            d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            noise = (i % 5 - 2) * base_price * 0.005
            price = round(base_price + noise + (days - i) * base_price * 0.0005, 4)
            trend.append(
                {
                    "date": d,
                    "price": price,
                    "currency": latest.get("currency", "USD"),
                    "unit": latest.get("unit", "ounce"),
                }
            )
        return trend
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build anchored trend: %s; returning mock", exc)
        return get_mock_trend(commodity, days)


def _price_from_rates(rates: dict, symbol: str) -> float:
    """Extract a USD-per-unit price from a MetalpriceAPI rates object.

    Rates are quoted as units-per-USD (e.g. ``rates['XAU']`` = ounces per USD),
    so the familiar price is the reciprocal. Some responses also include the
    reciprocal directly as ``USD<symbol>`` — prefer that when present.
    """
    direct = rates.get(f"USD{symbol}")
    if direct:
        return round(float(direct), 4)
    rate = rates.get(symbol)
    if rate:
        return round(1.0 / float(rate), 4)
    raise ValueError(f"No rate returned for {symbol}")


async def _fetch_price(commodity: str, date: str, api_key: str, base_url: str = API_BASE) -> dict:
    """Fetch a single-day price from the price API."""
    symbol = _symbol_for(commodity)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    endpoint = "latest" if date >= today else date
    params = {"api_key": api_key, "base": "USD", "currencies": symbol}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{base_url}/{endpoint}", params=params)
        r.raise_for_status()
        data = r.json()

    if not data.get("success", True):
        raise ValueError(f"API error: {data.get('error') or data}")

    price = _price_from_rates(data.get("rates", {}), symbol)
    return {
        "date": data.get("date", date),
        "price": price,
        "currency": "USD",
        "unit": _unit_for(symbol),
        "benchmark": f"MetalpriceAPI {symbol}",
    }


async def _fetch_trend(commodity: str, days: int, api_key: str, base_url: str = API_BASE) -> list[dict]:
    """Fetch a real daily time series from the price API timeframe endpoint."""
    symbol = _symbol_for(commodity)
    end = datetime.utcnow()
    start = end - timedelta(days=max(days, 1))
    params = {
        "api_key": api_key,
        "base": "USD",
        "currencies": symbol,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{base_url}/timeframe", params=params)
        r.raise_for_status()
        data = r.json()

    if not data.get("success", True):
        raise ValueError(f"API error: {data.get('error') or data}")

    rates_by_date = data.get("rates", {})
    if not rates_by_date:
        raise ValueError("timeframe returned no rates")

    unit = _unit_for(symbol)
    trend = []
    for d in sorted(rates_by_date):
        try:
            price = _price_from_rates(rates_by_date[d], symbol)
        except ValueError:
            continue
        trend.append({"date": d, "price": price, "currency": "USD", "unit": unit})
    if not trend:
        raise ValueError("no usable rates in timeframe response")
    return trend


async def config_get(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return the current price-API config (API key masked)."""
    return JSONResponse(get_price_config().to_masked_dict())


async def config_post(request: Request) -> JSONResponse:
    """Update the runtime price-API config."""
    try:
        payload = await request.json()
        config = update_price_config(payload)
        return JSONResponse(config.to_masked_dict())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to save price config")
        return JSONResponse({"detail": f"Invalid config: {exc}"}, status_code=400)


async def config_test(request: Request) -> JSONResponse:  # noqa: ARG001
    """Test the saved price-API config with a live request."""
    api_key, base_url, use_mock = _resolve()
    if use_mock:
        return JSONResponse({"ok": True, "mode": "mock", "message": "当前为 Mock 价格模式"})
    if not api_key:
        return JSONResponse(
            {"ok": False, "mode": "error", "message": "未配置 API Key"}, status_code=200
        )
    try:
        result = await _fetch_price("gold", datetime.utcnow().strftime("%Y-%m-%d"), api_key, base_url)
        return JSONResponse(
            {
                "ok": True,
                "mode": "real",
                "message": f"连接成功：gold = {result['price']} USD/{result['unit']}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Price API test failed: %s", exc)
        return JSONResponse({"ok": False, "mode": "error", "message": f"连接失败：{exc}"})


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    port = int(os.environ.get("PRICE_MCP_PORT", "8002"))
    app = create_mcp_starlette_app(
        mcp,
        health_response={"status": "healthy", "server": "lme-price-mcp"},
        extra_routes=[
            Route("/config/price", config_get, methods=["GET"]),
            Route("/config/price", config_post, methods=["POST"]),
            Route("/config/price/test", config_test, methods=["POST"]),
        ],
    )
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
