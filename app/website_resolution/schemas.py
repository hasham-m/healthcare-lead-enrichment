"""Pydantic models for website redirect-resolution jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator


class ClaimedWebsiteRedirect(BaseModel):
    """One website redirect atomically claimed from the database."""

    # Ignore extra database fields so the claim payload can grow safely later.
    model_config = ConfigDict(extra="ignore")

    id: int
    source_profile_id: str
    pt_website_redirect: str
    website_resolution_attempts: int

    @field_validator("pt_website_redirect")
    @classmethod
    def validate_redirect_url(cls, value: str) -> str:
        """Reject unavailable or malformed URLs before a worker requests them."""
        parsed = urlparse(value)
        if value == "__unavailable__" or parsed.scheme not in {"http", "https"}:
            raise ValueError("pt_website_redirect must be an available HTTP(S) URL")
        if not parsed.netloc:
            raise ValueError("pt_website_redirect must include a hostname")
        return value


class WebsiteResolutionResult(BaseModel):
    """A validated final external URL returned by redirect resolution."""

    source_profile_id: str
    website_url: str
    destination_type: Literal["directory", "owned_website"]
    website_scrape_eligible: bool
    resolved_at: datetime

    @field_validator("website_url")
    @classmethod
    def validate_external_website_url(cls, value: str) -> str:
        """Allow only external HTTP(S) URLs as resolved therapist websites."""
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ValueError("website_url must be an HTTP(S) URL with a hostname")
        if hostname == "psychologytoday.com" or hostname.endswith(
            ".psychologytoday.com"
        ):
            raise ValueError("website_url must resolve outside Psychology Today")
        return value


class WebsiteResolutionSummary(BaseModel):
    """Counters returned by one async website-resolution run."""

    claimed: int = 0
    completed: int = 0
    requeued: int = 0
    failed: int = 0
    started_at: datetime
    finished_at: datetime | None = None


ResolutionStatus = Literal["pending", "failed"]
