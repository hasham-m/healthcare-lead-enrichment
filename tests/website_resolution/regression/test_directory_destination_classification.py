"""Local regression checks for resolved URLs that point to directories."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel


# Add the repository root so this file can run directly as a Python module.
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.website_resolution.service import _classify_destination


class DirectoryDestinationCase(BaseModel):
    """One resolved URL expected to be classified as a directory."""

    website_url: str


class DirectoryDatabaseValues(BaseModel):
    """The database-ready values expected after directory URL resolution."""

    website_url: str
    destination_type: str
    website_scrape_eligible: bool
    passed: bool


# These are resolved website URLs, so no HTTP requests or proxies are needed.
DIRECTORY_CASES = (
    DirectoryDestinationCase(website_url="https://care.headway.co/"),
    DirectoryDestinationCase(website_url="https://www.zocdoc.com/"),
    DirectoryDestinationCase(
        website_url="https://apply.workable.com/psychology-today"
    ),
)


def run_directory_destination_regressions() -> list[DirectoryDatabaseValues]:
    """Return and assert the database values for known directory destinations."""
    results: list[DirectoryDatabaseValues] = []
    for case in DIRECTORY_CASES:
        # Use the same exact-host/subdomain classifier as the resolution service.
        destination_type = _classify_destination(case.website_url)
        # Directories must never be queued for the website scraping layer.
        website_scrape_eligible = destination_type == "owned_website"
        # Assert the expected database transition before returning JSON data.
        passed = (
            destination_type == "directory"
            and website_scrape_eligible is False
        )
        results.append(
            DirectoryDatabaseValues(
                website_url=case.website_url,
                destination_type=destination_type,
                website_scrape_eligible=website_scrape_eligible,
                passed=passed,
            )
        )
    return results


if __name__ == "__main__":
    # Print database-ready classification values in JSON for quick review.
    results = run_directory_destination_regressions()
    print(json.dumps([result.model_dump() for result in results], indent=2))
    # Fail the regression process if any known directory was misclassified.
    if not all(result.passed for result in results):
        raise SystemExit("One or more directory destination regressions failed")
