# backend/main.py
from __future__ import annotations

import os
import traceback
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path


# ... imports FastAPI ...

# Charge .env via chemin absolu (racine du projet)
try:
    from dotenv import load_dotenv  # type: ignore
    ROOT = Path(__file__).resolve().parents[1]
    ENV_PATH = ROOT / ".env"
    load_dotenv(dotenv_path=ENV_PATH, override=True)
except Exception:
    pass


from .db import init_db, get_conn
from .scheduler import start_scheduler
from .service import (
    search_offers,
    extract_offer_id,
    extract_title,
    extract_date,
    extract_url,
    get_detected_columns,
    _api_get,   # pour debug /raw
)

app = FastAPI(title="CSP Job Search API", version="1.1.0")

# CORS large pour UI locale
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- Modèles Pydantic ---------
class SearchQuery(BaseModel):
    q: Optional[str] = None
    page_size: int = 50
    page: int = 1  # pagination simple

class SaveSearch(BaseModel):
    q: str
    email: Optional[str] = None


# --------- Hooks ---------
@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()


# --------- Endpoints principaux ---------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}

@app.post("/search")
def post_search(body: SearchQuery) -> Dict[str, Any]:
    try:
        offers = search_offers(query=body.q, page_size=body.page_size, page=body.page)
    except Exception as e:
        # remonter l'erreur côté UI si besoin
        raise HTTPException(status_code=400, detail=str(e))

    # Normalisation minimale pour le front
    result = []
    for o in offers:
        result.append(
            {
                "id": extract_offer_id(o),
                "title": extract_title(o),
                "date": extract_date(o),
                "url": extract_url(o),
                "raw": o,  # utile pour debug
            }
        )
    return {"items": result, "page": body.page, "page_size": body.page_size}

@app.post("/save_search")
def save_search(body: SaveSearch) -> Dict[str, Any]:
    con = get_conn()
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO saved_searches(query, email) VALUES (?, ?)",
            (body.q, body.email),
        )
        con.commit()
    finally:
        con.close()
    return {"ok": True}

@app.get("/saved_searches")
def list_saved() -> Dict[str, List[Dict[str, Any]]]:
    con = get_conn()
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id, query, email FROM saved_searches ORDER BY id DESC"
        ).fetchall()
        items = [{"id": r[0], "query": r[1], "email": r[2]} for r in rows]
    finally:
        con.close()
    return {"items": items}


# --------- Endpoints de debug utiles ---------
@app.get("/debug/env")
def debug_env() -> Dict[str, Any]:
    """Vérifie la présence des variables .env (RID + overrides colonnes)."""
    return {
        "RID": os.getenv("RID"),
        "TITLE_KEY": os.getenv("TITLE_KEY"),
        "DATE_KEY": os.getenv("DATE_KEY"),
        "URL_KEY": os.getenv("URL_KEY"),
        "ID_KEY": os.getenv("ID_KEY"),
    }

@app.get("/debug/dotenv")
def debug_dotenv():
    return {
        "env_path": str(ENV_PATH),
        "exists": ENV_PATH.exists(),
        "RID": os.getenv("RID"),
        "TITLE_KEY": os.getenv("TITLE_KEY"),
        "DATE_KEY": os.getenv("DATE_KEY"),
        "ID_KEY": os.getenv("ID_KEY"),
    }


@app.get("/debug/profile")
def debug_profile():
    """Retourne le profil brut (schéma) de la ressource Tabular API."""
    try:
        from .service import PROFILE  # URL complète du /profile/ pour ce RID
        import requests
        r = requests.get(PROFILE, timeout=30)
        content_type = r.headers.get("Content-Type", "")
        return JSONResponse(
            status_code=r.status_code,
            content={
                "ok": r.ok,
                "status_code": r.status_code,
                "content_type": content_type,
                "text": r.text[:5000],  # tronqué pour ne pas surcharger
            },
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

@app.get("/debug/raw")
def debug_raw():
    """Récupère 1 ligne brute depuis /data/ pour voir les vraies clés."""
    try:
        data = _api_get({"page_size": 1})
        rows = data.get("data", [])
        first = rows[0] if rows else {}
        return {
            "ok": True,
            "count": len(rows),
            "first_row_keys": list(first.keys()) if first else [],
            "first_row": first,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

@app.get("/debug/schema")
def debug_schema() -> Dict[str, Any]:
    """Vue combinée : colonnes détectées + 1re ligne + URLs + ENV."""
    out: Dict[str, Any] = {}
    try:
        cols = get_detected_columns()
        out["detected"] = cols
    except Exception as e:
        out["detected_error"] = str(e)

    # Échantillon
    try:
        sample = _api_get({"page_size": 1}).get("data", [])
        first = sample[0] if sample else {}
        out["first_row_keys"] = list(first.keys()) if first else []
        out["first_row"] = first
    except Exception as e:
        out["sample_error"] = str(e)
        out["sample_trace"] = traceback.format_exc()

    # URLs & ENV
    try:
        from .service import BASE, PROFILE
        out["BASE"] = BASE
        out["PROFILE"] = PROFILE
        out["ENV"] = {
            "RID": os.getenv("RID"),
            "TITLE_KEY": os.getenv("TITLE_KEY"),
            "DATE_KEY": os.getenv("DATE_KEY"),
            "URL_KEY": os.getenv("URL_KEY"),
            "ID_KEY": os.getenv("ID_KEY"),
        }
    except Exception as e:
        out["urls_error"] = str(e)

    return out
