"""Metro-area assignment from (city, state).

Maps cities to the target metros from PROJECT_GUIDE.md — NYC, SF Bay
Area, LA, Chicago, Boston, Seattle, Austin — plus the DC metro (added:
it's a top-3 US analytics market thanks to federal/contractor demand,
and USAJobs ingestion in a later phase will skew heavily here).

Judgment calls:
- City-list based, not radius based: explicit, auditable, and wrong in
  knowable ways (a missing suburb is a one-line fix).
- None means "not in a tracked metro", not "unknown location".
- "Washington" requires DC state context to avoid Washington-state
  collisions; all other names are unambiguous within this list.
"""

from __future__ import annotations

METRO_CITIES: dict[str, set[str]] = {
    "NYC": {
        "new york",
        "brooklyn",
        "queens",
        "bronx",
        "staten island",
        "jersey city",
        "newark",
        "hoboken",
        "long island city",
        "manhattan",
    },
    "SF Bay Area": {
        "san francisco",
        "oakland",
        "san jose",
        "palo alto",
        "mountain view",
        "sunnyvale",
        "santa clara",
        "menlo park",
        "redwood city",
        "berkeley",
        "fremont",
        "cupertino",
        "south san francisco",
        "foster city",
        "san mateo",
    },
    "LA": {
        "los angeles",
        "santa monica",
        "pasadena",
        "long beach",
        "burbank",
        "glendale",
        "culver city",
        "el segundo",
        "irvine",
        "anaheim",
        "torrance",
    },
    "Chicago": {"chicago", "evanston", "naperville", "schaumburg", "oak brook", "deerfield"},
    "Boston": {"boston", "cambridge", "somerville", "waltham", "quincy", "burlington"},
    "Seattle": {"seattle", "bellevue", "redmond", "kirkland", "tacoma"},
    "Austin": {"austin", "round rock"},
    "DC": {
        "washington",
        "arlington",
        "alexandria",
        "fairfax",
        "reston",
        "mclean",
        "tysons",
        "herndon",
        "falls church",
        "vienna",
        "springfield",
        "bethesda",
        "rockville",
        "silver spring",
        "gaithersburg",
    },
}

_DC_STATES = {"district of columbia", "dc", "washington dc", "washington, d.c."}

_CITY_TO_METRO: dict[str, str] = {
    city: metro for metro, cities in METRO_CITIES.items() for city in cities
}


def assign_metro(city: str | None, state: str | None) -> str | None:
    if not city:
        return None
    key = city.strip().lower()
    if key == "washington":
        # only DC-the-city; Washington-state rows must not land in the DC metro
        return "DC" if (state or "").strip().lower() in _DC_STATES else None
    if key == "springfield":
        # many US Springfields; only claim the Virginia one for DC metro
        return "DC" if (state or "").strip().lower() == "virginia" else None
    return _CITY_TO_METRO.get(key)
