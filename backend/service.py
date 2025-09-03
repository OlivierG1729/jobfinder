# backend/service.py
"""
Recherche CSP en parsant les pages publiques (fiable et sans nonce).
Objectifs :
- Toujours trier par date décroissante (plus récent -> plus ancien).
- Limiter le nombre de résultats via un paramètre ``limit``.
- Dédoublonnage (au cas où une offre apparaisse sur plusieurs pages côté site).
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import html as _html
import re
import hashlib
import time

import requests
from bs4 import BeautifulSoup

SITE = "https://choisirleservicepublic.gouv.fr"
BASE_LIST = f"{SITE}/nos-offres/filtres/mot-cles/{{q}}/"
PAGE_URL = f"{SITE}/nos-offres/filtres/mot-cles/{{q}}/page/{{page}}/"

# Mois français -> numéro
FR_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "JobFinder/1.0 (+https://github.com/OlivierG1729/jobfinder)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{SITE}/nos-offres/",
    }
)

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


# --------- Parsing des pages publiques ---------

def _to_absolute(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return SITE + url
    return f"{SITE}/{url.lstrip('/')}"


def _parse_date_fr(text: str) -> Optional[str]:
    """
    Exemple de texte : 'En ligne depuis le 06 août 2025'
    Retourne ISO '2025-08-06' si possible.
    """
    if not text:
        return None
    t = text.strip().lower()
    # tolérer accents/variantes
    t = (
        t.replace("é", "e").replace("è", "e").replace("ê", "e")
         .replace("à", "a").replace("â", "a").replace("ô", "o")
         .replace("û", "u").replace("ï", "i").replace("î", "i")
         .replace("ç", "c").replace("œ", "oe")
    )
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", t)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2)
    year = int(m.group(3))
    month = FR_MONTHS.get(month_name)
    if not month:
        return None
    try:
        return datetime(year, month, day).date().isoformat()
    except Exception:
        return None


def _fetch_list_page(query: str, page: int) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Récupère une page publique (en général 20 offres), parse l’HTML.
    Retourne (offres, has_next)
    """
    global SESSION
    q = requests.utils.quote(query, safe="")
    url = BASE_LIST.format(q=q) if page <= 1 else PAGE_URL.format(q=q, page=page)

    try:
        resp = SESSION.get(url, timeout=30)
    except requests.exceptions.RequestException as exc:
        # Recreate session with Connection: close on network errors
        try:
            SESSION.close()
        except Exception:
            pass
        SESSION = requests.Session()
        SESSION.headers.update(
            {
                "User-Agent": "JobFinder/1.0 (+https://github.com/OlivierG1729/jobfinder)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{SITE}/nos-offres/",
                "Connection": "close",
            }
        )
        try:
            resp = SESSION.get(url, timeout=30)
        except requests.exceptions.RequestException as exc2:
            raise RuntimeError(f"Erreur réseau lors de la récupération de {url}") from exc2
    if resp.status_code == 404:
        return [], False
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results: List[Dict[str, Any]] = []

    # chaque carte offre
    for card in soup.select(".fr-card.fr-card--offer"):
        a = card.select_one("h3.fr-card__title a")
        if not a or not a.get("href"):
            continue
        title = _html.unescape(a.get_text(strip=True))
        href = _to_absolute(a["href"].strip())

        # tentative d'id depuis l'URL
        oid = href.rstrip("/").split("/")[-1]

        # date : chercher l’élément qui contient "En ligne depuis le ..."
        date_text = ""
        for li in card.select("ul.fr-card__desc li"):
            t = li.get_text(" ", strip=True)
            if "en ligne depuis" in t.lower():
                date_text = t
                break
        iso_date = _parse_date_fr(date_text) if date_text else None

        org_name = None
        detail = card.select_one(".fr-card__detail")
        if detail:
            org_name = detail.get_text(strip=True)

        logo_url = None
        img = card.select_one("img")
        if img and img.get("src"):
            logo_url = _to_absolute(img.get("src"))

        results.append(
            {
                "id": oid,
                "title": title,
                "date": iso_date,          # ISO (YYYY-MM-DD) ou None
                "url": href,               # URL absolue
                "org": org_name,
                "logo": logo_url,
            }
        )

    # pagination : bouton "Suivant" présent ?
    has_next = False
    next_link = soup.select_one(".fr-pagination__link--next[href]")
    if next_link and next_link.get("href"):
        has_next = True

    return results, has_next


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
        (off.get("id") and str(off["id"])) or
        (off.get("_id") and str(off["_id"])) or
        (off.get("offer_id") and str(off["offer_id"])) or
        (off.get("url") or "") or
        (off.get("title") or off.get("intitule") or "")
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

        fetched = []
        with ThreadPoolExecutor() as pool:
            # map conserve l'ordre des pages demandées
            fetched = list(pool.map(lambda p: (p, _fetch_list_page(query, p)), pages))

        stop = False
        for p, (items, has_next) in fetched:
            last_site_page = max(last_site_page, p)
            acc.extend(items)
            if not has_next:
                stop = True
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
        items, _ = _fetch_list_page(query, 1)
        return items

    acc = _get_cached_results(query, limit, refresh_cache=refresh_cache)

    return acc[:limit]


def get_detected_columns() -> Dict[str, Any]:
    """Compat rétro : pas de schéma dynamique ici."""
    return {}
