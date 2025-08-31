# backend/service.py
from __future__ import annotations

import os
from typing import Optional, List, Dict, Any
from pathlib import Path

import requests

# ----------------------------
# Chargement .env (RID, overrides colonnes)
# ----------------------------
try:
    from dotenv import load_dotenv  # type: ignore
    ROOT = Path(__file__).resolve().parents[1]  # .../JobFinder
    ENV_PATH = ROOT / ".env"
    load_dotenv(dotenv_path=ENV_PATH, override=True)
except Exception:
    pass







RID = os.getenv("RID")
if not RID:
    raise RuntimeError(
        "RID non défini. Créez un fichier .env à la racine et renseignez RID=<uuid_de_ressource_DataGouv>."
    )

BASE = f"https://tabular-api.data.gouv.fr/api/resources/{RID}/data/"
PROFILE = f"https://tabular-api.data.gouv.fr/api/resources/{RID}/profile/"

# Overrides manuels (facultatifs) – à poser dans .env si l’auto-détection échoue
ENV_TITLE = os.getenv("TITLE_KEY")
ENV_DATE = os.getenv("DATE_KEY")
ENV_URL = os.getenv("URL_KEY")
ENV_ID = os.getenv("ID_KEY")

# Candidats par défaut si pas d’override
TITLE_CANDIDATES = ["intitule", "intitulé", "intitulé du poste", "intitulé_du_poste", "titre", "title", "intitulé du poste"]
DATE_CANDIDATES = [
    "datePublication",
    "date_publication",
    "date de première publication",
    "date_de_premiere_publication",
    "publication_date",
    "date",
    "date de début de publication par défaut",
]
URL_CANDIDATES = ["url", "lien", "link"]
ID_CANDIDATES = ["id", "__id", "_id", "identifiant", "offer_id"]

# ----------------------------
# Découverte du schéma (profile)
# ----------------------------
_profile_cache: Optional[Dict[str, Any]] = None
_field_names: set[str] = set()

def _fetch_profile() -> Dict[str, Any]:
    """Récupère et met en cache le profil (schéma) de la ressource."""
    global _profile_cache, _field_names
    if _profile_cache is not None:
        return _profile_cache
    r = requests.get(PROFILE, timeout=30)
    r.raise_for_status()
    prof = r.json()

    fields = []
    if isinstance(prof, dict):
        schema = prof.get("schema")
        if isinstance(schema, dict) and "fields" in schema:
            fields = schema["fields"]
        elif "fields" in prof:
            fields = prof["fields"]

    names: set[str] = set()
    for f in fields or []:
        if isinstance(f, dict) and "name" in f:
            names.add(str(f["name"]))
        elif isinstance(f, str):
            names.add(f)
    _field_names = names
    _profile_cache = prof
    return prof

def _has_field(name: Optional[str]) -> bool:
    if not name:
        return False
    if not _field_names:
        _fetch_profile()
    return name in _field_names

def _pick_existing(candidates: List[str]) -> Optional[str]:
    if not _field_names:
        _fetch_profile()
    # On compare en insensible à la casse / espaces
    lowered = {k.lower(): k for k in _field_names}
    for cand in candidates:
        key_norm = cand.lower()
        if key_norm in lowered:
            return lowered[key_norm]
        # Gestion champs avec espaces/accents : on tente un contains grossier
        for k in lowered:
            if key_norm.replace(" ", "") in k.replace(" ", ""):
                return lowered[k]
    return None

# Choix finaux des colonnes : priorité aux overrides, sinon auto-pick
COLUMN_ID: Optional[str] = ENV_ID if ENV_ID else _pick_existing(ID_CANDIDATES)
COLUMN_TITLE: Optional[str] = ENV_TITLE if ENV_TITLE else _pick_existing(TITLE_CANDIDATES)
COLUMN_DATE: Optional[str] = ENV_DATE if ENV_DATE else _pick_existing(DATE_CANDIDATES)
COLUMN_URL: Optional[str] = ENV_URL if ENV_URL else _pick_existing(URL_CANDIDATES)

