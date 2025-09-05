# backend/service.py
"""
Recherche d'offres CSP via l'API publique.
Objectifs :
 - Toujours trier par date décroissante (plus récent -> plus ancien).
 - Limiter le nombre de résultats via un paramètre ``limit``.
 - Dédoublonnage (au cas où une offre apparaisse sur plusieurs pages côté site).
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://choisirleservicepublic.gouv.fr/api/offres"

# Cache des résultats : clé query -> (résultats cumulés, dernière page récupérée, timestamp)
_CACHE_TTL_SECONDS = 3600  # 1h par défaut
_SEARCH_CACHE: Dict[str, tuple[List[Dict[str, Any]], int, float]] = {}


# --------- Helpers d'extraction (API interne du backend) ---------


def extract_offer_id(off: Dict[str, Any]) -> Optional[str]:
    """Essaye d'extraire un identifiant stable ; sinon None."""
    oid = off.get("id")
    if oid:
        return str(oid)
    url = off.get("url")
    if isinstance(url, str) and url:
        # Dernier segment de l'URL comme identifiant minimal
        slug = url.rstrip("/").split("/")[-1]
        if slug:
            return slug
    return None


def extract_title(off: Dict[str, Any]) -> str:
    title = off.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    # fallback sur d'autres clés courantes
    for k in ("intitule", "intitulé", "titre"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "Offre"


def extract_date(off: Dict[str, Any]) -> Optional[str]:
    d = off.get("date")
    if isinstance(d, str) and d.strip():
        return d.strip()
    # fallback éventuel
    for k in ("datePublication", "date_publication", "publication_date"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def extract_url(off: Dict[str, Any]) -> Optional[str]:
    u = off.get("url")
    if isinstance(u, str) and u.strip():
        return u.strip()
    for k in ("lien", "link"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# --------- Appel de l'API publique ---------


def _fetch_api_page(query: str, page: int, per_page: int) -> List[Dict[str, Any]]:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
    )
    params = {"q": query, "page": page, "limit": per_page}
    try:
        resp = session.get(API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Page API {page} inaccessible") from exc
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Réponse non‑JSON reçue : {resp.text[:200]!r}") from exc
    items = data.get("items") or data.get("results") or []
    if not isinstance(items, list):
        return []
    return items


# --------- Tri/pagination stables ---------


def _parse_date_safe(s: Optional[str]) -> datetime:
    """Robuste : ISO 'YYYY-MM-DD' -> datetime ; sinon datetime.min."""
    if not s:
        return datetime.min
    try:
        # accepte aussi YYYY-MM-DDTHH:MM:SS[Z]
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        # si seulement 'YYYY-MM-DD'
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return datetime.min


def _stable_id(off: Dict[str, Any]) -> str:
    """Identifiant déterministe pour tie-break + dédoublonnage."""
    return (
        (off.get("id") and str(off["id"]))
        or (off.get("_id") and str(off["_id"]))
        or (off.get("offer_id") and str(off["offer_id"]))
        or (off.get("url") or "")
        or (off.get("title") or off.get("intitule") or "")
    )


def _get_cached_results(
    query: str,
    limit: int,
    refresh_cache: bool = False,
) -> List[Dict[str, Any]]:
    """Retourne la liste complète des résultats pour une requête donnée.

    On cumule les pages du site jusqu'à atteindre ``limit`` offres. Les
    résultats sont mis en cache pour éviter de repartir de la page 1 lors des
    appels suivants.
    """

    from concurrent.futures import ThreadPoolExecutor

    key = query
    now = time.time()

    acc: List[Dict[str, Any]]
    last_site_page: int

    if not refresh_cache:
        cached = _SEARCH_CACHE.get(key)
        if cached and now - cached[2] < _CACHE_TTL_SECONDS:
            acc = list(cached[0])
            last_site_page = cached[1]
        else:
            acc = []
            last_site_page = 0
    else:
        acc = []
        last_site_page = 0

    needed_items = limit

    while len(acc) < needed_items:
        missing = needed_items - len(acc)
        # Nombre de pages du site à récupérer (20 offres / page) + marge
        to_fetch = ((missing + 19) // 20) + 1
        pages = list(range(last_site_page + 1, last_site_page + to_fetch + 1))
        if not pages:
            break

        stop = False
        per_page = 20
        for i in range(0, len(pages), 5):
            chunk = pages[i : i + 5]
            fetched = []
            with ThreadPoolExecutor(max_workers=5) as pool:
                # map conserve l'ordre des pages demandées
                fetched = list(
                    pool.map(lambda p: (p, _fetch_api_page(query, p, per_page)), chunk)
                )

            for p, items in fetched:
                last_site_page = max(last_site_page, p)
                acc.extend(items)
                if len(items) < per_page:
                    stop = True
                    break
            if stop:
                break
        if stop or last_site_page >= 500:
            break

    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for o in acc:
        k = _stable_id(o)
        if not k:
            title = extract_title(o)
            date = extract_date(o) or ""
            if title or date:
                k = hashlib.sha1(f"{title}|{date}".encode("utf-8")).hexdigest()
            else:
                k = f"idx-{len(unique)}"
        if k not in seen:
            unique.append(o)
            seen.add(k)

    unique.sort(key=_stable_id)
    unique.sort(key=lambda o: _parse_date_safe(o.get("date")), reverse=True)

    _SEARCH_CACHE[key] = (unique, last_site_page, now)
    return unique


def search_offers(
    query: Optional[str] = None,
    limit: int = 50,
    fast_mode: bool = False,
    refresh_cache: bool = False,
) -> List[Dict[str, Any]]:
    """Recherche simple avec limite sur le nombre d'offres retournées."""
    if not query or not query.strip():
        return []

    query = query.strip()
    if fast_mode:
        return _fetch_api_page(query, 1, limit)

    acc = _get_cached_results(query, limit, refresh_cache=refresh_cache)

    return acc[:limit]


def get_detected_columns() -> Dict[str, Any]:
    """Compat rétro : pas de schéma dynamique ici."""
    return {}
