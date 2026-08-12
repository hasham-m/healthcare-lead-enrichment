"""Pydantic contracts for claiming and enriching therapist-owned websites."""

from __future__ import annotations

from typing import Literal

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


class EmailObservation(BaseModel):
    """One occurrence of an email found on one website page."""

    email: str
    page_url: str
    source: Literal["mailto", "text"]
    snippet: str


class ScoredEmail(BaseModel):
    """One deduplicated email with its score and supporting evidence."""

    email: str
    score: int = Field(ge=0, le=90)
    pages: list[str]
    sources: list[Literal["mailto", "text"]]
    evidence: list[str]


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
