# backend/service.py
"""Recherche CSP par scraping des pages publiques (parité maximale avec le site).
Stratégie :
- On lit les pages HTML publiques :
  https://choisirleservicepublic.gouv.fr/nos-offres/filtres/mot-cles/<query>/page/N/
- On PARCOURT les pages 1, 2, 3, ... jusqu’à cumuler AU MOINS page*page_size éléments.
- On renvoie la tranche demandée [start:end], triée par date décroissante.
- On expose aussi un total estimé si détectable.
Un fallback AJAX est gardé en dernier recours, mais n’est pas utilisé pour paginer.
"""

from __future__ import annotations

import os
import json
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
import dateparser

# ------------------ Config ------------------

SITE_BASE = "https://choisirleservicepublic.gouv.fr"
LIST_BASE = f"{SITE_BASE}/nos-offres/filtres/mot-cles"
SEARCH_MODE = os.getenv("SEARCH_MODE", "html").lower()  # html|ajax|auto

_session = requests.Session()
DEFAULT_HEADERS = {
    "User-Agent": "JobFinder/1.0",
    "Referer": f"{SITE_BASE}/nos-offres/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ------------------ Utilitaires ------------------

def _parse_any_iso(dt_str: Optional[str]) -> datetime:
    if not dt_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = dt_str.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            dt = dateparser.parse(s, languages=["fr", "en"])
            if dt is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

def extract_offer_id(off: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "_id", "offer_id", "reference", "ref"):
        val = off.get(key)
        if val is not None:
            return str(val)
    return None

def extract_title(off: Dict[str, Any]) -> str:
    for key in ("intitule", "intitulé", "titre", "title", "intituleOffre"):
        val = off.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for val in off.values():
        if isinstance(val, str) and val.strip() and not val.startswith(("http://", "https://")):
            return val.strip()
    return "Offre"

def extract_date(off: Dict[str, Any]) -> Optional[str]:
    for key in ("datePublication", "date_publication", "publication_date", "date",
                "dateEnLigne", "published_at", "createdAt"):
        val = off.get(key)
        if isinstance(val, str) and val:
            return val
    return None

def extract_url(off: Dict[str, Any]) -> Optional[str]:
    for key in ("url", "lien", "link", "apply_url"):
        val = off.get(key)
        if isinstance(val, str) and val:
            return val
    oid = extract_offer_id(off)
    if oid:
        return f"{SITE_BASE}/offre-emploi/{oid}/"
    return None

# ------------------ Pages publiques (HTML) ------------------

def _search_page_url(query: str, page: int) -> str:
    from requests.utils import quote
    base = f"{LIST_BASE}/{quote(query)}/"
    return base if page <= 1 else f"{base}page/{page}/"

def _fetch_list_html(query: str, page: int) -> str:
    url = _search_page_url(query, page)
    r = _session.get(url, headers=DEFAULT_HEADERS, timeout=25)
    if r.status_code == 404:
        # plus de page
        return ""
    r.raise_for_status()
    return r.text

def _total_from_list_html(html: str) -> Optional[int]:
    m = re.search(r'<span class="number">\s*([\d\s]+)\s*</span>', html)
    if not m:
        return None
    try:
        return int(m.group(1).replace(" ", ""))
    except Exception:
        return None

def _parse_list_html(html: str) -> List[Dict[str, Any]]:
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".fr-card.fr-card--offer")
    if len(cards) < 5:
        more = soup.select(".fr-card")
        if len(more) > len(cards):
            cards = more

    out: List[Dict[str, Any]] = []

    def _txt(el):
        if not el:
            return None
        if hasattr(el, "get_text"):
            return el.get_text(strip=True)
        return str(el).strip()

    for c in cards:
        a = c.select_one(".fr-card__title a") or c.find("a")
        title = a.get_text(strip=True) if a else None
        href = a["href"] if a and a.has_attr("href") else None

        loc_el = c.select_one(".fr-icon-map-pin-2-line") or c.find(string=re.compile("Localisation"))
        employer_el = c.select_one(".fr-icon-user-line") or c.find(string=re.compile("Employeur"))
        date_el = c.select_one(".fr-icon-calendar-line") or c.find(string=re.compile("En ligne depuis"))
        date_txt = _txt(date_el)

        dt_iso: Optional[str] = None
        if date_txt:
            m = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', date_txt)
            clean = m.group(1) if m else date_txt
            dt = dateparser.parse(clean, languages=["fr"])
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_iso = dt.isoformat()

        out.append({
            "title": (title or "Offre").strip(),
            "url": href,
            "location": _txt(loc_el),
            "employer": _txt(employer_el),
            "date": dt_iso,
        })

    # Important : on ne limite pas ici ; on trie seulement
    out.sort(key=lambda o: _parse_any_iso(o.get("date")), reverse=True)
    return out

