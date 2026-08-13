"""Pydantic validation models for the website-scraping layer."""

from app.website_scraping.schemas.email_models import (
    ClaimedWebsite,
    EmailObservation,
    ScoredEmail,
    WebsitePage,
    WebsiteScrapeEnrichment,
)
from app.website_scraping.schemas.categorization_models import (
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
