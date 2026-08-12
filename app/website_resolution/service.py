"""Async, proxy-backed resolution of directory website redirect URLs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

from app.database.create_tables import create_tables
from app.database.repository import PsychologyTodayWebsiteResolutionRepository
from app.directories.helpers import Helpers
from app.infrastructure.proxies.service import ProxyPoolService
from app.website_resolution.schemas import (
    ClaimedWebsiteRedirect,
    WebsiteResolutionResult,
    WebsiteResolutionSummary,
)


# PT's outbound endpoint must return one of these standard redirect statuses.
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class WebsiteRedirectResolutionError(RuntimeError):
    """Raised when an available redirect does not resolve to an external website."""


async def resolve_pending_websites(
    *,
    worker_count: int = 3,
    max_resolutions: int | None = None,
    status: Literal["pending", "failed"] = "pending",
    created_since: datetime | None = None,
    created_within_hours: int | None = None,
    source_city: str | None = None,
    source_state: str | None = None,
    max_resolution_attempts: int = 3,
    timeout_seconds: int = 20,
    proxy: str | None = None,
    proxy_csv_path: str | Path | None = None,
) -> WebsiteResolutionSummary:
    """Resolve pending PT redirects concurrently without using an async queue.

    Every worker repeatedly claims a row directly from PostgreSQL. The database
    lock and processing flag prevent two workers from resolving the same URL.
    """
    # Reject invalid worker counts before opening database or proxy resources.
    if worker_count < 1:
        raise ValueError("worker_count must be at least 1")
    # A provided maximum must represent at least one resolution job.
    if max_resolutions is not None and max_resolutions < 1:
        raise ValueError("max_resolutions must be at least 1 when provided")
    # Retry limits must allow at least the initial resolution attempt.
    if max_resolution_attempts < 1:
        raise ValueError("max_resolution_attempts must be at least 1")
    # Timeout is a maximum request duration; successful redirects return sooner.
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1")
    # Avoid ambiguous time filtering at the public service boundary.
    if created_since is not None and created_within_hours is not None:
        raise ValueError("Pass either created_since or created_within_hours, not both")
    # Convert a simple hours input into the UTC datetime expected by SQLAlchemy.
    if created_within_hours is not None:
        created_since = Helpers.utc_hours_ago(created_within_hours)

    # Ensure current tables and migrations exist before workers query them.
    await asyncio.to_thread(create_tables)
    # Use the dedicated repository for website-resolution state transitions.
    repository = PsychologyTodayWebsiteResolutionRepository()
    # Reuse the existing proxy service and its lease rules.
    proxy_pool_service = ProxyPoolService(proxy_csv_path)

    if proxy is None:
        # Sync CSV definitions before leasing database-managed proxies.
        await asyncio.to_thread(proxy_pool_service.sync_from_csv)
        # Limit concurrency to currently available proxy capacity.
        available_proxy_count = len(
            await asyncio.to_thread(proxy_pool_service.active_proxy_urls)
        )
        if available_proxy_count == 0:
            raise RuntimeError("No active proxy is available in proxy_pool")
        worker_count = min(worker_count, available_proxy_count)

    # Track all counts in one Pydantic-validated result object.
    summary = WebsiteResolutionSummary(started_at=datetime.now(timezone.utc))
    # Protect counters and the maximum-job reservation from concurrent workers.
    summary_lock = asyncio.Lock()
    claimed_slots = 0

    async def reserve_claim_slot() -> bool:
        """Reserve one potential database claim without introducing an async queue."""
        nonlocal claimed_slots
        async with summary_lock:
            if max_resolutions is not None and claimed_slots >= max_resolutions:
                return False
            claimed_slots += 1
            return True

    async def increment(
        field: Literal["claimed", "completed", "requeued", "failed"],
    ) -> None:
        """Safely increase one summary counter shared by all workers."""
        async with summary_lock:
            setattr(summary, field, getattr(summary, field) + 1)

    async def return_or_fail(
        claimed_redirect: ClaimedWebsiteRedirect, error: str
    ) -> None:
        """Requeue transient failures or mark terminal failures after the limit."""
        if claimed_redirect.website_resolution_attempts >= max_resolution_attempts:
            await asyncio.to_thread(
                repository.fail_resolution,
                claimed_redirect.source_profile_id,
                error,
            )
            await increment("failed")
            return

        await asyncio.to_thread(
            repository.release_resolution_claim,
            claimed_redirect.source_profile_id,
            error,
        )
        await increment("requeued")

    async def worker() -> None:
        """Claim and resolve rows until no job remains for this worker."""
        while await reserve_claim_slot():
            # Claim one row atomically; the synchronous database work runs in a thread.
            claimed_row = await asyncio.to_thread(
                repository.claim_next_redirect,
                status=status,
                created_since=created_since,
                source_city=source_city,
                source_state=source_state,
            )
            if claimed_row is None:
                return

            # Validate the repository payload before using it as a request target.
            claimed_redirect = ClaimedWebsiteRedirect.model_validate(claimed_row)
            await increment("claimed")
            # A lease is populated only when the caller did not supply a proxy URL.
            proxy_lease = None

            try:
                if proxy is None:
                    # Acquire one least-used proxy for this one redirect-resolution session.
                    proxy_lease = await asyncio.to_thread(
                        proxy_pool_service.acquire_proxy
                    )
                    if proxy_lease is None:
                        # Do not mark a URL failed merely because all proxies are busy.
                        await asyncio.to_thread(
                            repository.release_resolution_claim,
                            claimed_redirect.source_profile_id,
                            "No active proxy was available for this redirect",
                        )
                        await increment("requeued")
                        return

                # Use an explicit caller proxy or the leased database proxy.
                current_proxy = proxy or proxy_lease.proxy_url
                # Configure the async browser-like HTTP session for the single redirect.
                session_options = {
                    "impersonate": "chrome",
                    "proxies": {"http": current_proxy, "https": current_proxy},
                }
                # The context manager closes the HTTP session immediately after resolution.
                async with requests.AsyncSession(**session_options) as session:
                    final_url = await _resolve_psychology_today_redirect(
                        session,
                        claimed_redirect.pt_website_redirect,
                        timeout_seconds,
                    )

                # Validate the final external URL before it can be saved to the database.
                resolution = WebsiteResolutionResult(
                    source_profile_id=claimed_redirect.source_profile_id,
                    website_url=final_url,
                    resolved_at=datetime.now(timezone.utc),
                )
                # Persist the final URL and queue the next website-scrape stage.
                completed = await asyncio.to_thread(
                    repository.complete_resolution,
                    resolution.source_profile_id,
                    resolution.website_url,
                )
                if not completed:
                    raise LookupError(
                        "Claimed redirect disappeared before resolution completed"
                    )
                await increment("completed")
            except asyncio.CancelledError:
                # Return the row to pending when the caller stops the worker task.
                await asyncio.to_thread(
                    repository.release_resolution_claim,
                    claimed_redirect.source_profile_id,
                    "Website resolution worker was cancelled before completion",
                )
                raise
            except Exception as exc:
                # Store the request/validation error and decide retry versus terminal failure.
                await return_or_fail(
                    claimed_redirect,
                    f"{type(exc).__name__}: {exc}",
                )
            finally:
                if proxy_lease is not None:
                    # Always release a leased proxy, including after failures or cancellation.
                    await asyncio.to_thread(
                        proxy_pool_service.release_proxy,
                        proxy_lease.lease_token,
                    )

    # Run independent workers concurrently; their work source remains PostgreSQL.
    await asyncio.gather(*(worker() for _ in range(worker_count)))
    # Stamp completion after every worker has returned.
    summary.finished_at = datetime.now(timezone.utc)
    return summary


def build_psychology_today_redirect_endpoint(pt_redirect_url: str) -> str:
    """Build PT's server-side outbound endpoint from its profile redirect URL."""
    # Parse the database value without requesting the slow browser-facing page.
    parsed = urlparse(pt_redirect_url)
    # A valid PT redirect has the shape: /us/profile/<profile-id>/website.
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme not in {"http", "https"}
        or not (parsed.hostname or "").endswith("psychologytoday.com")
        or len(parts) != 4
        or parts[0] != "us"
        or parts[1] != "profile"
        or not parts[2].isdigit()
        or parts[3] != "website"
    ):
        raise ValueError(f"Unexpected Psychology Today redirect URL: {pt_redirect_url}")

    # This endpoint returns the external website in a 30x Location header.
    return f"https://out.psychologytoday.com/us/profile/{parts[2]}/website-redirect"


