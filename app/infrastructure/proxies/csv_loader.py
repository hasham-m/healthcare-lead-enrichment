"""Load proxy definitions from the project CSV file."""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


DEFAULT_PROXY_CSV_PATH = Path(__file__).resolve().parents[3] / "proxies.csv"


class ProxyCsvRecord(BaseModel):
    """A validated proxy row loaded from CSV."""

    proxy_url: str
    is_active: bool = True

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname or not parsed.port or not parsed.username:
            raise ValueError("proxy_url must include scheme, host, port, and username")
        return value

class ProxyCsvLoader:
    """Load validated proxy records from CSV."""

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self.path = Path(csv_path) if csv_path else DEFAULT_PROXY_CSV_PATH

    def load(self) -> list[ProxyCsvRecord]:
        """Load and validate all proxy rows from the configured CSV."""
        with self.path.open(newline="", encoding="utf-8-sig") as proxy_file:
            reader = csv.DictReader(proxy_file)
            if not reader.fieldnames or "proxy_url" not in reader.fieldnames:
                raise ValueError("Proxy CSV must contain a proxy_url column")
            return [
                ProxyCsvRecord(
                    proxy_url=(row.get("proxy_url") or "").strip(),
                    is_active=_parse_bool(row.get("enabled"), default=True),
                )
                for row in reader
                if (row.get("proxy_url") or "").strip()
            ]

def _parse_bool(value: object, *, default: bool) -> bool:
    """Parse common CSV boolean spellings."""
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")
