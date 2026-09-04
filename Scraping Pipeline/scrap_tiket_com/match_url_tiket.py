"""
Match property names against a list of URLs (hybrid matcher).

For every property in `property_with_competitor.json`, the name is normalised
into a booking.com style slug (same rule as the last cell of scrapping_2.ipynb:
lowercase, spaces -> "-", "&" -> "amp") and then looked up inside
`URL_text_list.txt` in two stages:

  1. SUBSTRING (fast, like CTRL+F): first URL whose slug *contains* the
     property slug wins.
  2. FUZZY fallback: for properties with no substring hit, score the slug
     against candidate URL slugs (those sharing a distinctive token) with
     difflib.SequenceMatcher; accept the best only if it scores >= SCORE_THRESHOLD.

Results are split into:
    found_url      -> list of property dicts + {"slug", "url", "match", "score"}
    manual_search  -> list of property dicts with no acceptable match
"""

import json, time, requests
import re
from difflib import SequenceMatcher
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

URL_FILE = "URL_pool_list.txt"
PROP_FILE = "property_with_competitor.json"
FOUND_URL_FILE = "found_url.json"
MANUAL_SEARCH_FILE = "manual_search.json"
SCORE_THRESHOLD = 0.80
API_KEY = "tp-link8855"
WEBHOOK_URL = " https://searches-kde-asking-wednesday.trycloudflare.com/api/scraped-properties/compinfo"

# Generic words that carry little identifying signal for a property; used only
# to pick which URLs are worth fuzzy-scoring, never to alter the slug itself.
STOPWORDS = {
    "hotel", "hotels", "the", "a", "an", "guesthouse", "guest", "house",
    "homestay", "home", "stay", "villa", "villas", "resort", "resorts",
    "cottage", "cottages", "inn", "residence", "syariah", "bali", "by",
    "oyo", "reddoorz", "flagship", "and", "at", "amp",
    "bungalow", "lodge", "hostel", "suite", "suites", "of", "spa",
}

URL_SLUG_RE = re.compile(r"/hotel/[a-z]{2}/([^.?/]+)")

def get_list_from_api():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    try:
        response = requests.get(WEBHOOK_URL, headers=headers)
        response.raise_for_status()  # Raises HTTPError for bad status codes   
        list_data = (response.json())["data"]
        with open("property_with_competitor.json", "w") as f:
            json.dump(list_data, f, indent=4)

    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")

def get_lists_from_json() -> tuple[list[str], list[str]]:
    """Build the result arrays from previously-saved JSON instead of the API.

    final_found_url     <- the "url" of every entry in found_url.json
    final_manual_search <- the "properties_name" of every entry in manual_search.json

    Missing or malformed files degrade to empty lists rather than crashing.
    """
    try:
        with open(FOUND_URL_FILE, encoding="utf-8") as f:
            found_url = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[warn] could not read {FOUND_URL_FILE}: {e}")
        found_url = []

    try:
        with open(MANUAL_SEARCH_FILE, encoding="utf-8") as f:
            manual_search = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[warn] could not read {MANUAL_SEARCH_FILE}: {e}")
        manual_search = []

    final_found_url = [e["url"] for e in found_url if "url" in e]
    final_manual_search = [e["properties_name"] for e in manual_search if "properties_name" in e]

    print(f"Loaded from JSON   : {len(final_found_url)} found URL(s), "
          f"{len(final_manual_search)} manual-search name(s)")
    return final_found_url, final_manual_search


def make_slug(name: str) -> str:
    """Same rule as scrapping_2.ipynb."""
    slug = name.lower().replace(" ", "-")
    if "&" in slug:
        slug = slug.replace("&", "amp")
    return slug


def tokenize(slug: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", slug) if t]


def main_processing(source: str = "api") -> tuple[list[str], list[str]]:
    """Return (final_found_url, final_manual_search) in that order.

    source="api"  -> pull the competitor mapping from the API and run the
                     name->URL matcher (default, original behaviour).
    source="json" -> skip the API/matcher and read the previously-saved
                     found_url.json / manual_search.json instead.
    """
    source = source.lower()
    if source == "json":
        return get_lists_from_json()
    if source != "api":
        raise ValueError(f"source must be 'api' or 'json', got {source!r}")

    print("Checking server for any API update on competitor mapping.")
    get_list_from_api()
    print("JSON file for customer mapping done updating.")

    with open(PROP_FILE, encoding="utf-8") as f:
        properties = json.load(f)
    with open(URL_FILE, encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    urls_lower = [u.lower() for u in urls]

    # Pre-extract a clean slug per URL and index URLs by token (for fuzzy stage).
    url_slugs: list[str] = []
    token_index: dict[str, list[int]] = {}
    for idx, u in enumerate(urls):
        m = URL_SLUG_RE.search(u)
        slug = m.group(1).lower() if m else urls_lower[idx]
        url_slugs.append(slug)
        for tok in set(tokenize(slug)):
            token_index.setdefault(tok, []).append(idx)

    found_url: list[dict] = []
    manual_search: list[dict] = []

    for prop in properties:
        pslug = make_slug(prop["properties_name"])

        # --- stage 1: substring (CTRL+F style) ---
        match_url = None
        for original, lowered in zip(urls, urls_lower):
            if pslug in lowered:
                match_url = original
                break

        if match_url is not None:
            found_url.append({**prop, "slug": pslug,
                              "match": "substring", "score": 1.0,
                              "url": match_url})
            continue

        # --- stage 2: fuzzy fallback (>= SCORE_THRESHOLD) ---
        ptokens = tokenize(pslug)
        distinctive = [t for t in ptokens if t not in STOPWORDS] or ptokens
        candidates = set()
        for tok in distinctive:
            candidates.update(token_index.get(tok, ()))

        best_score, best_url = 0.0, None
        for c in candidates:
            score = SequenceMatcher(None, pslug, url_slugs[c]).ratio()
            if score > best_score:
                best_score, best_url = score, urls[c]

        if best_score >= SCORE_THRESHOLD:
            found_url.append({**prop, "slug": pslug,
                              "match": "fuzzy", "score": round(best_score, 3),
                              "url": best_url})
        else:
            manual_search.append(prop)

    n_sub = sum(1 for r in found_url if r["match"] == "substring")
    n_fuzzy = sum(1 for r in found_url if r["match"] == "fuzzy")
    print(f"Properties checked : {len(properties)}")
    print(f"Found URLs         : {len(found_url)}  "
          f"(substring={n_sub}, fuzzy={n_fuzzy})")
    print(f"Needs manual search: {len(manual_search)}")

    with open("found_url.json", "w", encoding="utf-8") as f:
        json.dump(found_url, f, indent=4, ensure_ascii=False)
    with open("manual_search.json", "w", encoding="utf-8") as f:
        json.dump(manual_search, f, indent=4, ensure_ascii=False)

    final_manual_search = []
    final_found_url = []
    if manual_search:
        print("\nNo URL found for:")
        for prop in manual_search:
            print(f"  - {prop['properties_name']}")
        final_manual_search = [p['properties_name'] for p in manual_search]

    if found_url:
        # for content in found_url:
        #     print(f"property name is: {content["properties_name"]}")
        #     print(f"URL name is : {content["url"]}")
        final_found_url = [q['url'] for q in found_url]

    return final_found_url, final_manual_search

if __name__ == "__main__":
    main_processing()
