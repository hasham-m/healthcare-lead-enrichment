"""Pydantic validation models for the website-scraping layer."""

from app.website_scraping.schemas.email import (
    EmailObservation,
    ScoredEmail,
)
from app.website_scraping.schemas.website import (
    ClaimedWebsite,
    WebsitePage,
    WebsiteScrapeEnrichment,
)
from app.website_scraping.schemas.categorization import (
    PracticeCategorizationResult,
)

__all__ = [
    "ClaimedWebsite",
    "EmailObservation",
    "PracticeCategorizationResult",
    "ScoredEmail",
    "WebsitePage",
    "WebsiteScrapeEnrichment",
]
