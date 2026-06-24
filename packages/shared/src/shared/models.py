"""Shared Pydantic models."""

from datetime import datetime

from pydantic import BaseModel, Field


class Article(BaseModel):
    """A news article."""

    title: str
    source: str
    published: str
    summary: str
    url: str
    commodity: str | None = None


class ResourceEstimate(BaseModel):
    """A single NI 43-101 resource estimate row."""

    category: str = Field(description="Measured / Indicated / Inferred")
    tonnes: str | None = None
    grade: str | None = None
    contained: str | None = None
    unit: str | None = None


class ResourceTable(BaseModel):
    """A resource table extracted from a PDF."""

    page: int
    headers: list[str]
    rows: list[list[str]]
    commodity: str | None = None
    deposit: str | None = None


class PricePoint(BaseModel):
    """A single commodity price observation."""

    date: str
    price: float
    currency: str = "USD"
    unit: str = "tonne"


class BriefingOutput(BaseModel):
    """Structured output for the daily briefing."""

    query: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    news_summary: str
    resources: list[ResourceTable]
    price_trend: str
    risk_warnings: str
    sources: list[dict]
    markdown: str
