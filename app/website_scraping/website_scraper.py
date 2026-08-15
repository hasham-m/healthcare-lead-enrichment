"""Async workers that crawl and enrich eligible therapist-owned websites."""

from __future__ import annotations

import asyncio
import heapq
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Literal

from bs4 import BeautifulSoup
from curl_cffi import requests

from app.database.create_tables import create_tables
from app.database.repository import PsychologyTodayWebsiteScrapeRepository
from app.infrastructure.proxies.service import ProxyLease, ProxyPoolService
from app.website_scraping.email_enrichment import enrich_website_emails
from app.website_scraping.helpers import (
    clean_website_url,
    get_url_priority,
    is_same_netloc,
    normalize_page_url,
)
from app.website_scraping.practice_categorization import categorize_practice
from app.website_scraping.schemas import (
    ClaimedWebsite,
    WebsitePage,
    WebsiteScrapeEnrichment,
    WebsiteScrapeSummary,
)


async def scrape_pending_websites(
    *,
    worker_count: int = 3,
    max_websites: int | None = None,
    max_pages_per_website: int = 8,
    status: Literal["pending", "failed"] = "pending",
    created_since: datetime | None = None,
    created_within_hours: int | None = None,
    source_city: str | None = None,
    source_state: str | None = None,
    max_website_attempts: int = 3,
    proxy: str | None = None,
    proxy_csv_path: str | Path | None = None,
) -> WebsiteScrapeSummary:
    """Claim eligible websites, crawl same-site pages, enrich, and persist results.

    A worker keeps one proxy lease for one complete website session, including all
    prioritized subpages. PostgreSQL claim flags prevent another worker from
    processing that website while the HTTP work is in progress.
    """
    _validate_options(
        worker_count=worker_count,
        max_websites=max_websites,
        max_pages_per_website=max_pages_per_website,
        created_since=created_since,
        created_within_hours=created_within_hours,
        max_website_attempts=max_website_attempts,
    )
    if created_within_hours is not None:
        created_since = datetime.now(timezone.utc) - timedelta(
            hours=created_within_hours
        )

    await asyncio.to_thread(create_tables)
    repository = PsychologyTodayWebsiteScrapeRepository()
    proxy_service = ProxyPoolService(proxy_csv_path)
    if proxy is None:
        await asyncio.to_thread(proxy_service.sync_from_csv)
        available_proxies = await asyncio.to_thread(proxy_service.active_proxy_urls)
        if not available_proxies:
            raise RuntimeError("No active proxy is available in proxy_pool")
        worker_count = min(worker_count, len(available_proxies))

    summary = WebsiteScrapeSummary(started_at=datetime.now(timezone.utc))
    summary_lock = asyncio.Lock()
    claimed_slots = 0

    async def reserve_slot() -> bool:
        nonlocal claimed_slots
        async with summary_lock:
            if max_websites is not None and claimed_slots >= max_websites:
                return False
            claimed_slots += 1
            return True

    async def increment(
        field: Literal["claimed", "completed", "requeued", "failed", "pages_scraped"],
        value: int = 1,
    ) -> None:
        async with summary_lock:
            setattr(summary, field, getattr(summary, field) + value)

    async def requeue_or_fail(website: ClaimedWebsite, error: str) -> None:
        if website.website_scrape_attempts >= max_website_attempts:
            await asyncio.to_thread(
                repository.fail_website_scrape, website.source_profile_id, error
            )
            await increment("failed")
            return
        await asyncio.to_thread(
            repository.release_website_claim, website.source_profile_id, error
        )
        await increment("requeued")

    async def worker() -> None:
        while await reserve_slot():
            claimed_row = await asyncio.to_thread(
                repository.claim_next_website,
                status=status,
                created_since=created_since,
                source_city=source_city,
                source_state=source_state,
            )
            if claimed_row is None:
                return

            website = ClaimedWebsite.model_validate(claimed_row)
            await increment("claimed")
            proxy_lease: ProxyLease | None = None
            try:
                if proxy is None:
                    proxy_lease = await asyncio.to_thread(proxy_service.acquire_proxy)
                    if proxy_lease is None:
                        raise RuntimeError(
                            "No active proxy was available for this website"
                        )

                pages = await _crawl_website(
                    website.website_url,
                    proxy_url=proxy or proxy_lease.proxy_url,
                    max_pages=max_pages_per_website,
                    proxy_service=proxy_service if proxy_lease is not None else None,
                    lease_token=proxy_lease.lease_token
                    if proxy_lease is not None
                    else None,
                )
                enrichment = _enrich_website(website, pages)
                completed = await asyncio.to_thread(
                    repository.complete_website_scrape,
                    website.source_profile_id,
                    enrichment.model_dump(exclude_none=True),
                )
                if not completed:
                    raise LookupError(
                        f"Claimed website {website.source_profile_id} disappeared"
                    )
                await increment("completed")
                await increment("pages_scraped", len(pages))
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    repository.release_website_claim,
                    website.source_profile_id,
                    "Website worker was cancelled before completion",
                )
                raise
            except Exception as exc:
                await requeue_or_fail(website, f"{type(exc).__name__}: {exc}")
            finally:
                if proxy_lease is not None:
                    await asyncio.to_thread(
                        proxy_service.release_proxy, proxy_lease.lease_token
                    )

    await asyncio.gather(*(worker() for _ in range(worker_count)))
    summary.finished_at = datetime.now(timezone.utc)
    return summary


