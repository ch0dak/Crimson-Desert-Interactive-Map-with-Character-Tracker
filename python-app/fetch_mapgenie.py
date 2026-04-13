"""
Fetch and cache MapGenie location data for Crimson Desert.
Run this once to download the data, then the tracker serves it locally.
"""

import json
import os
import re
import sys
import urllib.request

MAPS = {
    "pywel": 887,
}

CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(CACHE_DIR, "mapgenie_data.json")

PAGE_URL = "https://mapgenie.io/crimson-desert/maps/pywel"


def fetch_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_mapdata(html):
    """Extract the mapData object from MapGenie's page HTML."""
    # MapGenie embeds mapData as a JS object in a script tag.
    # Look for patterns like:  mapData = {...}  or  window.mapData = {...}
    # The data is typically in a script that assigns to mapData or is in JSON form.

    # Strategy 1: Look for JSON-LD or inline JSON with locations
    # Strategy 2: Look for the mapData assignment in scripts

    # Find script tags content
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)

    for script in scripts:
        # Look for mapData assignment
        match = re.search(r'(?:window\.)?mapData\s*=\s*(\{.*?\})\s*;?\s*(?:window\.|var |let |const |$)', script, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if "locations" in data:
                    return data
            except json.JSONDecodeError:
                continue

        # Look for JSON.parse with mapData
        match = re.search(r'JSON\.parse\([\'"](.+?)[\'"]\)', script)
        if match:
            try:
                data = json.loads(match.group(1).replace('\\"', '"').replace("\\'", "'"))
                if "locations" in data:
                    return data
            except (json.JSONDecodeError, ValueError):
                continue

    return None


def build_cache(map_data):
    """Build a slim cache with just the data we need."""
    groups = []
    for g in map_data.get("groups", []):
        cats = []
        for c in g.get("categories", []):
            cats.append({
                "id": c["id"],
                "title": c["title"],
                "icon": c.get("icon", ""),
                "premium": c.get("premium", False),
            })
        groups.append({
            "title": g["title"],
            "color": g.get("color", "888888"),
            "categories": cats,
        })

    # Build category lookup for quick icon/color mapping
    cat_to_group_color = {}
    for g in groups:
        for c in g["categories"]:
            cat_to_group_color[c["id"]] = g["color"]

    locations = []
    for loc in map_data.get("locations", []):
        locations.append({
            "id": loc["id"],
            "c": loc["category_id"],
            "t": loc["title"],
            "la": loc["latitude"],
            "lo": loc["longitude"],
            "d": loc.get("description") or "",
        })

    return {
        "groups": groups,
        "locations": locations,
        "sprite": "https://cdn.mapgenie.io/images/games/crimson-desert/markers",
    }


def main():
    if os.path.exists(CACHE_FILE):
        size_kb = os.path.getsize(CACHE_FILE) // 1024
        print(f"Cache already exists ({size_kb} KB): {CACHE_FILE}")
        if "--force" not in sys.argv:
            print("Use --force to re-download.")
            return

    print(f"Fetching {PAGE_URL} ...")
    html = fetch_page(PAGE_URL)
    print(f"Page fetched ({len(html)} bytes), extracting mapData...")

    map_data = extract_mapdata(html)
    if not map_data:
        print("ERROR: Could not extract mapData from page.")
        print("MapGenie may have changed their page structure.")
        print("You can manually export mapData from browser console:")
        print('  copy(JSON.stringify(window.mapData))')
        print(f"  Save to: {CACHE_FILE}")
        sys.exit(1)

    cache = build_cache(map_data)
    print(f"Found {len(cache['locations'])} locations in {len(cache['groups'])} groups")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))

    size_kb = os.path.getsize(CACHE_FILE) // 1024
    print(f"Saved to {CACHE_FILE} ({size_kb} KB)")


if __name__ == "__main__":
    main()
