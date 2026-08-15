"""URL helpers shared by website crawling and website enrichment."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse


_SKIPPED_LINK_PREFIXES = ("mailto:", "tel:", "sms:", "javascript:", "#")

_CONTACT_KEYWORDS = (
    "contact", "appointment", "schedule", "book", "consult", "intake",
    "get-started", "start-here",
)
_ABOUT_KEYWORDS = ("about", "meet", "bio", "our-story")
_SERVICE_KEYWORDS = (
    "service", "services", "therapy", "therapies", "counseling",
    "counselling", "treatment", "specialties", "specialty", "areas",
)
_TEAM_KEYWORDS = ("team", "staff", "therapists", "clinicians", "providers")
_FAQ_KEYWORDS = ("faq", "faqs", "questions")
_CONTENT_KEYWORDS = ("blog", "article", "articles", "post", "news", "resources")
_LOW_VALUE_KEYWORDS = (
    "privacy", "terms", "cookie", "cookies", "disclaimer", "accessibility", "sitemap",
)


def clean_website_url(raw_url: object) -> str:
    """Return a fetchable HTTP(S) URL from a database website value."""
    if raw_url is None:
        return ""
    url = str(raw_url).strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.casefold().startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def normalize_page_url(href: object, current_page_url: str) -> str:
    """Return a normalized absolute HTTP(S) page URL or an empty string."""
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.casefold().startswith(_SKIPPED_LINK_PREFIXES):
        return ""

    parsed = urlparse(urljoin(current_page_url, href))
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""

    host_with_port = parsed.hostname.casefold()
    if parsed.port is not None:
        host_with_port = f"{host_with_port}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.casefold(), host_with_port, path, "", parsed.query, ""))


def is_same_netloc(base_url: str, page_url: str) -> bool:
    """Return whether URLs use the same hostname, treating ``www`` as cosmetic."""
    base_host = (urlparse(base_url).hostname or "").casefold().removeprefix("www.")
    page_host = (urlparse(page_url).hostname or "").casefold().removeprefix("www.")
    return bool(base_host and page_host) and base_host == page_host


def get_url_priority(page_url: str) -> int:
    """Return crawl priority; lower values are popped first by ``heapq``."""
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
    """Match a hint against URL path segments without inspecting the hostname."""
    segments = tuple(segment for segment in path.split("/") if segment)
    return any(keyword in segment for segment in segments for keyword in keywords)