async def _resolve_psychology_today_redirect(
    session: requests.AsyncSession,
    pt_redirect_url: str,
    timeout_seconds: int,
) -> str:
    """Resolve one PT redirect through its server-side outbound endpoint."""
    # Build the direct outbound endpoint locally; this does not wait or use I/O.
    outbound_url = build_psychology_today_redirect_endpoint(pt_redirect_url)
    # Do not follow the 30x response because its Location header is the value we need.
    response = await session.get(
        outbound_url,
        timeout=timeout_seconds,
        allow_redirects=False,
        headers={"Referer": "https://www.psychologytoday.com/"},
    )
    # The endpoint must return a standard redirect, not a successful interstitial page.
    if response.status_code not in _REDIRECT_STATUS_CODES:
        raise WebsiteRedirectResolutionError(
            f"PT outbound endpoint returned unexpected status {response.status_code}"
        )
    # Read the external website target directly from the server response headers.
    location = response.headers.get("location")
    if not location:
        raise WebsiteRedirectResolutionError(
            "PT outbound endpoint returned no Location header"
        )
    # Resolve any relative Location safely against the PT outbound endpoint.
    return urljoin(outbound_url, location)


if __name__ == "__main__":
    # Provide a small manual run without changing the function's reusable API.
    result = asyncio.run(
        resolve_pending_websites(worker_count=3, max_resolutions=10, hours=48)
    )
    print(result.model_dump_json(indent=2))
