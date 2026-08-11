"""Shared helpers for directory scrapers."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


class Helpers:
    """Universal URL and environment helpers used by directory scrapers."""

    @staticmethod
    def normalize_url(url: str) -> str:
        """Return a consistently formatted URL without a fragment."""
        parsed = urlparse(url.strip())
        if not parsed.scheme or not parsed.netloc:
            return url.strip()

        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                parsed.params,
                parsed.query,
                "",
            )
        )

    @staticmethod
    def same_netloc(first_url: str, second_url: str) -> bool:
        """Return whether two URLs point to the same network location."""
        first = urlparse(first_url)
        second = urlparse(second_url)
        return bool(first.netloc and second.netloc) and (
            first.netloc.lower() == second.netloc.lower()
        )

    @staticmethod
    def directory_name(url: str) -> str:
        """Return the normalized directory name for a source URL."""
        hostname = (urlparse(url).hostname or "").lower()
        if "psychologytoday.com" in hostname:
            return "psychology_today"
        if "goodtherapy.org" in hostname or "goodtherapy.com" in hostname:
            return "good_therapy"
        return hostname.removeprefix("www.").replace(".", "_")

    @staticmethod
    def load_root_env() -> None:
        """Load key/value pairs from the repository-root ``.env`` file."""
        # helpers.py lives at app/directories/helpers.py; the .env is at repo root.
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if not env_path.exists():
            return

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

    @staticmethod
    def load_proxies(csv_path: str | Path | None = None) -> list[str]:
        """Load enabled proxy URLs from the repository's local CSV file."""
        path = (
            Path(csv_path)
            if csv_path
            else Path(__file__).resolve().parents[2] / "proxies.csv"
        )
        if not path.exists():
            return []

        with path.open(newline="", encoding="utf-8-sig") as proxy_file:
            reader = csv.DictReader(proxy_file)
            if not reader.fieldnames or "proxy_url" not in reader.fieldnames:
                raise ValueError("Proxy CSV must contain a proxy_url column")

            proxies: list[str] = []
            for row in reader:
                proxy_url = (row.get("proxy_url") or "").strip()
                enabled = (row.get("enabled") or "true").strip().lower()
                if not proxy_url or enabled not in {"true", "1", "yes", "y", "on"}:
                    continue
                parsed = urlparse(proxy_url)
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError(f"Invalid proxy URL in {path}: {proxy_url}")
                proxies.append(proxy_url)
            return proxies

    @staticmethod
    def utc_hours_ago(hours: int) -> datetime:
        if hours < 0:
            raise ValueError("hours must be zero or greater")
        return datetime.now(timezone.utc) - timedelta(hours=hours)
