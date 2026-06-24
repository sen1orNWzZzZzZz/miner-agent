"""Runtime price-API configuration store.

Persists the metals price API settings (provider, base_url, api_key, use_mock)
to a local SQLite database so they can be changed from the web UI without
restarting the container. Mirrors the agent-client LLM config store.

The database file is gitignored and lives on the mounted data volume so it
survives restarts. The API key is stored in plaintext — rotate/encrypt in
production.
"""

import os
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PriceConfig(BaseModel):
    """User-configurable metals price API settings."""

    provider: str = Field(default="metalpriceapi", description="Price API provider")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    api_key: str | None = Field(default=None, description="API key", repr=False)
    use_mock: bool = Field(default=False, description="Force mock price data")

    def to_masked_dict(self) -> dict[str, Any]:
        """Return a dict safe to send to the frontend (key masked)."""
        key = self.api_key or ""
        masked = ""
        if key:
            visible = min(4, len(key))
            masked = key[:visible] + "*" * (len(key) - visible)
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": masked,
            "use_mock": self.use_mock,
        }


def _config_dir() -> Path:
    path = Path(os.environ.get("PRICE_DATA_DIR", "/app/data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return _config_dir() / "price_config.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_config (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            provider TEXT NOT NULL DEFAULT 'metalpriceapi',
            base_url TEXT,
            api_key TEXT,
            use_mock INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def _row_to_config(row: sqlite3.Row) -> PriceConfig:
    return PriceConfig(
        provider=row["provider"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        use_mock=bool(row["use_mock"]),
    )


def _save_to_db(conn: sqlite3.Connection, config: PriceConfig) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO price_config (id, provider, base_url, api_key, use_mock)
        VALUES (1, ?, ?, ?, ?)
        """,
        (config.provider, config.base_url, config.api_key, int(config.use_mock)),
    )
    conn.commit()


def load_price_config() -> PriceConfig:
    """Load price config from SQLite; return defaults if missing."""
    conn = sqlite3.connect(str(_config_path()))
    try:
        conn.row_factory = sqlite3.Row
        _init_db(conn)
        row = conn.execute("SELECT * FROM price_config WHERE id = 1").fetchone()
        if row is None:
            default = PriceConfig()
            _save_to_db(conn, default)
            return default
        return _row_to_config(row)
    finally:
        conn.close()


def save_price_config(config: PriceConfig) -> None:
    conn = sqlite3.connect(str(_config_path()))
    try:
        _init_db(conn)
        _save_to_db(conn, config)
    finally:
        conn.close()


def update_price_config(updates: dict[str, Any]) -> PriceConfig:
    """Merge partial updates into the existing config and persist."""
    current = load_price_config()
    current_dict = current.model_dump()
    # Preserve the existing api_key if the frontend sends an empty/masked value.
    if "api_key" in updates:
        new_key = updates["api_key"]
        if new_key is None or "*" in str(new_key):
            updates.pop("api_key", None)
    current_dict.update(updates)
    config = PriceConfig.model_validate(current_dict)
    save_price_config(config)
    return config


def get_price_config() -> PriceConfig:
    return load_price_config()
