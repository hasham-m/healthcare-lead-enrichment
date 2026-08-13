"""Rule-based categorisation of therapist websites as private or group practices."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.website_scraping.schemas import (
    PracticeCategorizationResult,
    WebsitePage,
)


PRACTICE_GROUP_URL_HINTS = (
    "our-team",
    "meet-the-team",
    "meet-our-team",
    "team-4",
    "team",
    "staff",
    "providers",
    "provider",
    "clinicians",
    "clinician",
    "therapists",
    "therapist",
    "counselors",
    "counselor",
    "our-therapists",
    "our-clinicians",
    "our-providers",
    "provider-directory",
    "therapist-directory",
    "clinician-directory",
    "directory",
    "careers",
    "jobs",
    "leadership",
)
PRACTICE_PRIVATE_URL_HINTS = (
    "about-me",
    "contact-me",
    "work-with-me",
    "my-approach",
    "my-practice",
    "meet-me",
)
PRACTICE_GROUP_TEXT_HINTS = (
    "meet our team",
    "meet the team",
    "our team",
    "our therapists",
    "our clinicians",
    "our providers",
    "our counselors",
    "our staff",
    "clinical team",
    "provider team",
    "find a therapist",
    "find your therapist",
    "choose your therapist",
    "view all providers",
    "multiple locations",
    "our locations",
    "counseling center",
    "wellness center",
    "therapy center",
    "mental health center",
    "careers",
    "join our team",
    "we are hiring",
)
PRACTICE_PRIVATE_TEXT_HINTS = (
    "about me",
    "contact me",
    "work with me",
    "therapy with me",
    "my practice",
    "my approach",
    "i am a therapist",
    "i'm a therapist",
    "i provide therapy",
    "i specialize",
    "hi, i'm",
    "hello, i'm",
    "as your therapist",
)

_STRONG_GROUP_URL_HINTS = frozenset(
    {
        "our-team",
        "meet-the-team",
        "meet-our-team",
        "our-therapists",
        "our-clinicians",
        "our-providers",
        "provider-directory",
        "therapist-directory",
        "clinician-directory",
        "directory",
        "careers",
        "jobs",
        "leadership",
    }
)
_WEAK_GROUP_URL_HINTS = frozenset(
    {"team", "provider", "clinician", "therapist", "counselor"}
)


def categorize_practice(
    pages: Iterable[WebsitePage], *, website_url: str
) -> PracticeCategorizationResult:
    """Classify fetched same-site pages as a private or group practice.

    URL structure and page count have more weight than page text. Every input page
    is expected to have already passed the same-netloc rule in the crawler.
    """
    unique_pages = _unique_pages(pages)
    group_score = 0
    private_score = 0
    group_evidence: list[str] = []
    private_evidence: list[str] = []

    page_count = len(unique_pages)
    if page_count <= 3:
        private_score += 45
        private_evidence.append(f"Only {page_count} same-site pages were collected (private +45).")
    elif page_count < 12:
        private_score += 25
        private_evidence.append(f"Only {page_count} same-site pages were collected (private +25).")
    else:
        group_score += 30
        group_evidence.append(f"{page_count} same-site pages were collected (group +30).")

    hostname = (urlparse(website_url).hostname or "").casefold().removeprefix("www.")
    if hostname.endswith(".org"):
        group_score += 20
        group_evidence.append("The website uses a .org domain (group +20).")

    page_urls = tuple(page.page_url for page in unique_pages)
    group_url_hints = _matched_url_hints(page_urls, PRACTICE_GROUP_URL_HINTS)
    private_url_hints = _matched_url_hints(page_urls, PRACTICE_PRIVATE_URL_HINTS)
    for hint in group_url_hints:
        points = 18 if hint in _STRONG_GROUP_URL_HINTS else 3 if hint in _WEAK_GROUP_URL_HINTS else 9
        group_score += points
        group_evidence.append(f"URL hint '{hint}' indicates a group structure (group +{points}).")
    for hint in private_url_hints:
        private_score += 16
        private_evidence.append(f"URL hint '{hint}' indicates an individual practice (private +16).")

    site_text = "\n".join(_visible_text(page.html) for page in unique_pages).casefold()
    group_text_hints = _matched_text_hints(site_text, PRACTICE_GROUP_TEXT_HINTS)
    private_text_hints = _matched_text_hints(site_text, PRACTICE_PRIVATE_TEXT_HINTS)
    for hint in group_text_hints:
        group_score += 7
        group_evidence.append(f"Website text contains '{hint}' (group +7).")
    for hint in private_text_hints:
        private_score += 5
        private_evidence.append(f"Website text contains '{hint}' (private +5).")

    # A medium-sized site alone is not enough to call a practice a group: solo
    # practices can have many legal, FAQ, rate, and blog pages. It needs a
    # structural group signal unless the page set itself is exceptionally large.
    has_structural_group_evidence = bool(
        hostname.endswith(".org") or group_url_hints or group_text_hints
    )
    is_group_practice = group_score >= private_score and (
        has_structural_group_evidence or page_count >= 20
    )
    if is_group_practice:
        category = "group_practice"
        winning_score = group_score
        opposing_score = private_score
        evidence = group_evidence
    else:
        category = "private_practice"
        winning_score = private_score
        opposing_score = group_score
        evidence = private_evidence
        if not evidence and page_count >= 12:
            evidence.append(
                "A larger page count without team, provider, clinician, or .org "
                "signals is insufficient by itself to label a group practice."
            )

    return PracticeCategorizationResult(
        category=category,
        category_score=_confidence_score(winning_score, opposing_score),
        category_evidence=evidence[:12],
    )


def _unique_pages(pages: Iterable[WebsitePage]) -> list[WebsitePage]:
    """Retain one validated page per normalized URL while preserving crawl order."""
    unique: list[WebsitePage] = []
    seen: set[str] = set()
    for page in pages:
        url = page.page_url.rstrip("/").casefold() or "/"
        if url not in seen:
            seen.add(url)
            unique.append(page)
    return unique


def _matched_url_hints(page_urls: Iterable[str], hints: Iterable[str]) -> list[str]:
    """Find each supplied hint once in page-path segments, not the domain name."""
    matched: list[str] = []
    for hint in hints:
        normalized_hint = hint.casefold()
        if any(normalized_hint in urlparse(page_url).path.casefold() for page_url in page_urls):
            matched.append(hint)
    return matched


def _matched_text_hints(text: str, hints: Iterable[str]) -> list[str]:
    """Find each categorisation phrase once in the visible same-site page text."""
    return [hint for hint in hints if hint.casefold() in text]


def _visible_text(html: str) -> str:
    """Extract human-visible content without scripts, styles, or hidden markup noise."""
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup.select("script, style, noscript, svg"):
        element.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _confidence_score(winning_score: int, opposing_score: int) -> int:
    """Return a bounded confidence that rewards both evidence and separation."""
    margin = winning_score - opposing_score
    return max(50, min(100, 50 + min(35, winning_score // 2) + min(15, margin // 3)))
