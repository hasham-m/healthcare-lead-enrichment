"""Coordinate proxy CSV loading with proxy_pool database synchronization."""

from __future__ import annotations

from datetime import datetime
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


class ProxyLease(BaseModel):
    """The database lease information assigned to one scraper session."""

    id: int
    proxy_url: str
    lease_token: str
    lease_until: datetime


class ProxyPoolService:
    # Synchronize CSV proxy definitions and read usable database proxies.

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

    def acquire_proxy(self) -> ProxyLease | None:
        """Lease the least-used active proxy for ten minutes."""
        lease = self._repository.acquire_proxy(lease_minutes=10)
        return ProxyLease.model_validate(lease) if lease else None

    def renew_proxy_lease(self, lease_token: str) -> ProxyLease | None:
        """Extend an active lease by five minutes."""
        lease = self._repository.renew_proxy_lease(lease_token, extension_minutes=5)
        return ProxyLease.model_validate(lease) if lease else None

    def release_proxy(self, lease_token: str) -> bool:
        """Release a proxy lease after the session ends."""
        return self._repository.release_proxy(lease_token)
