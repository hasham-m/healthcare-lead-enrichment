"""Pydantic contracts shared across the website-scraping layer."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClaimedWebsite(BaseModel):
    """One eligible website atomically claimed by a future scraping worker."""

    model_config = ConfigDict(extra="ignore")

    id: int
    source_profile_id: str
    website_url: str
    website_scrape_attempts: int
    first_name: str | None = None
    last_name: str | None = None


class WebsitePage(BaseModel):
    """One fetched website page supplied to the enrichment workflow."""

    page_url: str
    html: str


class WebsiteScrapeEnrichment(BaseModel):
    """Website-derived data that can be saved after a scrape completes."""

    best_email: str | None = None
    best_email_score: float | None = None
    all_emails: str | None = None
    website_best_specialty: str | None = None
    website_all_specialties: str | None = None
    category: str | None = None
    category_source: str | None = None
    evidence_snippets: str | None = None
    category_score: float | None = None
    category_evidence: str | None = None


class WebsiteScrapeSummary(BaseModel):
    """Counters and timestamps returned by one website-scraping worker run."""

    started_at: datetime
    finished_at: datetime | None = None
    claimed: int = 0
    completed: int = 0
    requeued: int = 0
    failed: int = 0
    pages_scraped: int = 0
