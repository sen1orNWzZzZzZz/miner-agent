"""Mock data for demo mode and API fallbacks."""

from datetime import datetime, timedelta


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def days_ago(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).isoformat(timespec="seconds")


MOCK_NEWS_ARTICLES = [
    {
        "title": "Pilbara Minerals 季度产量创新高，锂辉石出货强劲",
        "source": "Mining Weekly (Mock)",
        "published": days_ago(1),
        "summary": "Pilbara Minerals 公布最新季度报告，Pilgangoora 项目锂辉石精矿产量环比增长 12%，发货量达到指引上限。公司表示将推进下游氢氧化锂合资项目。",
        "url": "https://www.pilbaraminerals.com.au/site/investors-media/announcements",
        "commodity": "lithium",
    },
    {
        "title": "西澳锂矿勘探持续升温，Pilbara 地区新增高品位锂辉石 intersection",
        "source": "Resource World (Mock)",
        "published": days_ago(2),
        "summary": "多家勘探公司在 Pilbara 克拉通报告新的锂辉石矿化，部分样段氧化锂品位超过 1.5%，引发市场对区域资源潜力的重新评估。",
        "url": "https://www.resourceworld.com/news/lithium-pilbara-exploration",
        "commodity": "lithium",
    },
    {
        "title": "LME 锂价短期承压，分析师关注 Pilbara 拍卖价格指引",
        "source": "Metal Bulletin (Mock)",
        "published": days_ago(3),
        "summary": "受中国电动车需求增速放缓影响，碳酸锂价格继续筑底。Pilbara Minerals 的 BMX 锂精矿拍卖结果被视为现货市场短期风向指标。",
        "url": "https://www.metalbulletin.com/articles/lithium-prices",
        "commodity": "lithium",
    },
]

MOCK_RESOURCE_TABLE = {
    "deposit": "Pilgangoora Project (Mock)",
    "commodity": "lithium",
    "tables": [
        {
            "page": 42,
            "headers": ["Category", "Tonnes (Mt)", "Li2O (%)", "Contained Li2O (kt)"],
            "rows": [
                ["Indicated", "142.0", "1.26", "1,789"],
                ["Inferred", "74.0", "1.21", "895"],
                ["Total", "216.0", "1.24", "2,684"],
            ],
        }
    ],
    "notes": "以上数据为示例，仅用于演示 PDF 解析能力。",
}


def _generate_trend(base: float, days: int) -> list[dict]:
    trend = []
    price = base
    for i in range(days, -1, -1):
        date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        price = round(price + (i % 3 - 1) * 50 + (days - i) * 5, 2)
        trend.append(
            {
                "date": date,
                "price": price,
                "currency": "USD",
                "unit": "tonne",
            }
        )
    return trend


MOCK_LITHIUM_TREND = _generate_trend(11500.0, 30)

MOCK_PRICES = {
    "lithium": {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "price": 11800.0,
        "currency": "USD",
        "unit": "tonne",
        "benchmark": "LME lithium hydroxide indicator (mock)",
    },
    "copper": {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "price": 8475.5,
        "currency": "USD",
        "unit": "tonne",
        "benchmark": "LME Copper (mock)",
    },
    "nickel": {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "price": 18500.0,
        "currency": "USD",
        "unit": "tonne",
        "benchmark": "LME Nickel (mock)",
    },
}


def get_mock_news(query: str = "", commodity: str | None = None) -> list[dict]:
    """Return mock news articles, optionally filtered."""
    q = query.lower()
    articles = [
        a
        for a in MOCK_NEWS_ARTICLES
        if (not commodity or (a.get("commodity") or "").lower() == commodity.lower())
        and (not q or any(token in a["title"].lower() + a["summary"].lower() for token in q.split()))
    ]
    return articles if articles else MOCK_NEWS_ARTICLES[:2]


def get_mock_price(commodity: str) -> dict:
    """Return mock price for a commodity."""
    return MOCK_PRICES.get(commodity.lower(), MOCK_PRICES["lithium"])


def get_mock_trend(commodity: str, days: int) -> list[dict]:
    """Return mock trend for a commodity."""
    base = MOCK_PRICES.get(commodity.lower(), MOCK_PRICES["lithium"])["price"]
    return _generate_trend(base, days)


def get_mock_resources() -> dict:
    """Return mock NI 43-101 resource table."""
    return MOCK_RESOURCE_TABLE
