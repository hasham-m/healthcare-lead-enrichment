"""Pydantic contracts for email extraction and scoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
