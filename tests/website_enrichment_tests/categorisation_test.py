"""Fixture-backed practice categorisation check for private and group practices."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.website_scraping.practice_categorization import categorize_practice
from app.website_scraping.schemas import WebsitePage
from tests.website_enrichment_tests.test_live_email_enrichment import (
    FIXTURES_DIR,
    collect_same_site_pages,
)


CASES = (
    {
        "name": "Morgan Fitzgerald Therapy",
        "website_url": "https://www.morganfitzgeraldtherapy.com/",
        "expected_category": "private_practice",
    },
    {
        "name": "Dr. Seamans",
        "website_url": "https://www.drseamans.com/",
        "expected_category": "private_practice",
    },
    {
        "name": "Inner Motions",
        "website_url": "https://www.inner-motions.org/",
        "expected_category": "group_practice",
    },
    {
        "name": "Ala Therapy Collective",
        "website_url": "https://www.alatherapycollective.com/",
        "expected_category": "group_practice",
    },
)


def load_or_capture_pages(website_url: str) -> list[WebsitePage]:
    """Use saved fixtures, capturing same-site pages only when a fixture is absent."""
    fixture_directory = FIXTURES_DIR / _fixture_directory_name(website_url)
    pages = _load_fixture_pages(fixture_directory)
    return pages if pages else collect_same_site_pages(website_url)


def _load_fixture_pages(fixture_directory: Path) -> list[WebsitePage]:
    """Load URL-tagged HTML fixtures saved by the existing Curl CFFI crawler."""
    pages: list[WebsitePage] = []
    for fixture_file in sorted(fixture_directory.glob("*.html")):
        fixture = fixture_file.read_text(encoding="utf-8")
        match = re.match(r"<!-- source_url: (.*?) -->\r?\n", fixture)
        if not match:
            continue
        pages.append(
            WebsitePage(
                page_url=match.group(1),
                html=fixture[match.end() :],
            )
        )
    return pages


def _fixture_directory_name(website_url: str) -> str:
    """Mirror the fixture naming convention used by the existing live crawler."""
    return re.sub(r"[^a-z0-9]+", "_", website_url.casefold()).strip("_")


def run_categorisation_checks() -> list[dict[str, object]]:
    """Categorize every sample and return terminal-friendly JSON records."""
    results: list[dict[str, object]] = []
    for case in CASES:
        pages = load_or_capture_pages(case["website_url"])
        categorization = categorize_practice(pages, website_url=case["website_url"])
        results.append(
            {
                "name": case["name"],
                "website_url": case["website_url"],
                "pages_used": len(pages),
                "expected_category": case["expected_category"],
                **categorization.model_dump(),
                "passed": categorization.category == case["expected_category"],
            }
        )
    return results


if __name__ == "__main__":
    results = run_categorisation_checks()
    print(json.dumps(results, indent=2))
    if not all(result["passed"] for result in results):
        raise SystemExit("One or more practice categorisation checks failed")
