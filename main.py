from __future__ import annotations

import json
from app.directories.psychology_today import scrape_profile_urls


def main() -> None:
    start_url = input("Psychology Today directory URL: ").strip()
    max_profiles = int(input("Maximum number of profiles: "))
    max_pages = int(input("Maximum number of pages: "))
    result = scrape_profile_urls(start_url, max_profiles, max_pages)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
