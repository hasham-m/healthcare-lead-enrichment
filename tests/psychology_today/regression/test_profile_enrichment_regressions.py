"""Regression coverage for Psychology Today profile HTML structures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.directories.psychology_today.profile_enrichment import enrich_profile


FIXTURES_DIR = ROOT_DIR / "tests" / "psychology_today" / "fixtures"
PROFILE_URL = "https://www.psychologytoday.com/us/therapists/example/1"


class ProfileEnrichmentRegressionTests(unittest.TestCase):
    """Protect the two HTML structures that previously caused parser failures."""

    def test_not_accepting_new_clients_in_nested_div_is_detected(self) -> None:
        html = (
            FIXTURES_DIR / "availability_not_accepting_new_clients_nested_div.html"
        ).read_text(encoding="utf-8")
        enrichment = enrich_profile(html, PROFILE_URL)
        self.assertEqual(enrichment.availability_status, "not_accepting_new_clients")

    def test_client_focus_attribute_spans_are_collected(self) -> None:
        html = (FIXTURES_DIR / "client_focus_attribute_spans.html").read_text(
            encoding="utf-8"
        )
        enrichment = enrich_profile(html, PROFILE_URL)
        self.assertEqual(
            enrichment.client_focus,
            "Adults | Elders (65+) | Individuals | Aviation Professionals | Asian",
        )


if __name__ == "__main__":
    unittest.main()
