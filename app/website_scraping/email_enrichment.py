"""Website enrichment workflow and parsing rules for therapist-owned websites."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from html import unescape
from os.path import commonprefix
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from app.website_scraping.schemas import (
    EmailObservation,
    ScoredEmail,
    WebsitePage,
    WebsiteScrapeEnrichment,
)
from app.website_scraping.helpers import get_url_priority

_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])"
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    r"(?![\w.-])",
    re.IGNORECASE,
)
_FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "aol.com",
    }
)
_PREFERRED_ROLE_LOCAL_PARTS = frozenset(
    {"contact", "hello", "info", "office", "intake", "appointments"}
)
_LOW_VALUE_LOCAL_PARTS = (
    "support",
    "blog",
    "webmaster",
    "marketing",
    "sales",
    "billing",
    "careers",
    "jobs",
    "press",
    "media",
    "privacy",
    "legal",
)
_REJECTED_LOCAL_PARTS = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "example",
        "test",
        "yourname",
        "name",
        "email",
    }
)
_REJECTED_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "wordpress.com",
        "wixpress.com",
        "squarespace.com",
    }
)
_REJECTED_TLDS = frozenset(
    {
        "css",
        "gif",
        "ico",
        "jpeg",
        "jpg",
        "js",
        "png",
        "svg",
        "ttf",
        "webp",
        "woff",
        "woff2",
    }
)


def enrich_website_emails(
    pages: Iterable[WebsitePage],
    *,
    website_url: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> WebsiteScrapeEnrichment:
    """Extract, rank, and return email enrichment from fetched website pages.

    Scores range from 0 to 90. A score of 70+ is strong, 60–69 is usable,
    40–59 should be reviewed, and candidates below 40 are never selected as the
    best email. Specialties and category fields intentionally remain empty.
    """
    observations: list[EmailObservation] = []
    for page in pages:
        observations.extend(extract_email_observations(page.html, page.page_url))

    scored_emails = _score_email_observations(
        observations,
        website_url=website_url,
        first_name=first_name,
        last_name=last_name,
    )
    retained_emails = [
        candidate for candidate in scored_emails if candidate.score >= 20
    ]
    best_candidate = retained_emails[0] if retained_emails else None
    if best_candidate is not None and best_candidate.score < 40:
        best_candidate = None

    return WebsiteScrapeEnrichment(
        best_email=best_candidate.email if best_candidate else None,
        best_email_score=float(best_candidate.score) if best_candidate else None,
        all_emails=(
            " | ".join(candidate.email for candidate in retained_emails)
            if retained_emails
            else None
        ),
        evidence_snippets=(
            json.dumps(
                [candidate.model_dump() for candidate in retained_emails],
                ensure_ascii=False,
            )
            if retained_emails
            else None
        ),
    )


def extract_email_observations(html: str, page_url: str) -> list[EmailObservation]:
    """Find valid email occurrences in mailto links and visible page text."""
    soup = BeautifulSoup(html or "", "html.parser")
    observations: list[EmailObservation] = []
    seen: set[tuple[str, str]] = set()

    for link in soup.select("a[href]"):
        href = unescape(str(link.get("href", ""))).strip()
        if not href.casefold().startswith("mailto:"):
            continue
        mailto_value = unquote(href[7:].split("?", 1)[0])
        snippet = _clean_snippet(link.get_text(" ", strip=True) or href)
        for email in _extract_valid_emails(mailto_value.replace(";", ",")):
            key = (email, "mailto")
            if key not in seen:
                observations.append(
                    EmailObservation(
                        email=email,
                        page_url=page_url,
                        source="mailto",
                        snippet=snippet,
                    )
                )
                seen.add(key)

    for unwanted in soup.select("script, style, noscript, svg"):
        unwanted.decompose()
    visible_text = _normalize_obfuscated_email_text(
        unescape(soup.get_text(" ", strip=True))
    )
    for match in _EMAIL_PATTERN.finditer(visible_text):
        email = _normalize_email(match.group(0))
        key = (email, "text")
        if email and key not in seen:
            observations.append(
                EmailObservation(
                    email=email,
                    page_url=page_url,
                    source="text",
                    snippet=_clean_snippet(
                        visible_text[max(0, match.start() - 80) : match.end() + 80]
                    ),
                )
            )
            seen.add(key)

    return observations


def _score_email_observations(
    observations: Iterable[EmailObservation],
    *,
    website_url: str,
    first_name: str | None,
    last_name: str | None,
) -> list[ScoredEmail]:
    """Deduplicate observations and apply transparent quality signals."""
    grouped: dict[str, list[EmailObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.email, []).append(observation)

    scored: list[ScoredEmail] = []
    for email, email_observations in grouped.items():
        local_part, email_domain = email.rsplit("@", 1)
        pages = sorted(
            {item.page_url for item in email_observations},
            key=lambda page_url: (get_url_priority(page_url), page_url),
        )
        sources = sorted(
            {item.source for item in email_observations},
            key=lambda source: 0 if source == "mailto" else 1,
        )

        score = 15
        score += 25 if "mailto" in sources else 12
        score += max(_email_page_bonus(page_url) for page_url in pages)
        score += _email_name_bonus(local_part, first_name, last_name)
        score += _email_domain_bonus(email_domain, website_url)
        score += min(10, max(0, len(pages) - 1) * 4)

        normalized_local = re.sub(r"[^a-z0-9]", "", local_part.casefold())
        if local_part.casefold() in _PREFERRED_ROLE_LOCAL_PARTS:
            score += 6
        if any(term in normalized_local for term in _LOW_VALUE_LOCAL_PARTS):
            score -= 35
        if len(grouped) == 1:
            score += 5
        if (
            _email_name_bonus(local_part, first_name, last_name) >= 15
            and _email_domain_bonus(email_domain, website_url) >= 15
        ):
            # A named address with a matching website brand is highly reliable,
            # regardless of which fetched page exposed it.
            score = max(score, 90)

        evidence = list(
            dict.fromkeys(
                f"{item.source} on {item.page_url}: {item.snippet}"
                for item in email_observations
            )
        )[:6]
        scored.append(
            ScoredEmail(
                email=email,
                score=max(0, min(90, score)),
                pages=pages,
                sources=sources,
                evidence=evidence,
            )
        )

    return sorted(scored, key=lambda candidate: (-candidate.score, candidate.email))


def _email_page_bonus(page_url: str) -> int:
    """Convert crawl priority into an email-confidence contribution."""
    return {
        0: 2,
        10: 6,
        20: 4,
        30: 2,
        40: 4,
        50: 1,
        60: 0,
        80: -3,
        200: -6,
    }.get(get_url_priority(page_url), 0)


def _email_name_bonus(
    local_part: str,
    first_name: str | None,
    last_name: str | None,
) -> int:
    """Reward personal email local-parts that match the claimed profile name."""
    local = re.sub(r"[^a-z0-9]", "", local_part.casefold())
    first = re.sub(r"[^a-z0-9]", "", (first_name or "").casefold())
    last = re.sub(r"[^a-z0-9]", "", (last_name or "").casefold())
    if first and last and (first + last in local or last + first in local):
        return 30
    if first and last and first in local and last in local:
        return 25
    if first and first in local:
        return 15
    if last and last in local:
        return 10
    return 0


def _email_domain_bonus(email_domain: str, website_url: str) -> int:
    """Prefer the website's own domain, then trusted personal email providers."""
    website_host = (
        (urlparse(website_url).hostname or "").casefold().removeprefix("www.")
    )
    domain = email_domain.casefold().removeprefix("www.")
    if website_host and (
        domain == website_host
        or domain.endswith(f".{website_host}")
        or website_host.endswith(f".{domain}")
    ):
        return 20
    if _domains_share_brand_token(domain, website_host):
        return 15
    if domain in _FREE_EMAIL_DOMAINS:
        return 10
    return -12


