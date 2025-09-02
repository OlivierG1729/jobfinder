# backend/service.py
"""
Accès à la recherche de https://choisirleservicepublic.gouv.fr

Stratégie :
1) On tente d'utiliser l'endpoint AJAX officiel (admin-ajax.php) qui alimente le site.
   - On récupère un 'nonce' en chargeant une page publique puis on POSTe
     { action: get_offers, query, filters, rewrite_url } en multipart/form-data.
   - On gère la pagination via page & per_page si exposés ; sinon on découpe côté client.

2) En secours, on tente un endpoint JSON public si un jour il est exposé (BASE_JSON).

On renvoie une liste d'offres normalisées et triées par date décroissante.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import re

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constantes cibles (site WordPress avec admin-ajax)
# ---------------------------------------------------------------------------

SITE = "https://choisirleservicepublic.gouv.fr"
AJAX = f"{SITE}/wp-admin/admin-ajax.php"   # endpoint AJAX WordPress
LISTING_URL = f"{SITE}/nos-offres/"        # page publique pour récupérer le nonce

# S’il existe un jour un vrai endpoint JSON :
BASE_JSON = f"{SITE}/api/offres"  # utilisé en fallback si disponible


# ---------------------------------------------------------------------------
# Helpers HTTP
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "JobFinder/1.0 (+https://github.com/OlivierG1729/jobfinder)",
        "Accept": "*/*",
    }
)


def _iso_or_none(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Normalise quelques formats courants
    try:
        # Ex: 2025-08-24T12:34:56Z
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except Exception:
        pass

    # Ex: "En ligne depuis le 06 août 2025" -> tente d’extraire la date
    m = re.search(r"(\d{1,2})\s+([A-Za-zéûôà]+)\s+(\d{4})", s)
    if m:
        jour, mois_str, an = m.groups()
        mois_map = {
            "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
            "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
            "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
        }
        mois = mois_map.get(mois_str.lower())
        if mois:
            try:
                d = datetime(int(an), int(mois), int(jour))
                return d.isoformat()
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Extraction champs
# ---------------------------------------------------------------------------

def extract_offer_id(off: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "_id", "offer_id", "reference", "ref"):
        if key in off and off[key]:
            return str(off[key])
    # parfois l’URL contient l’identifiant
    url = off.get("url")
    if isinstance(url, str):
        m = re.search(r"/offre-emploi/[^/]+-reference-([^/]+)/?$", url)
        if m:
            return m.group(1)
    return None


def extract_title(off: Dict[str, Any]) -> str:
    for k in ("title", "intitule", "intitulé", "titre"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "Offre"


def extract_date(off: Dict[str, Any]) -> Optional[str]:
    for k in ("publication_date", "datePublication", "date_publication", "date"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return _iso_or_none(v)
    # fallback : parfois une chaîne "En ligne depuis le …"
    if isinstance(off.get("date_text"), str):
        return _iso_or_none(off["date_text"])
    return None


def extract_url(off: Dict[str, Any]) -> Optional[str]:
    for k in ("url", "lien", "link"):
        v = off.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    oid = extract_offer_id(off)
    if oid:
        return f"{SITE}/offre/{oid}"
    return None


# ---------------------------------------------------------------------------
# Récupération du nonce + POST AJAX
# ---------------------------------------------------------------------------

def _fetch_nonce() -> Optional[str]:
    """
    Charge une page publique et essaie d’y récupérer le 'nonce'
    utilisé par l’action AJAX get_offers.
    """
    r = SESSION.get(LISTING_URL, timeout=30)
    r.raise_for_status()
    html = r.text

    # 1) Cherche un script contenant 'ajax_nonce' / 'nonce'
    m = re.search(r'ajax_nonce["\']\s*:\s*["\']([a-zA-Z0-9]+)["\']', html)
    if m:
        return m.group(1)

    # 2) Cherche un meta/hidden input
    soup = BeautifulSoup(html, "html.parser")
    for css in ("input[name=nonce]", "input[name=_ajax_nonce]", "meta[name=nonce]"):
        el = soup.select_one(css)
        if el and (el.get("value") or el.get("content")):
            return el.get("value") or el.get("content")

    # 3) Dernier fallback : heuristique
    m2 = re.search(r'name=["\']nonce["\']\s+value=["\']([a-zA-Z0-9]+)["\']', html)
    if m2:
        return m2.group(1)

    return None


def _ajax_search_site(query: Optional[str], page: int, page_size: int) -> List[Dict[str, Any]]:
    """
    Appelle l’endpoint AJAX du site avec le même payload que le front.
    """
    nonce = _fetch_nonce()
    if not nonce:
        # Si le nonce n’est pas trouvable, on tente quand même (certains sites ne vérifient pas)
        nonce = ""

    # Le site envoie un multipart/form-data ; requests gère ça avec 'files' ou 'data'.
    # Ici, 'data' suffit : WP AJAX lit $_POST.
    filters = {
        "keywords": (query or "").strip(),
        "date": [],
        "contenu": [],
        "thematique": [],
        "geoloc": [],
        "locations": [],
        "domains": [],
        "versants": [],
        "categories": [],
        "organisations": [],
        "jobs": [],
        "managements": [],
        "remotes": [],
        "experiences": [],
        "search_order": "",
        # beaucoup d'implémentations supportent page & per_page
        "page": page,
        "per_page": page_size,
    }

    payload = {
        "nonce": nonce,
        "query": (query or "").strip(),
        "rewrite_url": f"{SITE}/nos-offres/filtres/mot-cles/{(query or '').strip()}/" if query else f"{SITE}/nos-offres/",
        "filters": json.dumps(filters, ensure_ascii=False),
        "action": "get_offers",
    }

    r = SESSION.post(AJAX, data=payload, timeout=30)
    r.raise_for_status()
    # Certaines instances renvoient du HTML ; d’autres du JSON.
    # On tente JSON d’abord, sinon on parse HTML.
    text = r.text.strip()

    # JSON direct ?
    try:
        data = r.json()
        items = data.get("items") or data.get("results") or data.get("data") or []
        return _normalize_items(items)
    except Exception:
        pass

    # HTML -> on extrait les cartes (liens + dates + titres)
    return _parse_offers_from_html(text)


def _normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "id": extract_offer_id(it),
                "title": extract_title(it),
                "date": extract_date(it),
                "url": extract_url(it),
                "raw": it,
            }
        )
    # tri date décroissante
    def key_date(x: Dict[str, Any]) -> datetime:
        d = x.get("date")
        if not d:
            return datetime.min
        try:
            return datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        except Exception:
            return datetime.min

    out.sort(key=key_date, reverse=True)
    return out


def _parse_offers_from_html(html: str) -> List[Dict[str, Any]]:
    """
    Parse le HTML de la liste d’offres (cartes) et extrait titre / url / date.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".fr-card--offer, .fr-card.fr-card--offer, .fr-card__title a")
    results: List[Dict[str, Any]] = []

    # Stratégie : chaque carte possède un <h3 class="fr-card__title"><a href="...">Titre</a></h3>
    for card in soup.select(".fr-card"):
        a = card.select_one("h3.fr-card__title a[href]")
        if not a:
            continue
        url = a.get("href", "").strip()
        title = (a.get_text() or "").strip()

        # texte contenant la date "En ligne depuis le …"
        date_text = None
        for li in card.select("li"):
            t = (li.get_text(" ", strip=True) or "").strip()
            if "En ligne depuis" in t:
                date_text = t
                break

        item = {
            "title": title,
            "url": url,
            "date_text": date_text,
        }
        item["date"] = extract_date(item)
        results.append(item)

    return _normalize_items(results)


# ---------------------------------------------------------------------------
# Fallback JSON (au cas où BASE_JSON existe)
# ---------------------------------------------------------------------------

def _json_api_search(query: Optional[str], page: int, page_size: int) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"page": page, "limit": page_size}
    if query:
        params["q"] = query
    r = SESSION.get(BASE_JSON, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("results") or data.get("data") or []
    return _normalize_items(items)


# ---------------------------------------------------------------------------
# API unique appelée par le backend
# ---------------------------------------------------------------------------

def search_offers(
    query: Optional[str] = None,
    page_size: int = 50,
    page: int = 1,
) -> List[Dict[str, Any]]:
    """
    Recherche principale appelée par l’API FastAPI.
    Tente AJAX (site) puis JSON (fallback).
    """
    # 1) Essai AJAX (site)
    try:
        items = _ajax_search_site(query=query, page=page, page_size=page_size)
        if items:
            return items
    except Exception:
        pass

    # 2) Fallback JSON si dispo
    try:
        return _json_api_search(query=query, page=page, page_size=page_size)
    except Exception:
        # si tout échoue, retourne une liste vide (l’API remontera l’erreur si besoin)
        return []