async def _crawl_website(
    website_url: str,
    *,
    proxy_url: str,
    max_pages: int,
    proxy_service: ProxyPoolService | None = None,
    lease_token: str | None = None,
) -> list[WebsitePage]:
    """Crawl unique same-netloc pages in heap-priority order using one proxy."""
    root_url = clean_website_url(website_url)
    if not root_url:
        raise ValueError("Website URL is empty after normalization")

    queue: list[tuple[int, int, str]] = [(get_url_priority(root_url), 0, root_url)]
    queued_urls = {root_url}
    fetched_urls: set[str] = set()
    pages: list[WebsitePage] = []
    sequence = 1
    last_lease_renewal = monotonic()
    session_options = {
        "impersonate": "chrome",
        "proxies": {"http": proxy_url, "https": proxy_url},
    }

    async with requests.AsyncSession(**session_options) as session:
        while queue and len(pages) < max_pages:
            if (
                proxy_service is not None
                and lease_token is not None
                and monotonic() - last_lease_renewal >= 5 * 60
            ):
                renewed = await asyncio.to_thread(
                    proxy_service.renew_proxy_lease, lease_token
                )
                if renewed is None:
                    raise RuntimeError("Proxy lease expired during website crawl")
                last_lease_renewal = monotonic()
            _, _, current_url = heapq.heappop(queue)
            if current_url in fetched_urls:
                continue

            response = await session.get(current_url, timeout=30)
            response.raise_for_status()
            final_url = normalize_page_url(str(response.url), current_url)
            if not final_url or not is_same_netloc(root_url, final_url):
                if not pages:
                    raise ValueError(
                        f"Website root redirected outside its netloc: {response.url}"
                    )
                continue
            if final_url in fetched_urls:
                continue

            fetched_urls.add(final_url)
            page = WebsitePage(page_url=final_url, html=response.text)
            pages.append(page)
            for next_url in _extract_same_netloc_links(page.html, final_url, root_url):
                if next_url not in queued_urls and next_url not in fetched_urls:
                    heapq.heappush(
                        queue, (get_url_priority(next_url), sequence, next_url)
                    )
                    queued_urls.add(next_url)
                    sequence += 1

    if not pages:
        raise RuntimeError(f"No pages could be fetched from {root_url}")
    return pages


def _extract_same_netloc_links(
    html: str, current_page_url: str, root_url: str
) -> list[str]:
    """Extract normalized crawl candidates that remain on the website's netloc."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.select("a[href]"):
        page_url = normalize_page_url(anchor.get("href"), current_page_url)
        if page_url and is_same_netloc(root_url, page_url) and page_url not in links:
            links.append(page_url)
    return links


def _enrich_website(
    website: ClaimedWebsite, pages: list[WebsitePage]
) -> WebsiteScrapeEnrichment:
    """Combine independent email and practice categorisation results for storage."""
    email_result = enrich_website_emails(
        pages,
        website_url=website.website_url,
        first_name=website.first_name,
        last_name=website.last_name,
    )
    categorization = categorize_practice(pages, website_url=website.website_url)
    return WebsiteScrapeEnrichment(
        **email_result.model_dump(exclude_none=True),
        category=categorization.category,
        category_source=categorization.category_source,
        category_score=float(categorization.category_score),
        category_evidence=json.dumps(categorization.category_evidence),
    )


def _validate_options(
    *,
    worker_count: int,
    max_websites: int | None,
    max_pages_per_website: int,
    created_since: datetime | None,
    created_within_hours: int | None,
    max_website_attempts: int,
) -> None:
    """Reject invalid run options before a database row can be claimed."""
    if worker_count < 1:
        raise ValueError("worker_count must be at least 1")
    if max_websites is not None and max_websites < 1:
        raise ValueError("max_websites must be at least 1 when provided")
    if max_pages_per_website < 1:
        raise ValueError("max_pages_per_website must be at least 1")
    if max_website_attempts < 1:
        raise ValueError("max_website_attempts must be at least 1")
    if created_since is not None and created_within_hours is not None:
        raise ValueError("Pass either created_since or created_within_hours, not both")
    if created_within_hours is not None and created_within_hours < 0:
        raise ValueError("created_within_hours must be zero or greater")


if __name__ == "__main__":
    result = asyncio.run(
        scrape_pending_websites(
            worker_count=10,
            max_websites=100,
            max_pages_per_website=8,
            created_within_hours=24,
        )
    )
    print(result.model_dump_json(indent=2))
