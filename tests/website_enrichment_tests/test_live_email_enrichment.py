"""Live email-enrichment regression and fixture capture for therapist websites.

The first run fetches same-site pages with Curl CFFI and saves their HTML under
this test folder. Those saved fixtures can later power a smaller offline test.
"""

from __future__ import annotations

import json
import re
import sys
from collections import deque
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests
from pydantic import BaseModel


# Permit direct execution from the repository root during live validation.
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.website_scraping.schemas import WebsitePage
from app.website_scraping.email_enrichment import (
    clean_website_url,
    enrich_website_emails,
    get_url_priority,
    is_same_netloc,
    normalize_page_url,
)


# Keep this low because the test is about email enrichment, not full-site crawling.
MAX_PAGES_PER_WEBSITE = 30
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class EmailRegressionCase(BaseModel):
    """A manually verified therapist website and its expected direct email."""

    website_url: str
    first_name: str
    last_name: str
    expected_email: str


class EmailRegressionResult(BaseModel):
    """JSON-ready output from one live email-enrichment regression case."""

    website_url: str
    expected_email: str
    best_email: str | None
    best_email_score: float | None
    all_emails: str | None
    pages_collected: int
    fixture_directory: str
    passed: bool


CASES = (
    EmailRegressionCase(
        website_url="https://www.morganfitzgeraldtherapy.com/",
        first_name="Morgan",
        last_name="Fitzgerald",
        expected_email="morgan@morganfitzgeraldcounseling.com",
    ),
    EmailRegressionCase(
        website_url="https://www.drseamans.com/",
        first_name="Cindy",
        last_name="Seamans",
        expected_email="cindyseamans@drseamans.com",
    ),
)


def collect_same_site_pages(website_url: str) -> list[WebsitePage]:
    """Fetch and fixture-capture same-netloc pages in email-first priority order."""
    root_url = clean_website_url(website_url)
    pending = deque([root_url])
    discovered = {root_url}
    pages: list[WebsitePage] = []

    with requests.Session(impersonate="chrome") as session:
        while pending and len(pages) < MAX_PAGES_PER_WEBSITE:
            current_url = pending.popleft()
            response = session.get(current_url, timeout=30)
            # A website can expose stale internal links. They should not prevent
            # us from enriching email data from the pages that did load.
            if response.status_code >= 400:
                if not pages:
                    response.raise_for_status()
                continue
            page = WebsitePage(page_url=str(response.url), html=response.text)
            pages.append(page)

            for page_url in _extract_same_site_links(page.html, page.page_url, root_url):
                if page_url not in discovered:
                    discovered.add(page_url)
                    pending.append(page_url)

            pending = deque(sorted(pending, key=lambda url: (get_url_priority(url), url)))

    _save_fixtures(root_url, pages)
    return pages


def _extract_same_site_links(
    html: str, current_page_url: str, root_url: str
) -> list[str]:
    """Return normalized same-site links from one fetched HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for link in soup.select("a[href]"):
        page_url = normalize_page_url(link.get("href"), current_page_url)
        if page_url and is_same_netloc(root_url, page_url) and page_url not in links:
            links.append(page_url)
    return links


def _save_fixtures(website_url: str, pages: list[WebsitePage]) -> Path:
    """Save page URL and HTML per page so the live sample can become offline tests."""
    site_directory = FIXTURES_DIR / _fixture_directory_name(website_url)
    site_directory.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(pages, start=1):
        file_name = f"{index:02d}_{_safe_page_name(page.page_url)}.html"
        fixture = f"<!-- source_url: {page.page_url} -->\n{page.html}"
        (site_directory / file_name).write_text(fixture, encoding="utf-8")
    return site_directory


def _fixture_directory_name(website_url: str) -> str:
    """Create a stable folder name from a website hostname."""
    return re.sub(r"[^a-z0-9]+", "_", website_url.casefold()).strip("_")


def _safe_page_name(page_url: str) -> str:
    """Create a short filesystem-safe name that still conveys the page path."""
    path = page_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "home"
    return re.sub(r"[^a-z0-9]+", "_", path.casefold()).strip("_") or "page"


def run_live_email_regressions() -> list[EmailRegressionResult]:
    """Collect real pages, enrich their emails, assert expected emails, and return JSON."""
    results: list[EmailRegressionResult] = []
    for case in CASES:
        pages = collect_same_site_pages(case.website_url)
        enrichment = enrich_website_emails(
            pages,
            website_url=case.website_url,
            first_name=case.first_name,
            last_name=case.last_name,
        )
        fixture_directory = FIXTURES_DIR / _fixture_directory_name(case.website_url)
        result = EmailRegressionResult(
            website_url=case.website_url,
            expected_email=case.expected_email,
            best_email=enrichment.best_email,
            best_email_score=enrichment.best_email_score,
            all_emails=enrichment.all_emails,
            pages_collected=len(pages),
            fixture_directory=str(fixture_directory.relative_to(ROOT_DIR)),
            passed=(
                enrichment.best_email == case.expected_email
                and enrichment.best_email_score == 90.0
            ),
        )
        results.append(result)
    return results


if __name__ == "__main__":
    results = run_live_email_regressions()
    print(json.dumps([result.model_dump() for result in results], indent=2))
    if not all(result.passed for result in results):
        raise SystemExit("One or more live email enrichment regressions failed")
