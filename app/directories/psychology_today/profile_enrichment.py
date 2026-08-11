"""HTML extraction rules for individual Psychology Today profiles."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup, Tag

from app.directories.schemas import ProfileEnrichment


_MONEY_PATTERN = re.compile(r"\$\s?[\d,]+(?:\s*(?:-|–|to)\s*\$?\s?[\d,]+)?")
_SELF_PAY_TERMS = (
    "out of network",
    "out-of-network",
    "self pay",
    "self-pay",
    "private pay",
    "cash pay",
    "cash-pay",
    "superbill",
    "out of pocket",
    "out-of-pocket",
)


def enrich_profile(html: str, profile_url: str) -> ProfileEnrichment:
    """Extract the currently supported fields from a Psychology Today profile."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = _text(soup)
    practice_text = _section_text(soup, "My Practice at a Glance")
    finances_text = _section_text(soup, "Finances")
    specialty_items = _unique(
        [
            *_subsection_items(soup, "Specialties and Expertise", "Top Specialties"),
            *_subsection_items(soup, "Specialties and Expertise", "Expertise"),
        ]
    )
    top_specialties = _unique(
        _subsection_items(soup, "Specialties and Expertise", "Top Specialties")
    )
    if not specialty_items:
        specialty_items = _unique(_specialties_from_practice_text(practice_text))

    focus_items = _unique(
        [
            *_split_focus_items(_subsection_items(soup, "Client Focus", "Age")),
            *_split_focus_items(
                _subsection_items(soup, "Client Focus", "Participants")
            ),
            *_split_focus_items(
                _subsection_items(soup, "Client Focus", "Communities")
            ),
            *_split_focus_items(
                _subsection_items(soup, "Client Focus", "Ethnicity")
            ),
        ]
    )
    insurance_items = _unique(_subsection_items(soup, "Finances", "Insurance"))
    fee_items = _unique(_subsection_items(soup, "Finances", "Fees"))
    fee_raw = _join(fee_items)
    fee_source = fee_raw or finances_text or practice_text
    fee_clean = _first_money_value(fee_source)
    profile_name = _profile_name(soup)
    first_name, last_name = _split_name(profile_name)
    client_focus_primary, client_focus_secondary = _rank_client_focus(
        focus_items, _profile_description(soup)
    )

    return ProfileEnrichment(
        first_name=first_name,
        last_name=last_name,
        phone_number=_phone_number(soup, page_text),
        pt_website_redirect=_website_redirect(soup, profile_url),
        all_specialties=_join(specialty_items),
        best_specialty=_best_specialty(
            specialty_items, top_specialties, practice_text, _profile_description(soup)
        ),
        client_focus=_join(focus_items),
        client_focus_primary=client_focus_primary,
        client_focus_secondary=client_focus_secondary,
        insurance_details=_join(insurance_items),
        payment_category=_payment_category(
            insurance_items, f"{finances_text} {practice_text}"
        ),
        fee_raw=fee_raw,
        fee_clean=fee_clean,
        availability_status=_availability_status(practice_text or page_text),
    )


def _find_heading(soup: BeautifulSoup, title: str) -> Tag | None:
    expected = _normalize(title)
    for heading in soup.find_all(("h2", "h3")):
        if _normalize(heading.get_text(" ", strip=True)) == expected:
            return heading
    return None


def _section_elements(heading: Tag) -> Iterable[Tag]:
    """Yield elements after an h2 until the next h2 starts a new section."""
    for element in heading.find_all_next():
        if not isinstance(element, Tag):
            continue
        if element.name == "h2":
            return
        yield element


def _section_text(soup: BeautifulSoup, title: str) -> str:
    heading = _find_heading(soup, title)
    if heading is None:
        return ""

    values: list[str] = []
    for element in _section_elements(heading):
        is_leaf_div = element.name == "div" and not element.find(
            ("div", "h3", "p", "li")
        )
        if element.name in {"h3", "p", "li"} or is_leaf_div:
            value = _text(element)
            if value:
                values.append(value)
    return " ".join(_unique(values))


def _subsection_items(soup: BeautifulSoup, section: str, subsection: str) -> list[str]:
    section_heading = _find_heading(soup, section)
    if section_heading is None:
        return []

    subsection_heading: Tag | None = None
    expected = _normalize(subsection)
    for element in _section_elements(section_heading):
        if element.name == "h3" and _normalize(_text(element)) == expected:
            subsection_heading = element
            break
    if subsection_heading is None:
        return []

    values: list[str] = []
    for element in subsection_heading.find_all_next():
        if not isinstance(element, Tag):
            continue
        if element.name in {"h2", "h3"}:
            break
        is_attribute_span = (
            element.name == "span"
            and str(element.get("data-x", "")).startswith("attribute-")
        )
        if element.name == "li" or is_attribute_span:
            value = _text(element)
            if value:
                values.append(value)
    return _unique(values)


