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

    # Internal row identifier, useful for logging and future metrics.
    id: int
    # Directory-specific profile identifier, used to finalize the same row.
    source_profile_id: str
    # Psychology Today redirect URL that should lead to the external website.
    pt_website_redirect: str
    # Number of resolution attempts after this claim incremented the counter.
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

    # The database row that should receive this resolved URL.
    source_profile_id: str
    # The final therapist website URL, after redirects have completed.
    website_url: str
    # UTC time when the final URL was resolved.
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

    # Number of database redirects claimed by this run.
    claimed: int = 0
    # Number of redirects resolved to a validated external website.
    completed: int = 0
    # Number of retryable failures returned to pending.
    requeued: int = 0
    # Number of terminal failures after the configured attempt limit.
    failed: int = 0
    # UTC time at which the worker run started.
    started_at: datetime
    # UTC time at which all workers finished.
    finished_at: datetime | None = None


ResolutionStatus = Literal["pending", "failed"]
