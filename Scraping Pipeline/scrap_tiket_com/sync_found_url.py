"""
Sync missing properties from property_with_competitor.json into found_url.json.

For every property in property_with_competitor.json, check whether a matching
"properties_name" already exists in found_url.json. If not, append a placeholder
dictionary carrying the property name and its competitor_id.
"""

import json
import os
import sys

PROPERTY_FILE = "property_with_competitor.json"
FOUND_URL_FILE = "found_url.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def main():
    # Optional base directory; defaults to the current working directory.
    base_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    property_path = os.path.join(base_dir, PROPERTY_FILE)
    found_url_path = os.path.join(base_dir, FOUND_URL_FILE)

    properties = load_json(property_path)
    found_url = load_json(found_url_path)

    # Set of names already present in found_url.json (case-insensitive, trimmed).
    existing_names = {
        entry.get("properties_name", "").strip().lower()
        for entry in found_url
    }

    added = 0
    for prop in properties:
        name = prop.get("properties_name", "").strip()
        if not name:
            continue

        if name.lower() in existing_names:
            continue

        new_entry = {
            "properties_name": name,
            "competitor_id": prop.get("competitor_id"),
            "slug": "",
            "match": "",
            "score": 1.0,
            "url": "",
        }
        found_url.append(new_entry)
        existing_names.add(name.lower())
        added += 1
        print(f"Added: {name} (competitor_id={prop.get('competitor_id')})")

    # Sort the whole list by competitor_id (entries without an id go last).
    found_url.sort(
        key=lambda e: (e.get("competitor_id") is None, e.get("competitor_id") or 0)
    )

    save_json(found_url_path, found_url)
    print(f"\nDone. {added} new propert{'y' if added == 1 else 'ies'} appended to {found_url_path}.")
    print(f"{found_url_path} sorted by competitor_id.")


if __name__ == "__main__":
    main()
