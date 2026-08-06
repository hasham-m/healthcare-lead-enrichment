"""Automatically resume the first pending or failed scrape run."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow this utility to be run directly from the repository root.
_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from app.directories.psychology_today.pages_scraper import scrape_profile_urls
from app.directories.scrape_runs import ScrapeRunManager


def resume_first_available_run() -> dict | None:
    """Resume the first pending or failed run found in the database."""
    run_manager = ScrapeRunManager()
    run = run_manager.find_resumable()
    if run is None:
        print("No pending or failed scrape run is available to resume.")
        return None

    print(f"Resuming scrape run {run.id} with status '{run.status}'.")
    print(f"Starting from saved page URL: {run.next_page_url}")
    return scrape_profile_urls(
        start_url=run.start_url,
        max_profiles=run.target_profile,
        max_pages=run.max_pages,
        resume_run_id=run.id,
    )


if __name__ == "__main__":
    result = resume_first_available_run()
    if result is not None:
        print(f"Resumed and scraped {len(result['profiles'])} profiles.")