# ----------------------------
# Appels API bas niveau
# ----------------------------
def _api_get(params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get(BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# ----------------------------
# Helpers extraction robustes
# ----------------------------
def _find_key_like(d: dict, *needles: str) -> Optional[str]:
    """Retourne la clé dont le nom contient tous les fragments `needles` (insensible casse/espaces/accents simples)."""
    def norm(s: str) -> str:
        return s.lower().replace(" ", "").replace("é", "e").replace("è", "e").replace("ê", "e")
    keys = list(d.keys())
    for k in keys:
        name = norm(str(k))
        if all(norm(n) in name for n in needles):
            return k
    return None

def extract_offer_id(off: dict) -> Optional[str]:
    if COLUMN_ID and COLUMN_ID in off and off[COLUMN_ID] is not None:
        return str(off[COLUMN_ID])
    k = _find_key_like(off, "id")
    if k and off.get(k) is not None:
        return str(off[k])
    for k in ID_CANDIDATES:
        if k in off and off[k] is not None:
            return str(off[k])
    return None

def extract_title(off: dict) -> str:
    if COLUMN_TITLE and COLUMN_TITLE in off and off[COLUMN_TITLE]:
        return str(off[COLUMN_TITLE])
    for patt in [("intitul",), ("titre",), ("title",)]:
        k = _find_key_like(off, *patt)
        if k and off.get(k):
            return str(off[k])
    # fallback : première valeur texte non-URL
    for k, v in off.items():
        if isinstance(v, str) and v.strip() and not v.startswith(("http://", "https://")):
            return v.strip()
    return "Offre"

def extract_date(off: dict) -> Optional[str]:
    if COLUMN_DATE and COLUMN_DATE in off:
        return off.get(COLUMN_DATE)
    for patt in [("date", "premiere", "publication"), ("date", "publi"), ("publication",), ("date",)]:
        k = _find_key_like(off, *patt)
        if k:
            return off.get(k)
    return None

def extract_url(off: dict) -> Optional[str]:
    # Si une colonne URL existe réellement
    if COLUMN_URL and COLUMN_URL in off:
        return off.get(COLUMN_URL)
    # Sinon, reconstruire depuis l'_id si présent (l’URL publique de la fiche CSP)
    if "_id" in off and off.get("_id"):
        return f"https://choisirleservicepublic.gouv.fr/offre/{off['_id']}"
    # Fallback : première valeur qui ressemble à une URL
    for k, v in off.items():
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            return v
    return None

# ----------------------------
# Recherche (avec contournement des champs à espaces)
# ----------------------------
def _has_spaces(s: Optional[str]) -> bool:
    return bool(s) and (" " in s)

def search_offers(query: Optional[str] = None, page_size: int = 50, page: int = 1) -> List[Dict[str, Any]]:
    """
    Version sûre : aucun tri/filtre côté API (évite les 400 si colonnes avec espaces).
    On récupère les lignes brutes puis on filtre/Trie en Python.
    Les paramètres ``page_size`` et ``page`` permettent de contrôler la pagination.
    """
    # 1) Récupération brute (sans __sort / __contains)
    params = {"page_size": page_size, "page": page}
    data = _api_get(params)
    rows: List[Dict[str, Any]] = data.get("data", [])

    # 2) Filtre local (titre) si query
    if query:
        qlow = query.lower()
        def keep(row: Dict[str, Any]) -> bool:
            t = extract_title(row)
            return (t is not None) and (qlow in str(t).lower())
        rows = list(filter(keep, rows))

    # 3) Tri local par date décroissante si on a la colonne de date
    if COLUMN_DATE:
        rows.sort(key=lambda r: r.get(COLUMN_DATE) or "", reverse=True)

    return rows


# ----------------------------
# Debug helper pour /debug/schema
# ----------------------------
def get_detected_columns() -> Dict[str, Any]:
    return {
        "COLUMN_ID": COLUMN_ID,
        "COLUMN_TITLE": COLUMN_TITLE,
        "COLUMN_DATE": COLUMN_DATE,
        "COLUMN_URL": COLUMN_URL,
        "known_fields": sorted(_field_names) if _field_names else [],
        "ENV": {
            "ID_KEY": ENV_ID,
            "TITLE_KEY": ENV_TITLE,
            "DATE_KEY": ENV_DATE,
            "URL_KEY": ENV_URL,
        },
    }
