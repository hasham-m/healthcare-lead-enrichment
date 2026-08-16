"""Async database-backed workers for Psychology Today profile enrichment."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from curl_cffi import requests

from app.database.create_tables import create_tables
from app.database.repository import PsychologyTodayProfileRepository
from app.directories.helpers import Helpers
from app.directories.schemas import ClaimedProfile, ProfileScrapeSummary
from app.directories.psychology_today.profile_enrichment import enrich_profile
from app.infrastructure.proxies.service import ProxyPoolService


async def scrape_pending_profiles(
    *,
    worker_count: int = 3,
    max_profiles: int | None = None,
    status: Literal["pending", "failed"] = "pending",
    created_since: datetime | None = None,
    created_within_hours: int | None = None,
    source_city: str | None = None,
    source_state: str | None = None,
    max_profile_attempts: int = 3,
    proxy: str | None = None,
    proxy_csv_path: str | Path | None = None,
) -> ProfileScrapeSummary:
    # Enrich claimed profiles concurrently, with PostgreSQL as the work queue.

    """Each worker claims one row directly from PostgreSQL with ``SKIP LOCKED``.
    It then uses one proxy lease for that profile HTTP session, parses the page,
    persists the enrichment fields, and claims another row until none remain.
    """
    if worker_count < 1:
        raise ValueError("worker_count must be at least 1")
    if max_profiles is not None and max_profiles < 1:
        raise ValueError("max_profiles must be at least 1 when provided")
    if max_profile_attempts < 1:
        raise ValueError("max_profile_attempts must be at least 1")
    if created_since is not None and created_within_hours is not None:
        raise ValueError("Pass either created_since or created_within_hours, not both")
    if created_within_hours is not None:
        created_since = Helpers.utc_hours_ago(created_within_hours)

    await asyncio.to_thread(create_tables)
    repository = PsychologyTodayProfileRepository()
    proxy_pool_service = ProxyPoolService(proxy_csv_path)

    if proxy is None:
        await asyncio.to_thread(proxy_pool_service.sync_from_csv)
        available_proxy_count = len(
            await asyncio.to_thread(proxy_pool_service.active_proxy_urls)
        )
        if available_proxy_count == 0:
            raise RuntimeError("No active proxy is available in proxy_pool")
        worker_count = min(worker_count, available_proxy_count)

    summary = ProfileScrapeSummary(started_at=datetime.now(timezone.utc))
    summary_lock = asyncio.Lock()
    claimed_slots = 0

    async def reserve_claim_slot() -> bool:
        nonlocal claimed_slots
        async with summary_lock:
            if max_profiles is not None and claimed_slots >= max_profiles:
                return False
            claimed_slots += 1
            return True

    async def increment(
        field: Literal["claimed", "completed", "requeued", "failed"],
    ) -> None:
        async with summary_lock:
            setattr(summary, field, getattr(summary, field) + 1)

    async def return_or_fail(profile: ClaimedProfile, error: str) -> None:
        if profile.profile_scrape_attempts >= max_profile_attempts:
            await asyncio.to_thread(
                repository.fail_profile, profile.source_profile_id, error
            )
            await increment("failed")
            return

        await asyncio.to_thread(
            repository.release_profile_claim, profile.source_profile_id, error
        )
        await increment("requeued")

    async def worker() -> None:
        while await reserve_claim_slot():
            claimed_row = await asyncio.to_thread(
                repository.claim_next_profile,
                status=status,
                created_since=created_since,
                source_city=source_city,
                source_state=source_state,
            )
            if claimed_row is None:
                return

            profile = ClaimedProfile.model_validate(claimed_row)
            await increment("claimed")
            proxy_lease = None
            try:
                if proxy is None:
                    proxy_lease = await asyncio.to_thread(
                        proxy_pool_service.acquire_proxy
                    )
                    if proxy_lease is None:
                        await asyncio.to_thread(
                            repository.release_profile_claim,
                            profile.source_profile_id,
                            "No active proxy was available for this profile",
                        )
                        await increment("requeued")
                        return

                current_proxy = proxy or proxy_lease.proxy_url
                session_options = {
                    "impersonate": "chrome",
                    "proxies": {"http": current_proxy, "https": current_proxy},
                }
                async with requests.AsyncSession(**session_options) as session:
                    response = await session.get(profile.profile_url, timeout=30)
                    response.raise_for_status()

                enrichment = enrich_profile(response.text, profile.profile_url)
                completed = await asyncio.to_thread(
                    repository.complete_profile,
                    profile.source_profile_id,
                    enrichment.model_dump(exclude_none=True),
                )
                if not completed:
                    raise LookupError(
                        f"Claimed profile {profile.source_profile_id} disappeared"
                    )
                await increment("completed")
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    repository.release_profile_claim,
                    profile.source_profile_id,
                    "Profile worker was cancelled before completion",
                )
                raise
            except Exception as exc:
                await return_or_fail(profile, f"{type(exc).__name__}: {exc}")
            finally:
                if proxy_lease is not None:
                    await asyncio.to_thread(
                        proxy_pool_service.release_proxy, proxy_lease.lease_token
                    )

    await asyncio.gather(*(worker() for _ in range(worker_count)))
    summary.finished_at = datetime.now(timezone.utc)
    return summary


if __name__ == "__main__":
    result = asyncio.run(
        scrape_pending_profiles(
            worker_count=10, max_profiles=150, created_within_hours=24
        )
    )
    print(result.model_dump_json(indent=2))
