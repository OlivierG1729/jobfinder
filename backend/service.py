# backend/service.py
"""
Recherche CSP en parsant les pages publiques (fiable et sans nonce).
Objectifs :
- Toujours trier par date décroissante (plus récent -> plus ancien).
- Pagination stable : page 1 = éléments 1..N, page 2 = N+1..2N, etc.
- Dédoublonnage (au cas où une offre apparaisse sur plusieurs pages côté site).
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import html as _html
import re
import hashlib

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
    q = requests.utils.quote(query, safe="")
    url = BASE_LIST.format(q=q) if page <= 1 else PAGE_URL.format(q=q, page=page)

    resp = SESSION.get(url, timeout=30)
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

        results.append(
            {
                "id": oid,
                "title": title,
                "date": iso_date,          # ISO (YYYY-MM-DD) ou None
                "url": href,               # URL absolue
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


def search_offers(
    query: Optional[str] = None,
    page_size: int = 50,
    page: int = 1,
    fast_mode: bool = False,
) -> List[Dict[str, Any]]:
    """
    Pagination user-friendly & STABLE :

      page=1  -> items 1..page_size  (les plus récents)
      page=2  -> items (page_size+1)..(2*page_size)
      etc.

    Implémentation :
    - on cumule des pages du site jusqu'à atteindre page*page_size items,
    - on dédoublonne,
    - on trie : date DESC puis stable_id ASC (ordre stable pour les dates identiques),
    - on découpe par offset (start/end).

    fast_mode:
      Si True, on ne récupère que la page demandée sur le site et on
      retourne la liste telle quelle (page_size ignoré). Cela supprime la
      garantie de pagination stable.
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    if fast_mode:
        items, _ = _fetch_list_page(query, page)
        return items
    need = page * page_size  # combien d'items au total à avoir avant de trancher
    acc: List[Dict[str, Any]] = []
    seen: set[str] = set()
    current_site_page = 1
    has_next = True

    while len(acc) < need and has_next:
        items, has_next = _fetch_list_page(query, current_site_page)
        current_site_page += 1
        for o in items:
            k = _stable_id(o)
            if not k:
                title = extract_title(o)
                date = extract_date(o) or ""
                if title or date:
                    k = hashlib.sha1(f"{title}|{date}".encode("utf-8")).hexdigest()
                else:
                    k = f"idx-{len(acc)}"
            if k not in seen:
                acc.append(o)
                seen.add(k)
        if not items:
            break
        if current_site_page > 500:  # garde-fou
            break

    # Tri STABLE : d'abord tie-breaker (id ASC), puis date DESC
    acc.sort(key=_stable_id)  # id ASC
    acc.sort(key=lambda o: _parse_date_safe(o.get("date")), reverse=True)  # date DESC (stable)

    # Découpage exact
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return acc[start:end]


def get_detected_columns() -> Dict[str, Any]:
    """Compat rétro : pas de schéma dynamique ici."""
    return {}