def _profile_name(soup: BeautifulSoup) -> str | None:
    heading = soup.find("h1")
    if heading is not None:
        value = _text(heading)
        if value:
            return value
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta and meta.get("content"):
        return str(meta["content"]).split(",", 1)[0].strip()
    return None


def _split_name(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    parts = name.split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


def _website_redirect(soup: BeautifulSoup, profile_url: str) -> str:
    link = soup.select_one("a[data-x='website-link']")
    href = str(link.get("href", "")).strip() if link else ""
    if not href or href.startswith(("#", "javascript:")):
        return "__unavailable__"
    return urljoin(profile_url, href)


def _phone_number(soup: BeautifulSoup, page_text: str) -> str | None:
    for link in soup.select("a[href^='tel:']"):
        label = _text(link)
        if len(re.sub(r"\D", "", label)) >= 7:
            return label
        href = unquote(str(link.get("href", ""))).removeprefix("tel:")
        if len(re.sub(r"\D", "", href)) >= 7:
            return href

    match = re.search(r"(?:\+1\s*)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", page_text)
    return match.group(0) if match else None


def _specialties_from_practice_text(practice_text: str) -> list[str]:
    match = re.search(
        r"I specialize in\s+(.+?)(?:\.|I accept|I see|$)",
        practice_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    return [
        item.strip() for item in re.split(r",|\band\b", match.group(1)) if item.strip()
    ]


def _best_specialty(
    specialties: list[str],
    top_specialties: list[str],
    practice_text: str,
    description_text: str,
) -> str | None:
    if not specialties:
        return None

    practice = practice_text.casefold()
    description = description_text.casefold()
    top_positions = {
        specialty.casefold(): index for index, specialty in enumerate(top_specialties)
    }
    scores: list[tuple[int, int, str]] = []
    for index, specialty in enumerate(specialties):
        phrase = specialty.casefold()
        score = (practice.count(phrase) * 5) + (description.count(phrase) * 2)
        if phrase in top_positions:
            score += 20 - top_positions[phrase]
        scores.append((score, -index, specialty))
    return max(scores)[2]


def _split_focus_items(items: list[str]) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(part.strip(" ,") for part in item.split(","))
    return [value for value in values if value]


def _rank_client_focus(
    focus_items: list[str], description_text: str
) -> tuple[str | None, str | None]:
    if not focus_items:
        return None, None
    description = description_text.casefold()
    scored = [
        (description.count(item.casefold()), -index, item)
        for index, item in enumerate(focus_items)
    ]
    ranked = [item for _, _, item in sorted(scored, reverse=True)]
    return ranked[0], ranked[1] if len(ranked) > 1 else None


def _payment_category(
    insurance_items: list[str], finance_and_practice_text: str
) -> str | None:
    text = finance_and_practice_text.casefold()
    says_no_insurance = "no insurance" in text or "do not accept insurance" in text
    accepts_insurance = bool(insurance_items) or "accept insurance" in text
    supports_self_pay = any(term in text for term in _SELF_PAY_TERMS)

    if says_no_insurance:
        return "self_pay"
    if accepts_insurance and supports_self_pay:
        return "hybrid"
    if accepts_insurance:
        return "insurance_only"
    return "self_pay" if text else None


def _availability_status(practice_text: str) -> str:
    text = practice_text.casefold()
    if "waitlist" in text or "wait list" in text:
        return "waitlist"
    if any(
        phrase in text
        for phrase in (
            "not accepting new clients",
            "unable to accept new clients",
            "not currently accepting clients",
        )
    ):
        return "not_accepting_new_clients"
    return "accepting_new_clients"


def _profile_description(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    if heading is None:
        return ""
    paragraphs: list[str] = []
    for element in heading.find_all_next():
        if not isinstance(element, Tag):
            continue
        if element.name == "h2":
            break
        if element.name == "p":
            value = _text(element)
            if value:
                paragraphs.append(value)
    return " ".join(_unique(paragraphs))


def _first_money_value(text: str) -> str | None:
    match = _MONEY_PATTERN.search(text)
    return re.sub(r"\s+", "", match.group(0)) if match else None


def _text(element: Tag | BeautifulSoup) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _unique(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip(" ,")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique.append(cleaned)
            seen.add(key)
    return unique


def _join(values: Iterable[str]) -> str | None:
    cleaned = _unique(values)
    return " | ".join(cleaned) if cleaned else None
