"""Fetch selected Psychology Today profiles and export parser output to CSV.

This is a manual integration test. It never reads, claims, inserts, or updates
the ``psychology_today`` table. Proxy leases use ``proxy_pool`` normally so the
same proxy path as production profile workers is exercised.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests
from pydantic import BaseModel, ConfigDict


# Allow direct execution with: uv run python tests/psychology_today/Pt_profile_enrichment_test.py
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.directories.psychology_today.profile_enrichment import enrich_profile
from app.directories.schemas import ProfileEnrichment
from app.infrastructure.proxies.service import ProxyPoolService


class TestProfile(BaseModel):
    """One manually selected profile and the expectation to review in the CSV."""

    profile_url: str
    expectation: str | None = None


class EnrichmentCsvRow(ProfileEnrichment):
    """A Pydantic-validated CSV row produced by this integration test."""

    model_config = ConfigDict(extra="forbid")

    profile_url: str
    expectation: str | None = None
    http_status: int | None = None
    proxy_id: int | None = None
    fetched_at: datetime
    error: str | None = None


TEST_PROFILES = [
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/nancy-key-new-york-ny/971161"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/nadi-badilla-austin-tx/851952"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/melody-montano-austin-tx/133384"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/ileana-gonzalez-austin-tx/1568695"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/chelsa-daniels-austin-tx/1674222"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/jordan-sanders-austin-tx/1657074"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/vic-garcia-austin-tx/1733232"
    ),
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/fatima-williams-austin-tx/894683",
        expectation="Not accepting new clients",
    ),  # Not accepting new clients
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/martha-pulkingham-austin-tx/155721",
        expectation="No website",
    ),  # No website
    TestProfile(
        profile_url="https://www.psychologytoday.com/us/therapists/susana-kugeares-austin-tx/862681",
        expectation="No website",
    ),  # No website
]

CSV_OUTPUT_PATH = ROOT_DIR / "pt_profile_enrichment_results.csv"


async def fetch_profile(
    profile: TestProfile, proxy_pool_service: ProxyPoolService
) -> EnrichmentCsvRow:
    """Fetch, Pydantic-validate, and return one profile without touching it in the DB."""
    fetched_at = datetime.now(timezone.utc)
    proxy_lease = await asyncio.to_thread(proxy_pool_service.acquire_proxy)
    if proxy_lease is None:
        return EnrichmentCsvRow(
            profile_url=profile.profile_url,
            expectation=profile.expectation,
            fetched_at=fetched_at,
            error="No active proxy was available",
        )

    try:
        async with requests.AsyncSession(
            impersonate="chrome",
            proxies={
                "http": proxy_lease.proxy_url,
                "https": proxy_lease.proxy_url,
            },
        ) as session:
            response = await session.get(profile.profile_url, timeout=30)
            response.raise_for_status()

        enrichment = ProfileEnrichment.model_validate(
            enrich_profile(response.text, profile.profile_url).model_dump()
        )
        return EnrichmentCsvRow(
            profile_url=profile.profile_url,
            expectation=profile.expectation,
            http_status=response.status_code,
            proxy_id=proxy_lease.id,
            fetched_at=fetched_at,
            **enrichment.model_dump(),
        )
    except Exception as exc:
        return EnrichmentCsvRow(
            profile_url=profile.profile_url,
            expectation=profile.expectation,
            proxy_id=proxy_lease.id,
            fetched_at=fetched_at,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        await asyncio.to_thread(
            proxy_pool_service.release_proxy, proxy_lease.lease_token
        )


async def run_profile_enrichment_test(
    worker_count: int = 3,
    output_path: Path = CSV_OUTPUT_PATH,
) -> Path:
    """Run the selected profiles concurrently and write their enriched CSV rows."""
    if worker_count < 1:
        raise ValueError("worker_count must be at least 1")

    proxy_pool_service = ProxyPoolService()
    await asyncio.to_thread(proxy_pool_service.sync_from_csv)
    available_proxy_count = len(
        await asyncio.to_thread(proxy_pool_service.active_proxy_urls)
    )
    if available_proxy_count == 0:
        raise RuntimeError("No active proxy is available in proxy_pool")

    semaphore = asyncio.Semaphore(min(worker_count, available_proxy_count))

    async def guarded_fetch(profile: TestProfile) -> EnrichmentCsvRow:
        async with semaphore:
            return await fetch_profile(profile, proxy_pool_service)

    rows = await asyncio.gather(*(guarded_fetch(profile) for profile in TEST_PROFILES))
    _write_csv(rows, output_path)
    return output_path


def _write_csv(rows: list[EnrichmentCsvRow], output_path: Path) -> None:
    """Write all validated rows in the same column order for easy review."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(EnrichmentCsvRow.model_fields)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            values: dict[str, Any] = row.model_dump(mode="json")
            writer.writerow(values)


if __name__ == "__main__":
    created_csv = asyncio.run(run_profile_enrichment_test())
    print(f"Wrote Pydantic-validated enrichment results to: {created_csv}")
