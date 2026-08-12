"""Live regression checks for known Psychology Today website redirects.

This script does not claim or update ``psychology_today`` rows. It only uses
the proxy-pool lease path and the shared redirect resolver, then prints JSON.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from curl_cffi import requests
from pydantic import BaseModel


# Add the repository root so this file can run directly with ``uv run python``.
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.infrastructure.proxies.service import ProxyPoolService
from app.website_resolution.schemas import WebsiteResolutionResult
from app.website_resolution.service import _resolve_psychology_today_redirect


class RedirectRegressionCase(BaseModel):
    """One real PT redirect and the external website it must resolve to."""

    profile_name: str
    pt_website_redirect: str
    expected_website_url: str


class RedirectRegressionResult(BaseModel):
    """JSON-safe result for one live redirect assertion."""

    profile_name: str
    pt_website_redirect: str
    expected_website_url: str
    resolved_website_url: str | None = None
    proxy_id: int | None = None
    passed: bool
    error: str | None = None


# These URLs are intentionally real regression cases rather than HTML fixtures.
REGRESSION_CASES = (
    RedirectRegressionCase(
        profile_name="Fatima Williams",
        pt_website_redirect="https://www.psychologytoday.com/us/profile/894683/website",
        expected_website_url="https://www.solutionfocusedconsulting.org/",
    ),
    RedirectRegressionCase(
        profile_name="Vic Garcia",
        pt_website_redirect="https://www.psychologytoday.com/us/profile/1733232/website",
        expected_website_url="https://crezcowellness.com/",
    ),
)


async def resolve_regression_case(
    case: RedirectRegressionCase,
    proxy_pool_service: ProxyPoolService,
    *,
    timeout_seconds: int = 20,
) -> RedirectRegressionResult:
    """Resolve one live redirect with a leased proxy and assert its final URL."""
    # Each redirect gets its own normal proxy session, matching production behavior.
    proxy_lease = await asyncio.to_thread(proxy_pool_service.acquire_proxy)
    if proxy_lease is None:
        return RedirectRegressionResult(
            profile_name=case.profile_name,
            pt_website_redirect=case.pt_website_redirect,
            expected_website_url=case.expected_website_url,
            passed=False,
            error="No active proxy was available",
        )

    try:
        # Configure a browser-like async HTTP session through the leased proxy.
        async with requests.AsyncSession(
            impersonate="chrome",
            proxies={
                "http": proxy_lease.proxy_url,
                "https": proxy_lease.proxy_url,
            },
        ) as session:
            # Reuse the production PT outbound-endpoint resolution logic.
            resolved_url = await _resolve_psychology_today_redirect(
                session,
                case.pt_website_redirect,
                timeout_seconds,
            )

        # Validate that the result is an external HTTP(S) website URL.
        validated_resolution = WebsiteResolutionResult(
            source_profile_id="regression-test",
            website_url=resolved_url,
            destination_type="owned_website",
            website_scrape_eligible=True,
            resolved_at=datetime.now(timezone.utc),
        )
        # Compare canonical URLs so an optional final trailing slash is harmless.
        passed = _canonical_url(validated_resolution.website_url) == _canonical_url(
            case.expected_website_url
        )
        return RedirectRegressionResult(
            profile_name=case.profile_name,
            pt_website_redirect=case.pt_website_redirect,
            expected_website_url=case.expected_website_url,
            resolved_website_url=validated_resolution.website_url,
            proxy_id=proxy_lease.id,
            passed=passed,
            error=None if passed else "Resolved URL did not match the expected website",
        )
    except Exception as exc:
        # Preserve the error as JSON data so the failed redirect is easy to review.
        return RedirectRegressionResult(
            profile_name=case.profile_name,
            pt_website_redirect=case.pt_website_redirect,
            expected_website_url=case.expected_website_url,
            proxy_id=proxy_lease.id,
            passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        # Always release the proxy, even when the redirect or assertion fails.
        await asyncio.to_thread(
            proxy_pool_service.release_proxy,
            proxy_lease.lease_token,
        )


async def run_live_website_redirect_regressions() -> list[RedirectRegressionResult]:
    """Run both live redirect assertions and return their JSON-ready results."""
    # Use the normal CSV synchronization and proxy lease behavior.
    proxy_pool_service = ProxyPoolService()
    await asyncio.to_thread(proxy_pool_service.sync_from_csv)

    # Run both independent redirects concurrently through the normal proxy leases.
    return list(
        await asyncio.gather(
            *(resolve_regression_case(case, proxy_pool_service) for case in REGRESSION_CASES)
        )
    )


def _canonical_url(url: str) -> str:
    """Normalize URL casing and trailing slashes for stable redirect assertions."""
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


if __name__ == "__main__":
    # Resolve the known redirects and always print results in JSON for review.
    results = asyncio.run(run_live_website_redirect_regressions())
    print(json.dumps([result.model_dump() for result in results], indent=2))
    # Exit with a test failure after printing JSON if either assertion failed.
    if not all(result.passed for result in results):
        raise SystemExit("One or more website redirect regressions failed")