def _domains_share_brand_token(first_domain: str, second_domain: str) -> bool:
    """Recognize a substantial shared brand token across two different domains."""
    first_label = first_domain.split(".", 1)[0]
    second_label = second_domain.split(".", 1)[0]
    return len(commonprefix((first_label, second_label))) >= 8


def _extract_valid_emails(value: str) -> list[str]:
    """Extract unique, normalized email addresses from one string."""
    emails: list[str] = []
    for match in _EMAIL_PATTERN.finditer(value):
        email = _normalize_email(match.group(0))
        if email and email not in emails:
            emails.append(email)
    return emails


def _normalize_email(value: str) -> str:
    """Normalize an email and reject placeholders, assets, and vendor addresses."""
    email = value.strip(" <>[](){}.,;:'\"").casefold()
    if len(email) > 254 or email.count("@") != 1:
        return ""
    local_part, domain = email.rsplit("@", 1)
    if (
        not local_part
        or len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or local_part in _REJECTED_LOCAL_PARTS
        or domain in _REJECTED_EMAIL_DOMAINS
        or domain.rsplit(".", 1)[-1] in _REJECTED_TLDS
    ):
        return ""
    return email


def _normalize_obfuscated_email_text(value: str) -> str:
    """Decode conservative forms such as ``name [at] domain [dot] com``."""
    value = re.sub(
        r"\b([a-z0-9._%+-]+)\s+at\s+([a-z0-9-]+(?:\s+dot\s+[a-z0-9-]+)+)\b",
        lambda match: (
            f"{match.group(1)}@" + re.sub(r"\s+dot\s+", ".", match.group(2), flags=re.I)
        ),
        value,
        flags=re.I,
    )
    value = re.sub(r"\s*(?:\[at\]|\(at\)|\{at\})\s*", "@", value, flags=re.I)
    value = re.sub(r"\s*(?:\[dot\]|\(dot\)|\{dot\})\s*", ".", value, flags=re.I)
    return value


def _clean_snippet(value: str) -> str:
    """Collapse evidence text to a compact database-friendly snippet."""
    return " ".join(value.split())[:240]
