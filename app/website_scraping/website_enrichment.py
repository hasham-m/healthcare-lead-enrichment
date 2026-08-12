"""Website enrichment workflow and parsing rules for therapist-owned websites."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from html import unescape
from urllib.parse import unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.website_scraping.schemas import (
    EmailObservation,
    ScoredEmail,
    WebsitePage,
    WebsiteScrapeEnrichment,
)


_SKIPPED_LINK_PREFIXES = ("mailto:", "tel:", "sms:", "javascript:", "#")

_CONTACT_KEYWORDS = (
    "contact",
    "appointment",
    "schedule",
    "book",
    "consult",
    "intake",
    "get-started",
    "start-here",
)
_ABOUT_KEYWORDS = ("about", "meet", "bio", "our-story")
_SERVICE_KEYWORDS = (
    "service",
    "services",
    "therapy",
    "therapies",
    "counseling",
    "counselling",
    "treatment",
    "specialties",
    "specialty",
    "areas",
)
_TEAM_KEYWORDS = ("team", "staff", "therapists", "clinicians", "providers")
_FAQ_KEYWORDS = ("faq", "faqs", "questions")
_CONTENT_KEYWORDS = ("blog", "article", "articles", "post", "news", "resources")
_LOW_VALUE_KEYWORDS = (
    "privacy",
    "terms",
    "cookie",
    "cookies",
    "disclaimer",
    "accessibility",
    "sitemap",
)

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
    {"css", "gif", "ico", "jpeg", "jpg", "js", "png", "svg", "ttf", "webp", "woff", "woff2"}
)


def clean_website_url(raw_url: object) -> str:
    """Return a fetchable HTTPS URL from a database website value.

    Example:
        ``drseamans.com`` becomes ``https://drseamans.com``.
    """
    # Database values can be null, empty, or non-string values.
    if raw_url is None:
        return ""

    # Normalize surrounding whitespace before validating the URL shape.
    url = str(raw_url).strip()
    if not url:
        return ""

    # Convert protocol-relative links to HTTPS rather than leaving them ambiguous.
    if url.startswith("//"):
        return f"https:{url}"

    # Preserve explicit HTTP(S) URLs exactly as supplied after whitespace cleanup.
    if url.casefold().startswith(("http://", "https://")):
        return url

    # Database website values without a scheme should default to secure HTTPS.
    return f"https://{url}"


def normalize_page_url(href: object, current_page_url: str) -> str:
    """Convert one raw page link into a normalized absolute HTTP(S) URL.

    Fragments, unsupported protocols, credentials, and trailing non-root slashes
    are removed. Query parameters are retained because they can identify a real
    website page or resource.
    """
    # A link must be a non-empty string before it can be resolved.
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.casefold().startswith(_SKIPPED_LINK_PREFIXES):
        return ""

    # Resolve relative, root-relative, and protocol-relative links consistently.
    full_url = urljoin(current_page_url, href)
    parsed = urlparse(full_url)
    scheme = parsed.scheme.casefold()
    netloc = parsed.netloc.casefold()

    # Only web pages with a valid hostname are candidates for future crawling.
    if scheme not in {"http", "https"} or not netloc:
        return ""

    # Never retain credentials if a malformed page link happened to include them.
    hostname = parsed.hostname
    if not hostname:
        return ""
    host_with_port = hostname.casefold()
    if parsed.port is not None:
        host_with_port = f"{host_with_port}:{parsed.port}"

    # Use a root path when absent and trim cosmetic trailing slashes elsewhere.
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    # Drop params/fragments while retaining query parameters that may be meaningful.
    return urlunparse((scheme, host_with_port, path, "", parsed.query, ""))


def is_same_netloc(base_url: str, page_url: str) -> bool:
    """Return whether two valid HTTP(S) URLs use the same hostname.

    Ports and a leading ``www.`` do not make a website subpage external.
    """
    base_host = (urlparse(base_url).hostname or "").casefold().removeprefix("www.")
    page_host = (urlparse(page_url).hostname or "").casefold().removeprefix("www.")
    return bool(base_host and page_host) and base_host == page_host


def get_url_priority(page_url: str) -> int:
    """Return a crawl priority where lower scores are visited earlier.

    Contact and appointment pages rank first because they are most likely to
    contain direct email addresses; legal and blog pages rank last.
    """
    path = urlparse(page_url).path.casefold().strip("/")
    if not path:
        return 0
    if _path_has_keyword(path, _CONTACT_KEYWORDS):
        return 10
    if _path_has_keyword(path, _ABOUT_KEYWORDS):
        return 20
    if _path_has_keyword(path, _SERVICE_KEYWORDS):
        return 30
    if _path_has_keyword(path, _TEAM_KEYWORDS):
        return 40
    if _path_has_keyword(path, _FAQ_KEYWORDS):
        return 50
    if _path_has_keyword(path, _LOW_VALUE_KEYWORDS):
        return 200
    if _path_has_keyword(path, _CONTENT_KEYWORDS):
        return 80
    return 60


def _path_has_keyword(path: str, keywords: tuple[str, ...]) -> bool:
    """Match keywords against individual URL path segments where possible."""
    segments = tuple(segment for segment in path.split("/") if segment)
    return any(keyword in segment for segment in segments for keyword in keywords)


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
    retained_emails = [candidate for candidate in scored_emails if candidate.score >= 20]
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
        0: 10,
        10: 20,
        20: 16,
        30: 8,
        40: 14,
        50: 5,
        60: 2,
        80: -8,
        200: -20,
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
    website_host = (urlparse(website_url).hostname or "").casefold().removeprefix("www.")
    domain = email_domain.casefold().removeprefix("www.")
    if website_host and (
        domain == website_host
        or domain.endswith(f".{website_host}")
        or website_host.endswith(f".{domain}")
    ):
        return 20
    if domain in _FREE_EMAIL_DOMAINS:
        return 10
    return -12


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
            f"{match.group(1)}@"
            + re.sub(r"\s+dot\s+", ".", match.group(2), flags=re.I)
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