def _html_collect_until(query: str, needed: int) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """
    Récupère séquentiellement page 1, 2, 3, ... et cumule les offres
    jusqu’à atteindre 'needed' éléments OU jusqu’à ce qu’une page soit vide.
    Retourne (liste_cumulée, total_estimé).
    """
    collected: List[Dict[str, Any]] = []
    total_est: Optional[int] = None
    page = 1
    while len(collected) < needed:
        html = _fetch_list_html(query, page)
        if not html:
            break
        if page == 1:
            total_est = _total_from_list_html(html)
        items = _parse_list_html(html)
        if not items:
            break
        collected.extend(items)
        page += 1
        # garde-fou dur en cas de pagination infinie bugguée
        if page > 500:
            break
    # dédoublonnage simple par (title, url) si jamais des pages se répètent
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for it in collected:
        key = (it.get("title"), it.get("url"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped, total_est

def _html_fetch_range_with_total(query: str, page: int, page_size: int) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    start = (page - 1) * page_size
    end = start + page_size
    needed = end  # on accumule jusqu'à avoir au moins 'end' éléments
    bucket, total_est = _html_collect_until(query, needed)
    # slice exact demandé
    slice_ = bucket[start:end]
    # re-tri par sécurité (au cas où)
    slice_.sort(key=lambda o: _parse_any_iso(o.get("date")), reverse=True)
    return slice_, total_est

# ------------------ Fallback AJAX (non utilisé pour paginer) ------------------

def _extract_nonce(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "nonce"})
    if inp and inp.get("value"):
        return inp["value"]
    m = re.search(r'data-nonce="([a-f0-9]{6,})"', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'["\']nonce["\']\s*[:=]\s*["\']([a-zA-Z0-9]+)["\']', html)
    return m.group(1) if m else None

def _post_ajax_raw(query: str, page: int) -> str:
    # On n'utilise pas cette voie pour paginer, juste en dernier recours pour la page 1
    html1 = _fetch_list_html(query, 1)
    nonce = _extract_nonce(html1)
    if not nonce:
        return ""

    filters = {
        "keywords": query,
        "date": [], "contenu": [], "thematique": [], "geoloc": [], "locations": [],
        "domains": [], "versants": [], "categories": [], "organisations": [],
        "jobs": [], "managements": [], "remotes": [], "experiences": [],
        "search_order": ""
    }
    form = {
        "nonce": nonce,
        "query": query,
        "rewrite_url": _search_page_url(query, page),
        "filters": json.dumps(filters, ensure_ascii=False),
        "action": "get_offers",
    }
    headers = dict(DEFAULT_HEADERS)
    headers.update({
        "Referer": form["rewrite_url"],
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        "Origin": SITE_BASE,
    })
    r = _session.post(f"{SITE_BASE}/wp-admin/admin-ajax.php", headers=headers, data=form, timeout=20)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    try:
        payload = r.json()
        return payload.get("html") or payload.get("data") or payload.get("content") or r.text
    except Exception:
        return r.text

def _ajax_first_page_with_total(query: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Dernier recours si la page 1 HTML échoue : tente admin-ajax pour la page 1 seulement."""
    html = _post_ajax_raw(query, 1)
    if not html:
        return [], None
    soup_items = _parse_list_html(html)
    # total : mieux vaut le prendre depuis la page publique si possible
    html_public = _fetch_list_html(query, 1)
    total_est = _total_from_list_html(html_public) if html_public else None
    return soup_items, total_est

# ------------------ API publique ------------------

def search_offers_with_total(
    query: Optional[str],
    page_size: int,
    page: int,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Renvoie (offers, total_estimated)."""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if not query:
        return [], 0

    try:
        if SEARCH_MODE in ("html", "auto"):
            return _html_fetch_range_with_total(query=query, page=page, page_size=page_size)
    except Exception:
        # tente le fallback AJAX uniquement pour sécuriser la page 1
        pass

    if SEARCH_MODE in ("ajax", "auto"):
        first, total = _ajax_first_page_with_total(query)
        # si on demandait page 1 et page_size <= len(first), slice simple
        if page == 1:
            return first[:page_size], total
        # sinon on n'a pas de pagination fiable en AJAX, donc on renvoie ce qu'on peut
        return [], total

def search_offers(
    query: Optional[str] = None,
    page_size: int = 50,
    page: int = 1,
) -> List[Dict[str, Any]]:
    offers, _ = search_offers_with_total(query=query, page_size=page_size, page=page)
    return offers

def get_detected_columns() -> Dict[str, Any]:
    return {}
