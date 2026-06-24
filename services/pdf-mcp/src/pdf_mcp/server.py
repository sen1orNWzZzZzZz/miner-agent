"""NI 43-101 mineral resource PDF parser MCP server.

Tool:
- extract_resources(pdf_url): download and parse a mining report PDF,
  returning resource estimate tables (Measured / Indicated / Inferred).
"""

import io
import logging
import os
import re
import tempfile

import fitz  # PyMuPDF
import httpx
import pdfplumber
from mcp.server.fastmcp import FastMCP

from shared.config import get_settings
from shared.mcp_app import create_mcp_starlette_app
from shared.mock_data import get_mock_resources

logger = logging.getLogger(__name__)

mcp = FastMCP("mineral-pdf-mcp")

RESOURCE_KEYWORDS = [
    "measured",
    "indicated",
    "inferred",
    "resource",
    "resources",
    "tonnes",
    "grade",
    "contained",
    "mt",
    "moz",
    "li2o",
    "cao",
]


@mcp.tool()
async def extract_resources(pdf_url: str) -> dict:
    """Download and extract NI 43-101 style resource tables from a PDF.

    Args:
        pdf_url: Public URL to the PDF report.

    Returns:
        dict with deposit name, commodity, tables (headers + rows), notes.
    """
    settings = get_settings()
    logger.info("extract_resources pdf_url=%r mock=%s", pdf_url, settings.use_mock)

    if settings.use_mock:
        return get_mock_resources()

    try:
        pdf_bytes = await _download_pdf(pdf_url)
        tables = _extract_tables(pdf_bytes)
        resource_tables = _filter_resource_tables(tables)

        # Try to infer deposit name from URL or tables
        deposit = _infer_deposit_name(pdf_url, resource_tables)
        commodity = _infer_commodity(resource_tables)

        return {
            "deposit": deposit,
            "commodity": commodity,
            "tables": resource_tables,
            "pdf_url": pdf_url,
            "notes": (
                "Extracted tables containing Measured / Indicated / Inferred "
                "resource keywords. Verify against the original report."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("PDF extraction failed for %r", pdf_url)
        return {
            "deposit": "",
            "commodity": "",
            "tables": [],
            "pdf_url": pdf_url,
            "error": str(exc),
            "notes": "Extraction failed; returning empty result.",
        }


async def _download_pdf(url: str) -> bytes:
    """Download PDF from URL into memory."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
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
    return r.content


def _extract_tables(pdf_bytes: bytes) -> list[dict]:
    """Extract tables from PDF using PyMuPDF, falling back to pdfplumber."""
    tables = _extract_with_pymupdf(pdf_bytes)
    if tables:
        logger.info("PyMuPDF extracted %d tables", len(tables))
        return tables

    logger.info("PyMuPDF found no tables, trying pdfplumber")
    return _extract_with_pdfplumber(pdf_bytes)


def _extract_with_pymupdf(pdf_bytes: bytes) -> list[dict]:
    tables = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc[page_num]
            found = page.find_tables()
            if not found or not found.tables:
                continue
            for table in found.tables:
                try:
                    df = table.to_pandas()
                    headers = [str(h) for h in df.columns.tolist()]
                    rows = [[str(cell) for cell in row] for row in df.values.tolist()]
                    tables.append(
                        {
                            "page": page_num + 1,
                            "extractor": "pymupdf",
                            "headers": headers,
                            "rows": rows,
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue
        doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF extraction failed: %s", exc)
    return tables


def _extract_with_pdfplumber(pdf_bytes: bytes) -> list[dict]:
    tables = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                try:
                    extracted = page.extract_tables(
                        {
                            "vertical_strategy": "lines",
                            "horizontal_strategy": "lines",
                            "snap_tolerance": 3,
                        }
                    )
                except Exception:  # noqa: BLE001
                    extracted = page.extract_tables()

                if not extracted:
                    continue
                for table in extracted:
                    if not table:
                        continue
                    rows = [[str(cell) if cell is not None else "" for cell in row] for row in table]
                    headers = rows[0] if rows else []
                    data_rows = rows[1:] if len(rows) > 1 else []
                    tables.append(
                        {
                            "page": page_num + 1,
                            "extractor": "pdfplumber",
                            "headers": headers,
                            "rows": data_rows,
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber extraction failed: %s", exc)
    return tables


def _filter_resource_tables(tables: list[dict]) -> list[dict]:
    """Keep tables that mention resource categories or mining terms."""
    resource_tables = []
    for table in tables:
        text = " ".join(str(table.get("headers", []))).lower()
        for row in table.get("rows", []):
            text += " " + " ".join(str(cell).lower() for cell in row)

        if any(kw in text for kw in RESOURCE_KEYWORDS):
            table["is_resource_table"] = True
            resource_tables.append(table)
    return resource_tables


def _infer_deposit_name(pdf_url: str, tables: list[dict]) -> str:
    """Best-effort deposit name extraction."""
    # From URL filename
    match = re.search(r"/([^/]+\.pdf)", pdf_url)
    if match:
        return match.group(1).replace("_", " ").replace("-", " ").replace(".pdf", "").title()
    # From first table headers/rows
    if tables:
        text = " ".join(str(tables[0].get("headers", [])))
        return text.strip()[:60] or "Unknown Deposit"
    return "Unknown Deposit"


def _infer_commodity(tables: list[dict]) -> str:
    """Best-effort commodity inference from table content."""
    text = ""
    for table in tables:
        text += " ".join(str(h).lower() for h in table.get("headers", []))
        for row in table.get("rows", []):
            text += " " + " ".join(str(cell).lower() for cell in row)
    if "li2o" in text or "lithium" in text:
        return "lithium"
    if "cu" in text or "copper" in text:
        return "copper"
    if "au" in text or "gold" in text:
        return "gold"
    if "ni" in text or "nickel" in text:
        return "nickel"
    return ""


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    port = int(os.environ.get("PDF_MCP_PORT", "8001"))
    app = create_mcp_starlette_app(
        mcp,
        health_response={"status": "healthy", "server": "mineral-pdf-mcp"},
    )
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
