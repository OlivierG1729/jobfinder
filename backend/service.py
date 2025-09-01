# backend/service.py
"""Utilities for interacting with the Choisir le Service Public API."""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# Official Choisir le Service Public API
# ---------------------------------------------------------------------------

# Public search endpoint for job offers.  This replaces the previous
# Tabular API based implementation which required a resource identifier (RID).
# The official API exposes a fixed schema so dynamic discovery of columns is no
# longer necessary.

BASE = "https://choisirleservicepublic.gouv.fr/api/offres"

# Some debug endpoints in ``main.py`` expect a ``PROFILE`` constant and a low
# level ``_api_get`` function.  They are kept here for backward compatibility
# but simply point to the same search endpoint.
PROFILE = BASE


def _api_get(params: Dict[str, Any]) -> Dict[str, Any]:
    """Low level helper around ``requests.get``.

    Parameters are forwarded to the Choisir le Service Public API and the JSON
    response is returned.  An exception is raised if the request fails.
    """

    r = requests.get(BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def extract_offer_id(off: Dict[str, Any]) -> Optional[str]:
    """Best effort extraction of an offer identifier."""

    for key in ("id", "_id", "offer_id"):
        if key in off and off[key] is not None:
            return str(off[key])
    return None


def extract_title(off: Dict[str, Any]) -> str:
    """Extracts a human readable title for the offer."""

    for key in ("intitule", "intitulé", "titre", "title"):
        val = off.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Fallback: first non-empty string that does not look like a URL
    for val in off.values():
        if isinstance(val, str) and val.strip() and not val.startswith(("http://", "https://")):
            return val.strip()
    return "Offre"


def extract_date(off: Dict[str, Any]) -> Optional[str]:
    """Returns the publication date as a string if available."""

    for key in ("datePublication", "date_publication", "publication_date", "date"):
        val = off.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def extract_url(off: Dict[str, Any]) -> Optional[str]:
    """Returns a URL pointing to the public offer page."""

    for key in ("url", "lien", "link"):
        val = off.get(key)
        if isinstance(val, str) and val:
            return val

    oid = extract_offer_id(off)
    if oid:
        return f"https://choisirleservicepublic.gouv.fr/offre/{oid}"
    return None


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------

def search_offers(
    query: Optional[str] = None,
    page_size: int = 50,
    page: int = 1,
) -> List[Dict[str, Any]]:
    """Searches job offers through the official API.

    ``query`` is passed via the ``q`` parameter which is what the website uses.
    The response contains a list of offers under the ``results`` key.  The
    offers are sorted by publication date in **reverse chronological order**
    (newest first) before being returned.
    """

    params: Dict[str, Any] = {"limit": page_size, "page": page}
    if query:
        params["q"] = query

    data = _api_get(params)
    offers: List[Dict[str, Any]] = data.get("results") or data.get("data") or []

    def parse_date(off: Dict[str, Any]) -> datetime:
        d = extract_date(off)
        if not d:
            return datetime.min
        try:
            # ``datetime.fromisoformat`` does not accept ``Z`` so we normalise
            # to an explicit UTC offset.
            return datetime.fromisoformat(d.replace("Z", "+00:00"))
        except Exception:
            return datetime.min

    # Newest first
    offers.sort(key=parse_date, reverse=True)
    return offers


def get_detected_columns() -> Dict[str, Any]:
    """Backward compatibility stub used by debug endpoints."""

    return {}

