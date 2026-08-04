"""Coordinate proxy CSV loading with proxy_pool database synchronization."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.database.create_tables import create_proxy_pool_table
from app.database.repository import ProxyPoolRepository
from app.infrastructure.proxies.csv_loader import ProxyCsvLoader


class ProxySyncResult(BaseModel):
    """Summary of a proxy CSV synchronization with the database."""

    added: int
    deactivated: int
    reactivated: int


class ProxyPoolService:
    """Synchronize CSV proxy definitions and read usable database proxies."""

    def __init__(
        self,
        csv_path: str | Path | None = None,
        repository: ProxyPoolRepository | None = None,
    ) -> None:
        self._loader = ProxyCsvLoader(csv_path)
        self._repository = repository or ProxyPoolRepository()

    def sync_from_csv(self) -> ProxySyncResult:
        """Create the table, then insert or update proxies from CSV."""
        create_proxy_pool_table()
        proxies = self._loader.load()
        added, deactivated, reactivated = self._repository.sync_csv_proxies(
            {
                "proxy_url": proxy.proxy_url,
                "is_active": proxy.is_active,
            }
            for proxy in proxies
        )
        return ProxySyncResult(
            added=added,
            deactivated=deactivated,
            reactivated=reactivated,
        )

    def active_proxy_urls(self) -> list[str]:
        """Return active, available proxy URLs from proxy_pool."""
        return self._repository.active_proxy_urls()
