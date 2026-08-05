"""Collect Psychology Today profile URLs from a paginated directory."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

# Allow this file to be run directly from the repository root for testing.
_ROOT_DIR = Path(__file__).resolve().parents[3]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from app.directories.helpers import Helpers
from app.database.create_tables import create_tables
from app.database.repository import ProfileRepository, ScrapeRunRepository
from app.infrastructure.proxies.service import ProxyPoolService


_STATE_NAMES = {
    "al": "Alabama",
    "ak": "Alaska",
    "az": "Arizona",
    "ar": "Arkansas",
    "ca": "California",
    "co": "Colorado",
    "ct": "Connecticut",
    "de": "Delaware",
    "fl": "Florida",
    "ga": "Georgia",
    "hi": "Hawaii",
    "id": "Idaho",
    "il": "Illinois",
    "in": "Indiana",
    "ia": "Iowa",
    "ks": "Kansas",
    "ky": "Kentucky",
    "la": "Louisiana",
    "me": "Maine",
    "md": "Maryland",
    "ma": "Massachusetts",
    "mi": "Michigan",
    "mn": "Minnesota",
    "ms": "Mississippi",
    "mo": "Missouri",
    "mt": "Montana",
    "ne": "Nebraska",
    "nv": "Nevada",
    "nh": "New Hampshire",
    "nj": "New Jersey",
    "nm": "New Mexico",
    "ny": "New York",
    "nc": "North Carolina",
    "nd": "North Dakota",
    "oh": "Ohio",
    "ok": "Oklahoma",
    "or": "Oregon",
    "pa": "Pennsylvania",
    "ri": "Rhode Island",
    "sc": "South Carolina",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "tx": "Texas",
    "ut": "Utah",
    "vt": "Vermont",
    "va": "Virginia",
    "wa": "Washington",
    "wv": "West Virginia",
    "wi": "Wisconsin",
    "wy": "Wyoming",
    "dc": "District of Columbia",
}


def _directory_location(directory_url: str) -> tuple[str, str]:
    """This will return the full state and city name which is usually in an abbreviated format in a PT url.
    This is essential for source_city and source_state columns in the database for better lead sorting"""

    parts = [part for part in urlparse(directory_url).path.split("/") if part]
    if len(parts) < 4 or parts[:2] != ["us", "therapists"]:
        return "", ""

    state_code = parts[2].lower()
    city = unquote(parts[3]).replace("-", " ").title()
    return _STATE_NAMES.get(state_code, state_code.upper()), city


def _profile_id(profile_url: str) -> str:
    """Extract the individual profile ID from a Psychology Today URL.
    This is essential for creating our source_profile_id which helps in deduplication"""
    profile_path = urlparse(profile_url).path.rstrip("/")
    profile_id = profile_path.rsplit("/", 1)[-1]
    return profile_id if profile_id.isdigit() else ""


def _is_profile_url(url: str, directory_url: str) -> bool:
    parsed = urlparse(url)
    directory = urlparse(directory_url)
    path = parsed.path.rstrip("/")
    directory_path = directory.path.rstrip("/")
    if not Helpers.same_netloc(url, directory_url):
        return False
    if not path.startswith("/us/therapists/") or path == directory_path:
        return False
    parts = [part for part in path.split("/") if part]
    therapist_parts = parts[2:]
    if len(therapist_parts) >= 3:
        return True
    # Directory pages are /us/therapists/<state>/<city>. Some profile URLs
    # are /us/therapists/<name>/<profile-id>, so distinguish them by state.
    if len(therapist_parts) == 2:
        return therapist_parts[0].lower() not in {
            "al",
            "ak",
            "az",
            "ar",
            "ca",
            "co",
            "ct",
            "de",
            "fl",
            "ga",
            "hi",
            "id",
            "il",
            "in",
            "ia",
            "ks",
            "ky",
            "la",
            "me",
            "md",
            "ma",
            "mi",
            "mn",
            "ms",
            "mo",
            "mt",
            "ne",
            "nv",
            "nh",
            "nj",
            "nm",
            "ny",
            "nc",
            "nd",
            "oh",
            "ok",
            "or",
            "pa",
            "ri",
            "sc",
            "sd",
            "tn",
            "tx",
            "ut",
            "vt",
            "va",
            "wa",
            "wv",
            "wi",
            "wy",
            "dc",
        }
    return False


def _extract_links(
    html: str, page_url: str, directory_url: str
) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    profile_urls: list[str] = []
    next_candidates: list[tuple[int, str]] = []

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = Helpers.normalize_url(urljoin(page_url, href))
        if _is_profile_url(absolute, directory_url) and absolute not in profile_urls:
            profile_urls.append(absolute)

        rel_value = link.get("rel", [])
        rel = (
            rel_value if isinstance(rel_value, list) else str(rel_value).lower().split()
        )
        label = f"{link.get_text(' ', strip=True)} {link.get('aria-label', '')}".lower()
        if "next" in rel or "next page" in label or label.strip() == "next":
            next_candidates.append((0 if "next" in rel else 1, absolute))

    next_url = min(next_candidates)[1] if next_candidates else None
    return profile_urls, next_url


def scrape_profile_urls(
    start_url: str,
    max_profiles: int,
    max_pages: int,
    *,
    proxy: str | None = None,
    proxy_csv_path: str | Path | None = None,
    max_proxy_attempts: int = 3,
) -> dict[str, Any]:
    """Scrape profile URLs with one session and rotate proxies on page failures."""
    if max_profiles < 1 or max_pages < 1:
        raise ValueError("max_profiles and max_pages must both be at least 1")
    if not urlparse(start_url).scheme:
        raise ValueError("start_url must include http:// or https://")
    if max_proxy_attempts < 1:
        raise ValueError("max_proxy_attempts must be at least 1")

    create_tables()
    proxy_pool_service = ProxyPoolService(proxy_csv_path)
    proxy_pool_service.sync_from_csv()
    source_state, source_city = _directory_location(start_url)
    profile_repository = ProfileRepository()
    scrape_run_repository = ScrapeRunRepository()
    scrape_run = scrape_run_repository.start(
        directory=Helpers.directory_name(start_url),
        start_url=start_url,
        target_profile=max_profiles,
        max_pages=max_pages,
        next_page_url=start_url,
    )

    profile_urls: list[str] = []
    pages: list[dict[str, Any]] = []
    current_url: str | None = start_url

    session = None
    proxy_lease = None
    failed_attempts = 0
    try:
        if not proxy:
            proxy_lease = proxy_pool_service.acquire_proxy()
            if proxy_lease is None:
                raise RuntimeError("No active proxy is available in proxy_pool")

        while (
            current_url and len(pages) < max_pages and len(profile_urls) < max_profiles
        ):
            if proxy_lease and proxy_lease.lease_until <= (
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ):
                proxy_lease = proxy_pool_service.renew_proxy_lease(
                    proxy_lease.lease_token
                )
                if proxy_lease is None:
                    raise RuntimeError("Could not renew the proxy lease")

            if session is None:
                session_options: dict[str, Any] = {"impersonate": "chrome"}
                current_proxy = proxy or (
                    proxy_lease.proxy_url if proxy_lease else None
                )
                if current_proxy:
                    session_options["proxies"] = {
                        "http": current_proxy,
                        "https": current_proxy,
                    }
                session = requests.Session(**session_options)

            try:
                response = session.get(current_url, timeout=30)
                response.raise_for_status()
            except Exception:
                session.close()
                session = None
                if proxy_lease:
                    proxy_pool_service.release_proxy(proxy_lease.lease_token)
                    proxy_lease = None
                failed_attempts += 1
                if failed_attempts >= max_proxy_attempts:
                    raise
                if not proxy:
                    proxy_lease = proxy_pool_service.acquire_proxy()
                    if proxy_lease is None:
                        raise RuntimeError("No replacement proxy is available")
                continue

            failed_attempts = 0
            found_urls, next_url = _extract_links(response.text, current_url, start_url)
            for profile_url in found_urls:
                if profile_url not in profile_urls:
                    profile_urls.append(profile_url)
                    if len(profile_urls) >= max_profiles:
                        break

            profile_repository.save_scraped_profiles(
                {
                    "directory": Helpers.directory_name(start_url),
                    "source_profile_id": f"PT:{_profile_id(profile_url)}",
                    "profile_id": _profile_id(profile_url),
                    "profile_url": profile_url,
                    "source_city": source_city,
                    "source_state": source_state,
                }
                for profile_url in found_urls
            )
            pages.append({"url": current_url, "profile_urls": found_urls})
            scrape_run_repository.update(
                scrape_run.id,
                pages_completed=len(pages),
                unique_profile=len(profile_urls),
                last_completed_page_url=current_url,
                next_page_url=next_url,
            )
            current_url = next_url
    except KeyboardInterrupt:
        scrape_run_repository.finish(
            scrape_run.id,
            status="pending",
            last_error="Scrape interrupted by user",
        )
        raise
    except Exception as exc:
        scrape_run_repository.finish(
            scrape_run.id,
            status="failed",
            last_error=str(exc),
        )
        raise
    else:
        scrape_run_repository.finish(scrape_run.id, status="completed")
    finally:
        if session is not None:
            session.close()
        if proxy_lease:
            proxy_pool_service.release_proxy(proxy_lease.lease_token)

    return {
        "profiles": [
            {
                "directory": "psychology_today",
                "source_profile_id": f"PT:{_profile_id(profile_url)}",
                "start_url": start_url,
                "profile_id": _profile_id(profile_url),
                "profile_url": profile_url,
                "source_city": source_city,
                "source_state": source_state,
            }
            for profile_url in profile_urls[:max_profiles]
        ]
    }


if __name__ == "__main__":
    result = scrape_profile_urls(
        start_url="https://www.psychologytoday.com/us/therapists/tx/austin",
        max_profiles=100,
        max_pages=5,
    )
    print(f"Scraped {len(result['profiles'])} Psychology Today profiles.")
