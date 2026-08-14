"""Pydantic contracts for website practice categorisation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PracticeCategorizationResult(BaseModel):
    """Rule-based private- or group-practice result ready for database storage."""

    category: Literal["private_practice", "group_practice"]
    category_score: int = Field(ge=0, le=100)
    category_source: Literal["website_rule_based"] = "website_rule_based"
    category_evidence: list[str] = Field(default_factory=list)
