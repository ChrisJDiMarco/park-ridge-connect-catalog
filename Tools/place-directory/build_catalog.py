#!/usr/bin/env python3
"""
Build a hosted place catalog for Park Ridge Connect from OpenStreetMap.

This is intentionally not a Google Maps scraper. Google place data should only
come from approved Google APIs under their terms. This script uses OSM/Overpass
as a free, attributed source and emits JSON that the app can fetch through the
TOWN_PLACE_CATALOG_URL Info.plist key.

Usage:
    python3 Tools/place-directory/build_catalog.py --output /tmp/places.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_ENDPOINTS = [
    DEFAULT_ENDPOINT,
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
DEFAULT_MINIMUM_PLACES = 8
DEFAULT_QUERY_TIMEOUT_SECONDS = 12
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
SOURCE = {
    "id": "openstreetmap",
    "title": "OpenStreetMap",
    "url": COPYRIGHT_URL,
    "summary": "Community-maintained place data licensed under the Open Database License.",
}

BBOX = {
    "south": 41.020405,
    "west": -74.069675,
    "north": 41.049278,
    "east": -74.018721,
}

NEIGHBOR_NAME_TERMS = {
    "emerson",
    "hillsdale",
    "montvale",
    "township of washington",
    "washington township",
    "westwood",
    "woodcliff",
}

FRAGMENT_FALLBACK_CATEGORIES = {
    "food-and-nightlife": {"Adults", "Food"},
    "shops-and-services": {"Food", "Services"},
    "schools-and-library": {"Library", "Schools"},
    "parks-and-recreation": {"Kids", "Recreation"},
    "tourism": {"Adults", "Recreation"},
}
NAME_DEDUPE_STOPWORDS = {"and", "bar", "kitchen", "public", "restaurant"}


class CatalogBuildError(RuntimeError):
    pass


def overpass_queries() -> list[tuple[str, str]]:
    bbox = "{south},{west},{north},{east}".format(**BBOX)
    timeout = DEFAULT_QUERY_TIMEOUT_SECONDS
    return [
        (
            "food-and-nightlife",
            f"""
            [out:json][timeout:{timeout}];
            (
              node["name"]["amenity"~"restaurant|cafe|bar|pub|fast_food|ice_cream|biergarten"]({bbox});
              way["name"]["amenity"~"restaurant|cafe|bar|pub|fast_food|ice_cream|biergarten"]({bbox});
            );
            out tags center 80;
            """,
        ),
        (
            "shops-and-services",
            f"""
            [out:json][timeout:{timeout}];
            (
              node["name"]["shop"]({bbox});
              way["name"]["shop"]({bbox});
            );
            out tags center 80;
            """,
        ),
        (
            "schools-and-library",
            f"""
            [out:json][timeout:{timeout}];
            (
              node["name"]["amenity"~"library|school"]({bbox});
              way["name"]["amenity"~"library|school"]({bbox});
            );
            out tags center 80;
            """,
        ),
        (
            "parks-and-recreation",
            f"""
            [out:json][timeout:{timeout}];
            (
              node["name"]["leisure"~"park|playground|sports_centre|swimming_pool|fitness_centre"]({bbox});
              way["name"]["leisure"~"park|playground|sports_centre|swimming_pool|fitness_centre"]({bbox});
            );
            out tags center 80;
            """,
        ),
        (
            "tourism",
            f"""
            [out:json][timeout:{timeout}];
            (
              node["name"]["tourism"~"museum|attraction|hotel"]({bbox});
              way["name"]["tourism"~"museum|attraction|hotel"]({bbox});
            );
            out tags center 80;
            """,
        ),
    ]


def fetch_json(endpoint: str, query: str) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "ParkRidgeConnect-CatalogBuilder/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def category(tags: dict[str, str]) -> str | None:
    amenity = tags.get("amenity")
    if amenity in {"restaurant", "cafe", "fast_food", "ice_cream"}:
        return "Food"
    if amenity in {"bar", "pub", "biergarten"}:
        return "Adults"
    if amenity == "library":
        return "Library"
    if amenity == "school":
        return "Schools"

    leisure = tags.get("leisure")
    if leisure == "playground":
        return "Kids"
    if leisure in {"park", "sports_centre", "swimming_pool", "fitness_centre"}:
        return "Recreation"

    shop = tags.get("shop")
    if shop:
        return "Food" if shop in {"bakery", "deli", "convenience", "supermarket", "coffee", "beverages"} else "Services"

    tourism = tags.get("tourism")
    if tourism:
        return "Adults" if tourism == "hotel" else "Recreation"

    return None


def readable(value: str) -> str:
    return value.replace("_", " ").split(";")[0].title()


def primary_tag(tags: dict[str, str], fallback: str) -> str:
    return (
        tags.get("cuisine")
        or tags.get("amenity")
        or tags.get("shop")
        or tags.get("leisure")
        or tags.get("tourism")
        or fallback
    )


def website(tags: dict[str, str]) -> str | None:
    value = (tags.get("website") or tags.get("contact:website") or tags.get("url") or "").strip()
    if not value:
        return None
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def address(tags: dict[str, str]) -> str | None:
    parts: list[str] = []
    number = tags.get("addr:housenumber")
    street = tags.get("addr:street")
    if number and street:
        parts.append(f"{number} {street}")
    elif street:
        parts.append(street)

    parts.append(tags.get("addr:city") or "Park Ridge")
    parts.append(tags.get("addr:state") or "NJ")
    if tags.get("addr:postcode"):
        parts.append(tags["addr:postcode"])

    return ", ".join(parts) if parts else None


def normalized_name(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


def is_park_ridge_record(tags: dict[str, str], name: str) -> bool:
    city = tags.get("addr:city")
    if city and normalized_name(city) != "parkridge":
        return False

    haystack = " ".join(
        value.lower()
        for value in [
            name,
            tags.get("operator") or "",
            tags.get("description") or "",
        ]
        if value
    )
    return not any(term in haystack for term in NEIGHBOR_NAME_TERMS)


def tags_list(tags: dict[str, str], cat: str) -> list[str]:
    raw = [
        cat.lower(),
        tags.get("amenity"),
        tags.get("shop"),
        tags.get("leisure"),
        tags.get("tourism"),
        tags.get("cuisine"),
        tags.get("addr:street"),
    ]
    values: list[str] = []
    for item in raw:
        if not item:
            continue
        values.extend(token for token in re.split(r"[^a-zA-Z0-9]+", item.lower()) if len(token) > 2)
    return sorted(set(values))


def place_from_element(element: dict) -> dict | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    cat = category(tags)
    if not name or not cat:
        return None
    if not is_park_ridge_record(tags, name):
        return None

    subcategory = readable(primary_tag(tags, cat))
    addr = address(tags)
    site = website(tags)
    highlights = [subcategory, "OpenStreetMap listing"]
    if addr:
        highlights.append("Address available")
    if site:
        highlights.append("Website listed")

    return {
        "id": f"osm-{element.get('type', 'element')}-{element['id']}",
        "name": name,
        "category": cat,
        "subcategory": subcategory,
        "summary": f"{subcategory} listing from the community-maintained OpenStreetMap directory. Confirm current hours and details with the place before going.",
        "address": addr,
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": site,
        "imageURL": None,
        "highlights": highlights,
        "tags": tags_list(tags, cat),
        "source": SOURCE,
    }


def catalog_from_elements(elements: list[dict], retrieved_from: list[str], warnings: list[str]) -> dict:
    places: list[dict] = []
    seen: set[str] = set()

    for element in elements:
        place = place_from_element(element)
        if not place:
            continue
        key = normalized_name(place["name"])
        if key in seen:
            continue
        seen.add(key)
        places.append(place)

    places.sort(key=lambda item: (item["category"], item["name"].lower()))
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "retrievedFrom": sorted(set(retrieved_from)),
        "warnings": warnings,
        "places": places,
    }


def place_name_key(place: dict) -> str:
    tokens = re.findall(r"[a-z0-9]+", place.get("name", "").lower())
    return "".join(token for token in tokens if token not in NAME_DEDUPE_STOPWORDS)


def unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def merge_place(existing: dict, supplemental: dict) -> dict:
    merged = dict(existing)
    for key in [
        "id",
        "name",
        "category",
        "subcategory",
        "summary",
        "address",
        "phone",
        "website",
        "imageURL",
        "source",
    ]:
        if supplemental.get(key) is not None:
            merged[key] = supplemental[key]

    merged["highlights"] = unique_values(supplemental.get("highlights", []) + existing.get("highlights", []))
    merged["tags"] = unique_values(supplemental.get("tags", []) + existing.get("tags", []))
    return merged


def merge_supplemental_places(catalog: dict, supplemental_places: list[dict]) -> dict:
    if not supplemental_places:
        return catalog

    existing_ids = {place.get("id") for place in catalog.get("places", [])}
    existing_names = {place_name_key(place): index for index, place in enumerate(catalog.get("places", []))}
    added = []
    updated = 0

    for place in supplemental_places:
        name_key = place_name_key(place)
        if not name_key:
            continue
        if name_key in existing_names:
            index = existing_names[name_key]
            catalog["places"][index] = merge_place(catalog["places"][index], place)
            existing_ids.add(place.get("id"))
            updated += 1
            continue
        if place.get("id") in existing_ids:
            continue
        added.append(place)
        existing_ids.add(place.get("id"))
        existing_names[name_key] = len(catalog["places"]) + len(added) - 1

    if not added and updated == 0:
        return catalog

    catalog["places"].extend(added)
    catalog["places"].sort(key=lambda item: (item["category"], item["name"].lower()))
    catalog["supplementalPlaces"] = {
        "addedPlaceCount": len(added),
        "source": "curated Park Ridge seed catalog",
        "updatedPlaceCount": updated,
    }
    return catalog


def failed_fragment_names(warnings: list[str]) -> set[str]:
    return {warning.split(":", 1)[0] for warning in warnings if ":" in warning}


def merge_fallback_places_for_failed_fragments(catalog: dict, fallback_catalog: dict | None) -> dict:
    if not fallback_catalog:
        return catalog

    failed_fragments = failed_fragment_names(catalog.get("warnings", []))
    fallback_categories = set().union(
        *(FRAGMENT_FALLBACK_CATEGORIES.get(fragment, set()) for fragment in failed_fragments)
    )
    if not fallback_categories:
        return catalog

    existing_ids = {place.get("id") for place in catalog.get("places", [])}
    existing_names = {place_name_key(place) for place in catalog.get("places", [])}
    preserved = []

    for place in fallback_catalog.get("places", []):
        if place.get("id") in existing_ids:
            continue
        if place_name_key(place) in existing_names:
            continue
        if place.get("category") not in fallback_categories:
            continue
        preserved.append(place)
        existing_ids.add(place.get("id"))
        existing_names.add(place_name_key(place))

    if not preserved:
        return catalog

    catalog["places"].extend(preserved)
    catalog["places"].sort(key=lambda item: (item["category"], item["name"].lower()))
    catalog["preservedFromFallback"] = {
        "failedFragments": sorted(failed_fragments),
        "placeCount": len(preserved),
    }
    catalog["warnings"].append(
        "Preserved "
        f"{len(preserved)} last-good places for failed fragments: "
        + ", ".join(sorted(failed_fragments))
    )
    return catalog


def validate_catalog(catalog: dict, minimum_places: int) -> None:
    place_count = len(catalog.get("places", []))
    if place_count < minimum_places:
        raise CatalogBuildError(
            f"Catalog contains {place_count} places; expected at least {minimum_places}.\n"
            + "\n".join(catalog.get("warnings", []))
        )


def build_catalog(endpoints: list[str], fallback_catalog: dict | None = None) -> dict:
    elements: list[dict] = []
    retrieved_from: list[str] = []
    errors: list[str] = []

    for fragment_name, query in overpass_queries():
        fragment_errors: list[str] = []
        for endpoint in endpoints:
            try:
                payload = fetch_json(endpoint, query)
                elements.extend(payload.get("elements", []))
                retrieved_from.append(f"{fragment_name}: {endpoint}")
                break
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                fragment_errors.append(f"{endpoint}: {error}")
        else:
            errors.append(f"{fragment_name}: " + " | ".join(fragment_errors))

    catalog = catalog_from_elements(elements, retrieved_from, errors)
    catalog = merge_fallback_places_for_failed_fragments(catalog, fallback_catalog)
    return catalog


def load_fallback_catalog(path: Path, minimum_places: int) -> dict:
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)

    validate_catalog(catalog, minimum_places)
    return catalog


def load_place_list(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("places"), list):
        return payload["places"]
    raise CatalogBuildError(f"{path} must contain a JSON array or an object with a places array")


def write_catalog(catalog: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="Overpass endpoint to try. Can be passed more than once.",
    )
    parser.add_argument(
        "--fallback-input",
        help="Existing catalog to keep when every live endpoint fails.",
    )
    parser.add_argument(
        "--supplemental-input",
        help="Curated LocalPlace JSON records to merge when OSM lacks a known Park Ridge place.",
    )
    parser.add_argument("--minimum-places", type=int, default=DEFAULT_MINIMUM_PLACES)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_path = Path(args.output)
    endpoints = args.endpoints or DEFAULT_ENDPOINTS
    fallback_path = Path(args.fallback_input) if args.fallback_input else None
    fallback_catalog = None
    fallback_load_error = None
    supplemental_places: list[dict] = []

    if fallback_path:
        try:
            fallback_catalog = load_fallback_catalog(fallback_path, args.minimum_places)
        except (CatalogBuildError, OSError, json.JSONDecodeError) as error:
            fallback_load_error = error
    if args.supplemental_input:
        supplemental_places = load_place_list(Path(args.supplemental_input))

    try:
        catalog = build_catalog(endpoints, fallback_catalog)
        catalog = merge_supplemental_places(catalog, supplemental_places)
        validate_catalog(catalog, args.minimum_places)
    except CatalogBuildError as error:
        if not fallback_catalog:
            print(str(error), file=sys.stderr)
            if fallback_load_error:
                print(f"Fallback unavailable: {fallback_load_error}", file=sys.stderr)
            return 1
        catalog = merge_supplemental_places(fallback_catalog, supplemental_places)
        validate_catalog(catalog, args.minimum_places)
        print(f"Live refresh failed; keeping fallback catalog from {args.fallback_input}", file=sys.stderr)

    write_catalog(catalog, output_path)
    print(f"Wrote {len(catalog['places'])} places to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
