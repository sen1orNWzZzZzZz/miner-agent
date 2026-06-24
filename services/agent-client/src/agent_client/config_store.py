"""Runtime LLM configuration store.

Persists user-supplied LLM settings (provider, model, base_url, api_key, use_mock)
to a local SQLite database so they can be changed via the web UI without restarting
the service.

Security note: the API key is stored in plaintext on disk inside the container's
``data/`` volume. This keeps the demo simple; rotate or encrypt in production.
The database file is gitignored so it is never committed.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """User-configurable LLM connection settings."""

    provider: str = Field(default="openai", description="openai, anthropic, or openai-compatible")
    model: str = Field(default="gpt-4o-mini", description="Model name")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    api_key: str | None = Field(default=None, description="API key", repr=False)
    use_mock: bool = Field(default=False, description="Force deterministic mock LLM")

    def to_masked_dict(self) -> dict[str, Any]:
        """Return a dict safe to send to the frontend (key masked)."""
        key = self.api_key or ""
        masked = ""
        if key:
            visible = min(4, len(key))
            masked = key[:visible] + "*" * (len(key) - visible)
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": masked,
            "use_mock": self.use_mock,
        }


def _config_dir() -> Path:
    """Return the directory used for runtime configuration files."""
    path = Path(os.environ.get("AGENT_DATA_DIR", "/app/data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return _config_dir() / "llm_config.db"


def _init_db(conn: sqlite3.Connection) -> None:
    """Create the config table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_config (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            provider TEXT NOT NULL DEFAULT 'openai',
            model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
            base_url TEXT,
            api_key TEXT,
            use_mock INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def _migrate_from_json(conn: sqlite3.Connection) -> None:
    """One-time migration from the legacy JSON config file."""
    legacy = _config_dir() / "llm_config.json"
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        config = LLMConfig.model_validate(data)
        _save_to_db(conn, config)
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            legacy.unlink()
        except OSError:
            pass


def _row_to_config(row: sqlite3.Row) -> LLMConfig:
    return LLMConfig(
        provider=row["provider"],
        model=row["model"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        use_mock=bool(row["use_mock"]),
    )


def _save_to_db(conn: sqlite3.Connection, config: LLMConfig) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO llm_config (id, provider, model, base_url, api_key, use_mock)
        VALUES (1, ?, ?, ?, ?, ?)
        """,
        (
            config.provider,
            config.model,
            config.base_url,
            config.api_key,
            int(config.use_mock),
        ),
    )
    conn.commit()


def load_llm_config() -> LLMConfig:
    """Load LLM config from the SQLite database; return defaults if missing."""
    path = _config_path()
    _config_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        _init_db(conn)
        _migrate_from_json(conn)
        row = conn.execute("SELECT * FROM llm_config WHERE id = 1").fetchone()
        if row is None:
            default = LLMConfig()
            _save_to_db(conn, default)
            return default
        return _row_to_config(row)
    finally:
        conn.close()


def save_llm_config(config: LLMConfig) -> None:
    """Persist LLM config to the SQLite database."""
    path = _config_path()
    _config_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        _init_db(conn)
        _save_to_db(conn, config)
    finally:
        conn.close()


def update_llm_config(updates: dict[str, Any]) -> LLMConfig:
    """Merge partial updates into the existing config and persist."""
    current = load_llm_config()
    current_dict = json.loads(current.model_dump_json())
    # Preserve existing api_key if the frontend sends an empty/masked value.
    if "api_key" in updates:
        new_key = updates["api_key"]
        if new_key is None or "*" in str(new_key):
            updates.pop("api_key", None)
    current_dict.update(updates)
    config = LLMConfig.model_validate(current_dict)
    save_llm_config(config)
    return config


def get_llm_config() -> LLMConfig:
    """Return the current LLM configuration."""
    return load_llm_config()
